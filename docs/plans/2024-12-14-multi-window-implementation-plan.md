# Multi-Window Agent Tracking - Implementation Plan

## Phase 1: Core Infrastructure

### Task 1.1: Add window listing to tmux.py

**File:** `agentctl/src/agentctl/core/tmux.py`

**Add after `send_keys()` function (~line 138):**

```python
def list_windows(session_name: str) -> List[Dict]:
    """Get all windows in a tmux session.

    Args:
        session_name: Name of the tmux session

    Returns:
        List of window info dicts with keys: index, name, pane_count
        Empty list if session not found
    """
    server = get_server()
    session = server.find_where({"session_name": session_name})

    if not session:
        return []

    windows = []
    for window in session.windows:
        windows.append({
            "index": window.index,
            "name": window.name,
            "pane_count": len(window.panes),
        })

    return windows


def capture_window_pane(
    session_name: str,
    window: int = 0,
    pane: int = 0,
    lines: int = 100
) -> Optional[str]:
    """Capture content from a specific window/pane.

    Args:
        session_name: Name of the tmux session
        window: Window index (default 0)
        pane: Pane index within window (default 0)
        lines: Number of lines to capture

    Returns:
        Captured pane content as string, or None if not found
    """
    server = get_server()
    session = server.find_where({"session_name": session_name})

    if not session:
        return None

    if window >= len(session.windows):
        return None

    target_window = session.windows[window]

    if pane >= len(target_window.panes):
        return None

    target_pane = target_window.panes[pane]

    try:
        captured = target_pane.cmd('capture-pane', '-p', '-S', f'-{lines}')
        return '\n'.join(captured.stdout) if captured.stdout else None
    except Exception:
        return None
```

**Add import at top:** `from typing import List, Dict` (if not present)

---

### Task 1.2: Create config.py module

**File:** `agentctl/src/agentctl/core/config.py` (NEW)

```python
"""Configuration management for agentctl."""

import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml


def get_config_dir() -> Path:
    """Get the agentctl config directory."""
    return Path.home() / ".agentctl"


def get_global_config() -> Dict:
    """Load global configuration from ~/.agentctl/config.yaml."""
    config_file = get_config_dir() / "config.yaml"

    if not config_file.exists():
        return {}

    try:
        with open(config_file) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def get_window_config(task_id: Optional[str] = None) -> List[Dict]:
    """Get window configuration with fallbacks.

    Priority:
    1. Task-specific override (future)
    2. Global config
    3. Empty list (auto-discovery)

    Args:
        task_id: Optional task ID for task-specific overrides

    Returns:
        List of window config dicts with keys: index, name, role (optional)
    """
    # TODO: Add task-specific override lookup

    global_config = get_global_config()
    windows = global_config.get("windows", [])

    # Ensure each window has required fields
    result = []
    for w in windows:
        if isinstance(w, dict) and "index" in w:
            result.append({
                "index": w["index"],
                "name": w.get("name", f"Window {w['index']}"),
                "role": w.get("role"),
            })

    return result


def get_window_name(task_id: Optional[str], window_index: int) -> str:
    """Get display name for a window.

    Args:
        task_id: Optional task ID for task-specific config
        window_index: The window index

    Returns:
        Window name (e.g., "Claude") or fallback ("Window 0")
    """
    windows = get_window_config(task_id)

    for w in windows:
        if w["index"] == window_index:
            return w["name"]

    return f"Window {window_index}"


def get_window_role(task_id: Optional[str], window_index: int) -> Optional[str]:
    """Get role for a window (e.g., 'implementer', 'reviewer').

    Args:
        task_id: Optional task ID for task-specific config
        window_index: The window index

    Returns:
        Role string or None if not configured
    """
    windows = get_window_config(task_id)

    for w in windows:
        if w["index"] == window_index:
            return w.get("role")

    return None
```

---

### Task 1.3: Add multi-window status to agent_monitor.py

**File:** `agentctl/src/agentctl/core/agent_monitor.py`

