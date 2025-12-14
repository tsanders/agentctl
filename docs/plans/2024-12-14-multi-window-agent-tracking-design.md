# Multi-Window Agent Tracking Design

## Overview

Enable agentctl to track multiple tmux windows within a single task session. This supports workflows where multiple agents collaborate on one task (e.g., Claude Code in window 0 implements, Codex in window 1 reviews).

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Window relationship to task | Same task, collaborating | Both windows work on the same task |
| Configuration scope | Global defaults + per-task overrides | Simple defaults, flexible when needed |
| Monitoring detail | Health + smart summary | Quick understanding without reading raw output |
| Prompt targeting | Default (p) + modifier (P) for selection | Fast path for common case |
| Dashboard display | Single row, inline icons per window | Compact, at-a-glance status |

## Data Model

### Global Configuration (`~/.agentctl/config.yaml`)

```yaml
windows:
  - index: 0
    name: "Claude"
    role: "implementer"
  - index: 1
    name: "Codex"
    role: "reviewer"
```

### Per-Task Override (task frontmatter or database)

```yaml
windows:
  - index: 0
    name: "Claude"
  - index: 1
    name: "Codex"
  - index: 2
    name: "Tests"
```

### Configuration Loading Priority

1. Task-specific override
2. Project-level config (future)
3. Global config (`~/.agentctl/config.yaml`)
4. Auto-discovery fallback ("Window N")

## Core Module Changes

### `tmux.py` additions

```python
def list_windows(session_name: str) -> List[Dict]:
    """Get all windows in a session.

    Returns:
        List of dicts: [{"index": 0, "name": "bash", "pane_count": 1}, ...]
    """

def capture_window_pane(
    session_name: str,
    window: int = 0,
    pane: int = 0,
    lines: int = 100
) -> Optional[str]:
    """Capture output from a specific window/pane."""
```

### `agent_monitor.py` additions

```python
def get_window_status(session_name: str, window: int) -> Dict:
    """Get health status for a specific window.

    Returns:
        {"health": "active", "icon": "...", "summary": "Running tests..."}
    """

def get_all_window_statuses(session_name: str) -> List[Dict]:
    """Get status for all windows in a session.

    Returns:
        List of window status dicts with health, icon, summary, index, name
    """
```

### `config.py` (new)

```python
def get_window_config(task_id: Optional[str] = None) -> List[Dict]:
    """Get window configuration with fallbacks."""

def get_window_name(task_id: str, window_index: int) -> str:
    """Get display name for a window (e.g., 'Claude' or 'Window 0')."""
```

### Smart Summary Detection

Extends current pattern matching to generate human-readable summaries:

| Pattern | Summary |
|---------|---------|
| Test runner output | "Running tests..." |
| Review/diff patterns | "Reviewing..." |
| Input prompt detected | "Waiting for input" |
| Build tool output | "Building..." |
| Default | Truncated last meaningful line |

## UI Changes

### Active Agents Dashboard Row

```
TASK-001 | ... Claude ... Codex | impl... | 5m | human_review
```

- Health icon + name for each window inline
- Row selection opens TaskDetailScreen as before

### TaskDetailScreen - Window Output Section

```
... Agent Windows ...............................................
  [W] Switch Window

  . Claude (0)  ... Running tests...
    Codex (1)   ... Waiting: "Ready to review?"

  ================================================================
  $ pytest src/tests/
  ====== 15 passed in 2.3s ======
  (output from selected window)
..................................................................
```

### Key Bindings

| Key | Action |
|-----|--------|
| `w` | Cycle through windows (selected shown with marker) |
| `t` | Toggle output lines (10/100) for current window |
| `p` | Send prompt to window 0 (or currently selected) |
| `P` | Show window picker, then prompt input |

## Notifications

- Each window monitored independently for state changes
- Format: `"... TASK-001 [Codex] Waiting for input"`
- Only the window that changed triggers notification

## Implementation Plan

### Phase 1: Core Infrastructure
1. Add `list_windows()` to `tmux.py`
2. Add `capture_window_pane()` to `tmux.py`
3. Create `config.py` with window configuration loading
4. Add `get_window_status()` to `agent_monitor.py`
5. Add `get_all_window_statuses()` to `agent_monitor.py`

### Phase 2: Smart Summaries
1. Add summary pattern detection to `agent_monitor.py`
2. Implement role-aware summary generation

### Phase 3: Dashboard Updates
1. Update Active Agents widget to show inline window icons
2. Modify row rendering for multi-window display

### Phase 4: TaskDetailScreen Updates
1. Add window list UI section
2. Implement window switching (`w` key)
3. Update output display to show selected window
4. Track selected window state

### Phase 5: Prompt Targeting
1. Add `P` binding for window selection
2. Create window picker modal
3. Update `send_keys()` calls to use selected window

### Phase 6: Notifications
1. Update notification system to track per-window state
2. Include window name in notification messages

## Testing

- Unit tests for `list_windows()`, `capture_window_pane()`
- Unit tests for config loading with fallbacks
- Integration test with multi-window tmux session
- UI tests for window switching behavior