**Add import at top:**
```python
from .config import get_window_name, get_window_role
```

**Add after `get_session_status()` function (~line 345):**

```python
def get_window_status(session_name: str, window: int, task_id: Optional[str] = None) -> Dict:
    """Get health status for a specific window.

    Args:
        session_name: The tmux session name
        window: Window index
        task_id: Optional task ID for window naming

    Returns:
        Dict with health, icon, summary, index, name
    """
    from .tmux import capture_window_pane, list_windows

    # Check if window exists
    windows = list_windows(session_name)
    window_exists = any(w["index"] == window for w in windows)

    if not window_exists:
        return {
            "index": window,
            "name": get_window_name(task_id, window),
            "health": HEALTH_EXITED,
            "icon": HEALTH_ICONS[HEALTH_EXITED],
            "summary": "Window not found",
        }

    # Capture output from this window
    output = capture_window_pane(session_name, window=window, lines=100)

    if not output:
        return {
            "index": window,
            "name": get_window_name(task_id, window),
            "health": HEALTH_IDLE,
            "icon": HEALTH_ICONS[HEALTH_IDLE],
            "summary": "(no output)",
        }

    # Analyze output for health
    recent_lines = output.split('\n')
    non_empty = [l for l in recent_lines if l.strip()]
    recent_text = "\n".join(recent_lines[-20:])

    # Determine health state
    health = HEALTH_IDLE
    summary = ""

    if ACTIVE_PATTERN in recent_text.lower():
        health = HEALTH_ACTIVE
        summary = generate_smart_summary(recent_text, get_window_role(task_id, window))
    else:
        for pattern in INPUT_PATTERNS:
            if re.search(pattern, recent_text, re.IGNORECASE):
                health = HEALTH_WAITING
                # Extract the prompt line
                for line in reversed(non_empty):
                    if re.search(pattern, line, re.IGNORECASE):
                        summary = f'Waiting: "{line[:40]}..."' if len(line) > 40 else f'Waiting: "{line}"'
                        break
                break

        if health == HEALTH_IDLE:
            for pattern in ERROR_PATTERNS:
                if re.search(pattern, recent_text):
                    health = HEALTH_ERROR
                    summary = "Error detected"
                    break

    # Default summary if not set
    if not summary and non_empty:
        last_line = non_empty[-1]
        summary = last_line[:50] + "..." if len(last_line) > 50 else last_line

    return {
        "index": window,
        "name": get_window_name(task_id, window),
        "health": health,
        "icon": HEALTH_ICONS[health],
        "summary": summary or "(idle)",
    }


def get_all_window_statuses(session_name: str, task_id: Optional[str] = None) -> List[Dict]:
    """Get status for all windows in a session.

    Args:
        session_name: The tmux session name
        task_id: Optional task ID for window naming

    Returns:
        List of window status dicts
    """
    from .tmux import list_windows

    windows = list_windows(session_name)

    if not windows:
        return []

    statuses = []
    for window in windows:
        status = get_window_status(session_name, window["index"], task_id)
        statuses.append(status)

    return statuses


def generate_smart_summary(output: str, role: Optional[str] = None) -> str:
    """Generate a smart summary from output text.

    Args:
        output: Recent output text
        role: Optional window role for context

    Returns:
        Human-readable summary string
    """
    output_lower = output.lower()

    # Test patterns
    if any(p in output_lower for p in ["pytest", "jest", "mocha", "running tests", "test_"]):
        if "passed" in output_lower or "ok" in output_lower:
            return "Tests passing"
        elif "failed" in output_lower or "error" in output_lower:
            return "Tests failing"
        return "Running tests..."

    # Build patterns
    if any(p in output_lower for p in ["building", "compiling", "webpack", "vite", "tsc"]):
        return "Building..."

    # Review patterns (for reviewer role)
    if role == "reviewer" or any(p in output_lower for p in ["reviewing", "diff", "changes"]):
        if "lgtm" in output_lower or "approved" in output_lower:
            return "Review: Approved"
        return "Reviewing..."

    # Git patterns
    if "git push" in output_lower:
        return "Pushing changes..."
    if "git commit" in output_lower:
        return "Committing..."

    # Claude Code patterns
    if "esc to interrupt" in output_lower:
        return "Working..."

    return "Active"
```

---

### Task 1.4: Update existing capture_pane to use new function

**File:** `agentctl/src/agentctl/core/tmux.py`

**Modify existing `capture_pane()` to delegate:**

```python
def capture_pane(session_name: str, lines: int = 100) -> Optional[str]:
    """Capture content from tmux pane (window 0, pane 0).

    This is a convenience wrapper around capture_window_pane for backwards
    compatibility.

    Args:
        session_name: Name of the tmux session
        lines: Number of lines to capture from pane history

    Returns:
        Captured pane content as string, or None if session not found
    """
    return capture_window_pane(session_name, window=0, pane=0, lines=lines)
```

---

## Phase 2: Smart Summaries

Already included in Phase 1 Task 1.3 (`generate_smart_summary`).

Additional patterns can be added to `generate_smart_summary()` as needed.

---

## Phase 3: Dashboard Updates

### Task 3.1: Update Active Agents widget

**File:** `agentctl/src/agentctl/tui.py`

**Find `ActiveAgentsWidget` class and update row rendering to show inline window icons.**

**In the row rendering loop, change from single health icon to multi-window format:**

```python
# Get all window statuses
from agentctl.core.agent_monitor import get_all_window_statuses

window_statuses = get_all_window_statuses(tmux_session, task_id)

# Format inline: "🟢 Claude 🟡 Codex"
if window_statuses:
    windows_display = " ".join(
        f"{w['icon']} {w['name']}" for w in window_statuses
    )
else:
    windows_display = agent_display  # fallback to current behavior
```

---

## Phase 4: TaskDetailScreen Updates

### Task 4.1: Add window state tracking

**File:** `agentctl/src/agentctl/tui.py`

**In `TaskDetailScreen.__init__`:**
```python
self.selected_window = 0  # Currently selected window index
self._window_statuses: List[Dict] = []  # Cached window statuses
```

### Task 4.2: Add window list UI section

**In `TaskDetailScreen.compose()`, add window section before tmux output:**

```python
Container(
    Static("Agent Windows", classes="widget-title"),
    Static("", id="windows-list"),
    id="windows-section"
),
```

### Task 4.3: Add window switching action

```python
def action_switch_window(self) -> None:
    """Cycle through windows (w key)"""
    if not self._window_statuses:
        return

    self.selected_window = (self.selected_window + 1) % len(self._window_statuses)
    self._update_windows_display()
    self._update_tmux_output()
```

### Task 4.4: Update BINDINGS

```python
("w", "switch_window", "Switch Win"),
```

### Task 4.5: Update refresh to load window statuses

In `_refresh_content()`:
```python
from agentctl.core.agent_monitor import get_all_window_statuses

tmux_session = self.task_data.get('tmux_session')
if tmux_session:
    self._window_statuses = get_all_window_statuses(tmux_session, self.task_id)
    self._update_windows_display()
```

### Task 4.6: Add window display update method

```python
def _update_windows_display(self) -> None:
    """Update the windows list display"""
    if not self._window_statuses:
        return

    lines = []
    for w in self._window_statuses:
        marker = "▶ " if w["index"] == self.selected_window else "  "
        lines.append(f"{marker}{w['name']} ({w['index']})  {w['icon']} {w['summary']}")

    windows_widget = self.query_one("#windows-list", Static)
    windows_widget.update("\n".join(lines))
```

### Task 4.7: Update tmux output to use selected window

In `_build_tmux_output_content()`:
```python
from agentctl.core.tmux import capture_window_pane

recent_output = capture_window_pane(
    tmux_session,
    window=self.selected_window,
    lines=200
)
```

---

## Phase 5: Prompt Targeting

### Task 5.1: Add window picker modal

**File:** `agentctl/src/agentctl/tui.py`

```python
class WindowPickerModal(ModalScreen):
    """Modal for selecting which window to send a prompt to"""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, windows: List[Dict]):
        super().__init__()
        self.windows = windows

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Select Window", classes="modal-title"),
            DataTable(id="windows-table"),
            Static("Enter to select, Escape to cancel", classes="modal-hint"),
            id="window-picker-container",
            classes="modal-container"
        )

    def on_mount(self) -> None:
        table = self.query_one("#windows-table", DataTable)
        table.add_columns("Key", "Window", "Status")
        table.cursor_type = "row"

        for i, w in enumerate(self.windows):
            table.add_row(str(i), f"{w['name']} ({w['index']})", f"{w['icon']} {w['summary']}")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.dismiss(self.windows[event.cursor_row]["index"])

    def action_cancel(self) -> None:
        self.dismiss(None)
```

### Task 5.2: Add shift-P binding

```python
("P", "prompt_with_picker", "Prompt (pick window)"),
```

### Task 5.3: Implement prompt with picker

```python
def action_prompt_with_picker(self) -> None:
    """Show window picker then prompt input"""
    tmux_session = self.task_data.get('tmux_session')
    if not tmux_session:
        self.app.notify("No tmux session", severity="warning")
        return

    if not self._window_statuses:
        self.app.notify("No windows found", severity="warning")
        return

    def handle_window_selection(window_index: Optional[int]) -> None:
        if window_index is not None:
            self._prompt_target_window = window_index
            self.action_send_prompt()

    self.app.push_screen(WindowPickerModal(self._window_statuses), handle_window_selection)
```

### Task 5.4: Update send_prompt to use target window

Add instance variable: `self._prompt_target_window: Optional[int] = None`

In the send logic:
```python
target_window = self._prompt_target_window if self._prompt_target_window is not None else self.selected_window
send_keys(tmux_session, prompt_text, window=target_window)
self._prompt_target_window = None  # Reset after use
```

---

## Phase 6: Notifications

### Task 6.1: Update notification state tracking

**File:** `agentctl/src/agentctl/core/agent_monitor.py`

Change `_previous_agent_states` to track per-window:
```python
# Key format: "task_id:window_index"
_previous_window_states: Dict[str, str] = {}
```

### Task 6.2: Update check_and_notify_state_changes

```python
def check_and_notify_state_changes(agents: List[Dict]) -> List[Dict]:
    """Check for agent state changes and send notifications."""
    global _previous_window_states

    notifications = []

    for agent in agents:
        task_id = agent["task_id"]
        tmux_session = agent.get("tmux_session")

        if not tmux_session:
            continue

        window_statuses = get_all_window_statuses(tmux_session, task_id)

        for window in window_statuses:
            state_key = f"{task_id}:{window['index']}"
            current_health = window["health"]
            previous_health = _previous_window_states.get(state_key)

            if previous_health is None:
                _previous_window_states[state_key] = current_health
                continue

            if previous_health != current_health:
                notification = None
                window_label = f"[{window['name']}]"

                if current_health == HEALTH_WAITING:
                    notification = {
                        "task_id": task_id,
                        "window": window["name"],
                        "title": f"🟠 {task_id} {window_label} Waiting",
                        "message": window["summary"],
                        "health": current_health,
                    }
                elif current_health == HEALTH_ERROR:
                    notification = {
                        "task_id": task_id,
                        "window": window["name"],
                        "title": f"⚠️ {task_id} {window_label} Error",
                        "message": "Error detected in output",
                        "health": current_health,
                    }
                # ... other state changes

                if notification:
                    send_desktop_notification(notification["title"], notification["message"])
                    notifications.append(notification)

                _previous_window_states[state_key] = current_health

    return notifications
```

---

## Verification Steps

After each phase:
1. Run `agentctl dash` - should not crash
2. Test with a real multi-window tmux session
3. Verify expected behavior matches design

## Dependencies

- PyYAML (for config.yaml parsing) - check if already installed
