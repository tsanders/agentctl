# Multi-Agent Watch Screen Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a TUI screen that displays compact output from many Claude Code agents simultaneously with keyboard-driven approval workflows.

**Architecture:** New `WatchScreen` class using Textual's Screen pattern, with `AgentCard` widgets arranged in grid/stack/filtered layouts. Output parsing extracts clean 3-4 line summaries from raw tmux output. Approval actions send keys to tmux sessions via existing `send_keys()`.

**Tech Stack:** Python 3.10+, Textual TUI framework, libtmux for session capture/send

---

## Task 1: Create Output Parser Module

**Files:**
- Create: `src/agentctl/core/output_parser.py`
- Create: `tests/core/test_output_parser.py`
- Modify: `pyproject.toml` (add pytest dev dependency)

### Step 1: Add pytest to dev dependencies

Edit `pyproject.toml` to add optional dev dependencies:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
]
```

### Step 2: Create tests directory structure

```bash
mkdir -p tests/core
touch tests/__init__.py
touch tests/core/__init__.py
```

### Step 3: Write failing test for ANSI stripping

Create `tests/core/test_output_parser.py`:

```python
"""Tests for output_parser module"""

import pytest
from agentctl.core.output_parser import strip_ansi, ParsedOutput, PromptInfo


class TestStripAnsi:
    def test_removes_color_codes(self):
        text = "\x1b[32mgreen text\x1b[0m"
        assert strip_ansi(text) == "green text"

    def test_removes_cursor_movement(self):
        text = "\x1b[2J\x1b[H Hello"
        assert strip_ansi(text) == " Hello"

    def test_preserves_plain_text(self):
        text = "plain text without codes"
        assert strip_ansi(text) == "plain text without codes"

    def test_handles_multiple_codes(self):
        text = "\x1b[1m\x1b[31mbold red\x1b[0m normal"
        assert strip_ansi(text) == "bold red normal"
```

### Step 4: Run test to verify it fails

```bash
cd /Users/tylersanders/dev/active/APPS/agentctl/agentctl
uv pip install -e ".[dev]"
uv run pytest tests/core/test_output_parser.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentctl.core.output_parser'`

### Step 5: Write minimal strip_ansi implementation

Create `src/agentctl/core/output_parser.py`:

```python
"""Output parsing utilities for cleaning tmux output and extracting prompts."""

import re
from dataclasses import dataclass
from typing import List, Optional


# ANSI escape sequence pattern
ANSI_PATTERN = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[()][AB012]')


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text.

    Args:
        text: Raw text potentially containing ANSI codes

    Returns:
        Clean text with all ANSI escape sequences removed
    """
    return ANSI_PATTERN.sub('', text)


@dataclass
class PromptInfo:
    """Extracted prompt information from Claude Code output."""
    question: str
    options: List[str]
    selected_index: int = 0


@dataclass
class ParsedOutput:
    """Cleaned and parsed output from a tmux pane."""
    raw_lines: List[str]
    clean_lines: List[str]
    prompt: Optional[PromptInfo] = None
```

### Step 6: Run test to verify it passes

```bash
uv run pytest tests/core/test_output_parser.py::TestStripAnsi -v
```

Expected: PASS (4 tests)

### Step 7: Commit

```bash
git add pyproject.toml tests/ src/agentctl/core/output_parser.py
git commit -m "feat: add output_parser module with ANSI stripping"
```

---

## Task 2: Add Whitespace Cleanup

**Files:**
- Modify: `src/agentctl/core/output_parser.py`
- Modify: `tests/core/test_output_parser.py`

### Step 1: Write failing test for collapse_whitespace

Add to `tests/core/test_output_parser.py`:

```python
from agentctl.core.output_parser import collapse_whitespace


class TestCollapseWhitespace:
    def test_collapses_multiple_blank_lines(self):
        lines = ["line1", "", "", "", "line2"]
        assert collapse_whitespace(lines) == ["line1", "", "line2"]

    def test_trims_trailing_spaces(self):
        lines = ["text with trailing   ", "  leading and trailing  "]
        result = collapse_whitespace(lines)
        assert result == ["text with trailing", "  leading and trailing"]

    def test_removes_trailing_blank_lines(self):
        lines = ["content", "", ""]
        assert collapse_whitespace(lines) == ["content"]

    def test_handles_empty_input(self):
        assert collapse_whitespace([]) == []

    def test_handles_all_blank_lines(self):
        lines = ["", "", ""]
        assert collapse_whitespace(lines) == []
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/core/test_output_parser.py::TestCollapseWhitespace -v
```

Expected: FAIL with `ImportError: cannot import name 'collapse_whitespace'`

### Step 3: Implement collapse_whitespace

Add to `src/agentctl/core/output_parser.py`:

```python
def collapse_whitespace(lines: List[str]) -> List[str]:
    """Collapse multiple blank lines and trim trailing whitespace.

    Args:
        lines: List of text lines

    Returns:
        Cleaned lines with collapsed whitespace
    """
    result = []
    prev_blank = False

    for line in lines:
        # Trim trailing whitespace (preserve leading)
        line = line.rstrip()
        is_blank = len(line) == 0

        # Skip consecutive blank lines
        if is_blank and prev_blank:
            continue

        result.append(line)
        prev_blank = is_blank

    # Remove trailing blank lines
    while result and result[-1] == "":
        result.pop()

    return result
```

### Step 4: Run test to verify it passes

```bash
uv run pytest tests/core/test_output_parser.py::TestCollapseWhitespace -v
```

Expected: PASS (5 tests)

### Step 5: Commit

```bash
git add src/agentctl/core/output_parser.py tests/core/test_output_parser.py
git commit -m "feat: add whitespace collapsing to output_parser"
```

---

## Task 3: Add Prompt Detection and Extraction

**Files:**
- Modify: `src/agentctl/core/output_parser.py`
- Modify: `tests/core/test_output_parser.py`

### Step 1: Write failing test for extract_prompt

Add to `tests/core/test_output_parser.py`:

```python
from agentctl.core.output_parser import extract_prompt


class TestExtractPrompt:
    def test_extracts_create_file_prompt(self):
        lines = [
            " Do you want to create test_auth.py?",
            " > 1. Yes",
            "   2. Yes, allow all edits during this session (shift+tab)",
            "   3. Type here to tell Claude what to do differently",
            "",
            " Esc to cancel",
        ]
        prompt = extract_prompt(lines)
        assert prompt is not None
        assert prompt.question == "Do you want to create test_auth.py?"
        assert len(prompt.options) == 3
        assert prompt.options[0] == "Yes"
        assert prompt.selected_index == 0

    def test_extracts_edit_file_prompt(self):
        lines = [
            " Do you want to edit src/main.py?",
            "   1. Yes",
            " > 2. Yes, allow all edits during this session",
            "   3. Type here...",
        ]
        prompt = extract_prompt(lines)
        assert prompt is not None
        assert prompt.selected_index == 1

    def test_returns_none_for_no_prompt(self):
        lines = [
            "Running tests...",
            "====== 5 passed in 2.3s ======",
        ]
        prompt = extract_prompt(lines)
        assert prompt is None

    def test_extracts_bash_command_prompt(self):
        lines = [
            " Do you want to run this command?",
            " > 1. Yes",
            "   2. No",
        ]
        prompt = extract_prompt(lines)
        assert prompt is not None
        assert "run this command" in prompt.question
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/core/test_output_parser.py::TestExtractPrompt -v
```

Expected: FAIL with `ImportError: cannot import name 'extract_prompt'`

### Step 3: Implement extract_prompt

Add to `src/agentctl/core/output_parser.py`:

```python
# Patterns for detecting Claude Code prompts
PROMPT_QUESTION_PATTERN = re.compile(r'^\s*Do you want to (.+)\?')
PROMPT_OPTION_PATTERN = re.compile(r'^\s*[>]?\s*(\d+)\.\s+(.+)$')
SELECTED_OPTION_PATTERN = re.compile(r'^\s*[>❯]\s*(\d+)\.')


def extract_prompt(lines: List[str]) -> Optional[PromptInfo]:
    """Extract prompt information from Claude Code output.

    Detects prompts like:
      Do you want to create test.py?
      > 1. Yes
        2. Yes, allow all edits...
        3. Type here...

    Args:
        lines: Lines from tmux output

    Returns:
        PromptInfo if a prompt is detected, None otherwise
    """
    question = None
    options = []
    selected_index = 0

    for line in lines:
        # Check for question
        q_match = PROMPT_QUESTION_PATTERN.match(line)
        if q_match:
            question = f"Do you want to {q_match.group(1)}?"
            continue

        # Check for option
        opt_match = PROMPT_OPTION_PATTERN.match(line)
        if opt_match:
            option_num = int(opt_match.group(1))
            option_text = opt_match.group(2).strip()

            # Truncate long options
            if len(option_text) > 50:
                option_text = option_text[:47] + "..."

            options.append(option_text)

            # Check if this option is selected
            if SELECTED_OPTION_PATTERN.match(line):
                selected_index = option_num - 1

    if question and options:
        return PromptInfo(
            question=question,
            options=options,
            selected_index=selected_index
        )

    return None
```

### Step 4: Run test to verify it passes

```bash
uv run pytest tests/core/test_output_parser.py::TestExtractPrompt -v
```

Expected: PASS (4 tests)

### Step 5: Commit

```bash
git add src/agentctl/core/output_parser.py tests/core/test_output_parser.py
git commit -m "feat: add prompt extraction to output_parser"
```

---

## Task 4: Add Main parse_output Function

**Files:**
- Modify: `src/agentctl/core/output_parser.py`
- Modify: `tests/core/test_output_parser.py`

### Step 1: Write failing test for parse_output

Add to `tests/core/test_output_parser.py`:

```python
from agentctl.core.output_parser import parse_output


class TestParseOutput:
    def test_full_parsing_with_prompt(self):
        raw = """
\x1b[32m Some colored output\x1b[0m


 Do you want to create test.py?
 > 1. Yes
   2. No

 Esc to cancel
"""
        result = parse_output(raw, max_lines=4)

        assert len(result.clean_lines) <= 4
        assert result.prompt is not None
        assert result.prompt.question == "Do you want to create test.py?"

    def test_limits_output_lines(self):
        raw = "\n".join([f"line {i}" for i in range(100)])
        result = parse_output(raw, max_lines=4)

        assert len(result.clean_lines) == 4

    def test_prioritizes_prompt_in_output(self):
        raw = """
lots of build output here
more output
even more

 Do you want to proceed?
 > 1. Yes
   2. No
"""
        result = parse_output(raw, max_lines=4)

        # Should include the prompt, not just the first 4 lines
        assert result.prompt is not None
        assert any("proceed" in line.lower() or "yes" in line.lower()
                   for line in result.clean_lines)

    def test_handles_empty_input(self):
        result = parse_output("", max_lines=4)
        assert result.clean_lines == []
        assert result.prompt is None
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/core/test_output_parser.py::TestParseOutput -v
```

Expected: FAIL with `ImportError: cannot import name 'parse_output'`

### Step 3: Implement parse_output

Add to `src/agentctl/core/output_parser.py`:

```python
def parse_output(raw_text: str, max_lines: int = 4) -> ParsedOutput:
    """Parse raw tmux output into clean, compact format.

    Args:
        raw_text: Raw captured output from tmux pane
        max_lines: Maximum number of lines to return (default 4)

    Returns:
        ParsedOutput with cleaned lines and extracted prompt info
    """
    if not raw_text:
        return ParsedOutput(raw_lines=[], clean_lines=[], prompt=None)

    # Split into lines
    raw_lines = raw_text.split('\n')

    # Strip ANSI codes from each line
    stripped_lines = [strip_ansi(line) for line in raw_lines]

    # Collapse whitespace
    collapsed_lines = collapse_whitespace(stripped_lines)

    # Try to extract prompt
    prompt = extract_prompt(collapsed_lines)

    # Select which lines to show
    if prompt:
        # Find prompt start and include it
        clean_lines = _select_prompt_lines(collapsed_lines, max_lines)
    else:
        # Just take the last N non-empty lines
        clean_lines = collapsed_lines[-max_lines:] if collapsed_lines else []

    return ParsedOutput(
        raw_lines=raw_lines,
        clean_lines=clean_lines,
        prompt=prompt
    )


def _select_prompt_lines(lines: List[str], max_lines: int) -> List[str]:
    """Select lines that best represent the prompt.

    Prioritizes showing the question and options.
    """
    # Find the question line
    question_idx = None
    for i, line in enumerate(lines):
        if PROMPT_QUESTION_PATTERN.match(line):
            question_idx = i
            break

    if question_idx is not None:
        # Return from question onwards, limited to max_lines
        return lines[question_idx:question_idx + max_lines]

    # Fallback: return last N lines
    return lines[-max_lines:]
```

### Step 4: Run test to verify it passes

```bash
uv run pytest tests/core/test_output_parser.py::TestParseOutput -v
```

Expected: PASS (4 tests)

### Step 5: Run all parser tests

```bash
uv run pytest tests/core/test_output_parser.py -v
```

Expected: PASS (17 tests total)

### Step 6: Commit

```bash
git add src/agentctl/core/output_parser.py tests/core/test_output_parser.py
git commit -m "feat: add main parse_output function"
```

---

## Task 5: Create AgentCard Widget

**Files:**
- Create: `src/agentctl/tui/watch_screen.py`
- Create: `tests/tui/__init__.py`

### Step 1: Create tui module directory

```bash
mkdir -p src/agentctl/tui
touch src/agentctl/tui/__init__.py
mkdir -p tests/tui
touch tests/tui/__init__.py
```

### Step 2: Create AgentCard widget

Create `src/agentctl/tui/watch_screen.py`:

```python
"""Multi-agent watch screen for monitoring many Claude Code agents."""

from textual.app import ComposeResult
from textual.containers import Container, ScrollableContainer, Horizontal, Vertical
from textual.widgets import Static, Label
from textual.screen import Screen
from textual.reactive import reactive
from typing import List, Dict, Optional, Literal

from agentctl.core.output_parser import parse_output, ParsedOutput
from agentctl.core.tmux import list_sessions, capture_window_pane, send_keys
from agentctl.core.agent_monitor import HEALTH_ICONS, HEALTH_WAITING


class AgentCard(Static):
    """Compact widget showing one agent's output (3-4 lines)."""

    DEFAULT_CSS = """
    AgentCard {
        border: solid $primary;
        padding: 0 1;
        margin: 0 1 1 0;
        height: auto;
        min-height: 5;
        max-height: 7;
    }

    AgentCard.waiting {
        border: solid $warning;
        background: $warning 10%;
    }

    AgentCard.focused {
        border: double $accent;
    }

    AgentCard .card-header {
        text-style: bold;
    }

    AgentCard .card-output {
        color: $text-muted;
    }
    """

    def __init__(
        self,
        task_id: str,
        tmux_session: str,
        health: str = "idle",
        **kwargs
    ):
        super().__init__(**kwargs)
        self.task_id = task_id
        self.tmux_session = tmux_session
        self.health = health
        self.parsed_output: Optional[ParsedOutput] = None

    def compose(self) -> ComposeResult:
        icon = HEALTH_ICONS.get(self.health, "⚪")
        yield Static(f"{self.task_id} {icon}", classes="card-header")
        yield Static("(loading...)", classes="card-output", id="output")

    def update_output(self, raw_output: str) -> None:
        """Update the card with new output."""
        self.parsed_output = parse_output(raw_output, max_lines=3)

        output_widget = self.query_one("#output", Static)
        if self.parsed_output.clean_lines:
            output_widget.update("\n".join(self.parsed_output.clean_lines))
        else:
            output_widget.update("(no output)")

        # Update styling based on prompt detection
        if self.parsed_output.prompt:
            self.add_class("waiting")
            self.health = HEALTH_WAITING
        else:
            self.remove_class("waiting")

    def send_approval(self, option: int = 1) -> bool:
        """Send an approval key to this agent's tmux session.

        Args:
            option: Option number to select (1-4)

        Returns:
            True if sent successfully
        """
        return send_keys(self.tmux_session, str(option), enter=True)

    def send_text(self, text: str) -> bool:
        """Send custom text to this agent's tmux session.

        Args:
            text: Text to send

        Returns:
            True if sent successfully
        """
        return send_keys(self.tmux_session, text, enter=True)
```

### Step 3: Commit

```bash
git add src/agentctl/tui/ tests/tui/
git commit -m "feat: add AgentCard widget for watch screen"
```

---

## Task 6: Create WatchScreen Foundation with Grid View

**Files:**
- Modify: `src/agentctl/tui/watch_screen.py`

### Step 1: Add WatchScreen class with grid layout

Append to `src/agentctl/tui/watch_screen.py`:

```python
class WatchScreen(Screen):
    """Multi-agent monitoring screen with compact cards."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("r", "refresh", "Refresh"),
        ("g", "grid_view", "Grid"),
        ("s", "stack_view", "Stack"),
        ("f", "filtered_view", "Filtered"),
        ("?", "show_help", "Help"),
        # Navigation
        ("up", "nav_up", "Up"),
        ("down", "nav_down", "Down"),
        ("left", "nav_left", "Left"),
        ("right", "nav_right", "Right"),
        ("k", "nav_up", "Up"),
        ("j", "nav_down", "Down"),
        ("h", "nav_left", "Left"),
        ("l", "nav_right", "Right"),
        ("tab", "nav_next_waiting", "Next Waiting"),
        # Approval
        ("y", "approve_yes", "Yes"),
        ("1", "approve_1", "Option 1"),
        ("2", "approve_2", "Option 2"),
        ("3", "approve_3", "Option 3"),
        ("4", "approve_4", "Option 4"),
        ("n", "approve_no", "No"),
        ("t", "type_response", "Type"),
        ("a", "approve_all", "Approve All"),
    ]

    DEFAULT_CSS = """
    WatchScreen {
        layout: vertical;
    }

    WatchScreen #header {
        dock: top;
        height: 3;
        background: $primary;
        padding: 1;
    }

    WatchScreen #grid-container {
        layout: grid;
        grid-size: 3;
        grid-gutter: 1;
        padding: 1;
    }

    WatchScreen #footer {
        dock: bottom;
        height: 1;
        background: $surface;
    }
    """

    view_mode: reactive[Literal["grid", "stack", "filtered"]] = reactive("grid")
    focused_index: reactive[int] = reactive(0)

    def __init__(self):
        super().__init__()
        self.agent_cards: List[AgentCard] = []
        self._refresh_interval = 2.0

    def compose(self) -> ComposeResult:
        yield Static("🔍 AGENT WATCH", id="header")
        yield ScrollableContainer(id="grid-container")
        yield Static("[g]rid [s]tack [f]ilter | [a]pprove all | [?]help", id="footer")

    def on_mount(self) -> None:
        """Initialize and start refresh loop."""
        self._discover_agents()
        self._update_all_outputs()
        self.set_interval(self._refresh_interval, self._update_all_outputs)

    def _discover_agents(self) -> None:
        """Discover all agent-* tmux sessions."""
        container = self.query_one("#grid-container")
        container.remove_children()
        self.agent_cards.clear()

        sessions = list_sessions()
        agent_sessions = [s for s in sessions if s.startswith("agent-")]

        for session in agent_sessions:
            # Extract task_id from session name (agent-TASK-ID)
            task_id = session.replace("agent-", "", 1)
            card = AgentCard(task_id=task_id, tmux_session=session)
            self.agent_cards.append(card)
            container.mount(card)

        if not self.agent_cards:
            container.mount(Static("[dim]No agent sessions found[/dim]"))

    def _update_all_outputs(self) -> None:
        """Refresh output for all agent cards."""
        for card in self.agent_cards:
            raw = capture_window_pane(card.tmux_session, lines=50)
            if raw:
                card.update_output(raw)

    def _get_waiting_cards(self) -> List[AgentCard]:
        """Get list of cards that are waiting for input."""
        return [c for c in self.agent_cards if c.parsed_output and c.parsed_output.prompt]

    def _get_focused_card(self) -> Optional[AgentCard]:
        """Get the currently focused card."""
        if 0 <= self.focused_index < len(self.agent_cards):
            return self.agent_cards[self.focused_index]
        return None

    # Actions
    def action_go_back(self) -> None:
        """Return to previous screen."""
        self.app.pop_screen()

    def action_refresh(self) -> None:
        """Force refresh all outputs."""
        self._discover_agents()
        self._update_all_outputs()

    def action_approve_yes(self) -> None:
        """Send yes/1 to focused agent."""
        self._send_to_focused(1)

    def action_approve_1(self) -> None:
        self._send_to_focused(1)

    def action_approve_2(self) -> None:
        self._send_to_focused(2)

    def action_approve_3(self) -> None:
        self._send_to_focused(3)

    def action_approve_4(self) -> None:
        self._send_to_focused(4)

    def action_approve_no(self) -> None:
        """Send no/2 to focused agent."""
        self._send_to_focused(2)

    def action_approve_all(self) -> None:
        """Approve all waiting agents with option 1."""
        waiting = self._get_waiting_cards()
        for card in waiting:
            # Safety check - skip destructive prompts
            if card.parsed_output and card.parsed_output.prompt:
                question = card.parsed_output.prompt.question.lower()
                if any(word in question for word in ["delete", "remove", "overwrite", "destroy"]):
                    continue
            card.send_approval(1)
        self.notify(f"Approved {len(waiting)} agents")

    def _send_to_focused(self, option: int) -> None:
        """Send option to focused card."""
        card = self._get_focused_card()
        if card:
            if card.send_approval(option):
                self.notify(f"Sent {option} to {card.task_id}")
            else:
                self.notify(f"Failed to send to {card.task_id}", severity="error")

    # Navigation
    def action_nav_up(self) -> None:
        self._navigate(-3)  # Move up one row in 3-column grid

    def action_nav_down(self) -> None:
        self._navigate(3)

    def action_nav_left(self) -> None:
        self._navigate(-1)

    def action_nav_right(self) -> None:
        self._navigate(1)

    def action_nav_next_waiting(self) -> None:
        """Jump to next waiting card."""
        waiting = self._get_waiting_cards()
        if not waiting:
            return

        # Find next waiting card after current focus
        for i, card in enumerate(self.agent_cards):
            if i > self.focused_index and card in waiting:
                self.focused_index = i
                self._update_focus()
                return

        # Wrap around
        for i, card in enumerate(self.agent_cards):
            if card in waiting:
                self.focused_index = i
                self._update_focus()
                return

    def _navigate(self, delta: int) -> None:
        """Navigate by delta positions."""
        if not self.agent_cards:
            return
        new_index = (self.focused_index + delta) % len(self.agent_cards)
        self.focused_index = new_index
        self._update_focus()

    def _update_focus(self) -> None:
        """Update visual focus indicator."""
        for i, card in enumerate(self.agent_cards):
            if i == self.focused_index:
                card.add_class("focused")
            else:
                card.remove_class("focused")
```

### Step 2: Commit

```bash
git add src/agentctl/tui/watch_screen.py
git commit -m "feat: add WatchScreen with grid view and navigation"
```

---

## Task 7: Add CLI Command for Watch Screen

**Files:**
- Modify: `src/agentctl/cli.py`

### Step 1: Add watch command to CLI

Add after the `dash` command in `src/agentctl/cli.py`:

```python
@app.command()
def watch():
    """Launch multi-agent watch screen for monitoring and approvals"""
    from agentctl.tui import run_watch_screen
    run_watch_screen()
```

### Step 2: Add run_watch_screen function to tui module

Add to `src/agentctl/tui/__init__.py`:

```python
"""TUI module for agentctl."""

from agentctl.tui.watch_screen import WatchScreen


def run_watch_screen():
    """Run the watch screen as a standalone app."""
    from textual.app import App

    class WatchApp(App):
        """Minimal app to host watch screen."""

        def on_mount(self):
            self.push_screen(WatchScreen())

    app = WatchApp()
    app.run()
```

### Step 3: Test manually

```bash
cd /Users/tylersanders/dev/active/APPS/agentctl/agentctl
uv run agentctl watch
```

Expected: Watch screen opens (may show "No agent sessions found" if no agents running)

### Step 4: Commit

```bash
git add src/agentctl/cli.py src/agentctl/tui/__init__.py
git commit -m "feat: add 'agentctl watch' CLI command"
```

---

## Task 8: Add Stack (Priority) View

**Files:**
- Modify: `src/agentctl/tui/watch_screen.py`

### Step 1: Add stack view container and CSS

Update the `DEFAULT_CSS` in `WatchScreen`:

```python
    DEFAULT_CSS = """
    WatchScreen {
        layout: vertical;
    }

    WatchScreen #header {
        dock: top;
        height: 3;
        background: $primary;
        padding: 1;
    }

    WatchScreen #grid-container {
        layout: grid;
        grid-size: 3;
        grid-gutter: 1;
        padding: 1;
    }

    WatchScreen #stack-container {
        padding: 1;
    }

    WatchScreen .section-header {
        text-style: bold;
        padding: 0 0 1 0;
    }

    WatchScreen .collapsed-card {
        height: 1;
        border: none;
        padding: 0 1;
    }

    WatchScreen #footer {
        dock: bottom;
        height: 1;
        background: $surface;
    }
    """
```

### Step 2: Add view mode switching and stack rendering

Add methods to `WatchScreen`:

```python
    def watch_view_mode(self, new_mode: str) -> None:
        """React to view mode changes."""
        self._render_current_view()

    def action_grid_view(self) -> None:
        self.view_mode = "grid"

    def action_stack_view(self) -> None:
        self.view_mode = "stack"

    def action_filtered_view(self) -> None:
        self.view_mode = "filtered"

    def _render_current_view(self) -> None:
        """Re-render the current view mode."""
        # Remove existing containers
        for container_id in ["grid-container", "stack-container", "filtered-container"]:
            try:
                self.query_one(f"#{container_id}").remove()
            except Exception:
                pass

        if self.view_mode == "grid":
            self._render_grid_view()
        elif self.view_mode == "stack":
            self._render_stack_view()
        elif self.view_mode == "filtered":
            self._render_filtered_view()

    def _render_grid_view(self) -> None:
        """Render agents in a grid layout."""
        container = ScrollableContainer(id="grid-container")
        self.mount(container, before=self.query_one("#footer"))

        for card in self.agent_cards:
            container.mount(card)

    def _render_stack_view(self) -> None:
        """Render agents in priority stack (waiting on top, expanded)."""
        from textual.containers import Vertical

        container = ScrollableContainer(id="stack-container")
        self.mount(container, before=self.query_one("#footer"))

        waiting = self._get_waiting_cards()
        active = [c for c in self.agent_cards if c not in waiting]

        # Waiting section (expanded)
        if waiting:
            container.mount(Static(f"🟠 NEEDS ATTENTION ({len(waiting)})", classes="section-header"))
            for card in waiting:
                container.mount(card)

        # Active section (collapsed to single lines)
        if active:
            container.mount(Static(f"🟢 ACTIVE ({len(active)})", classes="section-header"))
            for card in active:
                summary = card.task_id
                if card.parsed_output and card.parsed_output.clean_lines:
                    summary += f"  {card.parsed_output.clean_lines[0][:40]}"
                container.mount(Static(summary, classes="collapsed-card"))
```

### Step 3: Commit

```bash
git add src/agentctl/tui/watch_screen.py
git commit -m "feat: add stack (priority) view to watch screen"
```

---

## Task 9: Add Filtered Tabs View

**Files:**
- Modify: `src/agentctl/tui/watch_screen.py`

### Step 1: Add filtered view with tab bar

Add to `WatchScreen`:

```python
    current_filter: reactive[str] = reactive("attention")

    def _render_filtered_view(self) -> None:
        """Render agents with filter tabs."""
        from textual.containers import Vertical, Horizontal

        container = Vertical(id="filtered-container")
        self.mount(container, before=self.query_one("#footer"))

        waiting = self._get_waiting_cards()
        active = [c for c in self.agent_cards if c.health in ("active",) and c not in waiting]
        idle = [c for c in self.agent_cards if c not in waiting and c not in active]

        # Tab bar
        tabs = Horizontal(
            Static(f"[{'>' if self.current_filter == 'attention' else ' '}Attention: {len(waiting)}] ", id="tab-attention"),
            Static(f"[{'>' if self.current_filter == 'active' else ' '}Active: {len(active)}] ", id="tab-active"),
            Static(f"[{'>' if self.current_filter == 'idle' else ' '}Idle: {len(idle)}] ", id="tab-idle"),
            Static(f"[{'>' if self.current_filter == 'all' else ' '}All: {len(self.agent_cards)}]", id="tab-all"),
            classes="tab-bar"
        )
        container.mount(tabs)

        # Content based on filter
        content = ScrollableContainer(id="filtered-content")
        container.mount(content)

        cards_to_show = {
            "attention": waiting,
            "active": active,
            "idle": idle,
            "all": self.agent_cards,
        }.get(self.current_filter, self.agent_cards)

        for card in cards_to_show:
            content.mount(card)

    def action_filter_attention(self) -> None:
        self.current_filter = "attention"
        if self.view_mode == "filtered":
            self._render_current_view()

    def action_filter_active(self) -> None:
        self.current_filter = "active"
        if self.view_mode == "filtered":
            self._render_current_view()

    def action_filter_idle(self) -> None:
        self.current_filter = "idle"
        if self.view_mode == "filtered":
            self._render_current_view()

    def action_filter_all(self) -> None:
        self.current_filter = "all"
        if self.view_mode == "filtered":
            self._render_current_view()
```

### Step 2: Add tab switching keybindings

Add to `BINDINGS` in `WatchScreen`:

```python
        # Tab filtering (when in filtered view)
        ("1", "filter_attention", "Attention"),
        ("2", "filter_active", "Active"),
        ("3", "filter_idle", "Idle"),
        ("4", "filter_all", "All"),
```

Note: These conflict with approval keys. We need to make them context-aware.

### Step 3: Make number keys context-aware

Update the approval actions:

```python
    def action_approve_1(self) -> None:
        if self.view_mode == "filtered":
            self.action_filter_attention()
        else:
            self._send_to_focused(1)

    def action_approve_2(self) -> None:
        if self.view_mode == "filtered":
            self.action_filter_active()
        else:
            self._send_to_focused(2)

    def action_approve_3(self) -> None:
        if self.view_mode == "filtered":
            self.action_filter_idle()
        else:
            self._send_to_focused(3)

    def action_approve_4(self) -> None:
        if self.view_mode == "filtered":
            self.action_filter_all()
        else:
            self._send_to_focused(4)
```

### Step 4: Commit

```bash
git add src/agentctl/tui/watch_screen.py
git commit -m "feat: add filtered tabs view to watch screen"
```

---

## Task 10: Add Text Input Modal for Custom Responses

**Files:**
- Modify: `src/agentctl/tui/watch_screen.py`

### Step 1: Create TextInputModal class

Add to `src/agentctl/tui/watch_screen.py`:

```python
from textual.screen import ModalScreen
from textual.widgets import Input, Button


class TextInputModal(ModalScreen):
    """Modal for typing custom response to an agent."""

    DEFAULT_CSS = """
    TextInputModal {
        align: center middle;
    }

    TextInputModal > Container {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    TextInputModal Input {
        margin: 1 0;
    }

    TextInputModal .buttons {
        align: center middle;
        height: 3;
    }
    """

    def __init__(self, task_id: str, tmux_session: str):
        super().__init__()
        self.task_id = task_id
        self.tmux_session = tmux_session

    def compose(self) -> ComposeResult:
        yield Container(
            Label(f"Send to {self.task_id}:"),
            Input(placeholder="Type your response...", id="response-input"),
            Horizontal(
                Button("Send", variant="primary", id="send-btn"),
                Button("Cancel", id="cancel-btn"),
                classes="buttons"
            )
        )

    def on_mount(self) -> None:
        self.query_one("#response-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-btn":
            self._send_response()
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._send_response()

    def _send_response(self) -> None:
        text = self.query_one("#response-input", Input).value
        if text:
            send_keys(self.tmux_session, text, enter=True)
            self.dismiss(text)
        else:
            self.dismiss(None)
```

### Step 2: Add type_response action to WatchScreen

Add to `WatchScreen`:

```python
    def action_type_response(self) -> None:
        """Open text input modal for custom response."""
        card = self._get_focused_card()
        if card:
            def on_dismiss(result):
                if result:
                    self.notify(f"Sent to {card.task_id}")

            self.push_screen(
                TextInputModal(card.task_id, card.tmux_session),
                on_dismiss
            )
```

### Step 3: Commit

```bash
git add src/agentctl/tui/watch_screen.py
git commit -m "feat: add text input modal for custom responses"
```

---

## Task 11: Add Help Overlay

**Files:**
- Modify: `src/agentctl/tui/watch_screen.py`

### Step 1: Create HelpModal class

Add to `src/agentctl/tui/watch_screen.py`:

```python
class WatchHelpModal(ModalScreen):
    """Help overlay showing all keybindings."""

    BINDINGS = [("escape", "dismiss", "Close"), ("question_mark", "dismiss", "Close")]

    DEFAULT_CSS = """
    WatchHelpModal {
        align: center middle;
    }

    WatchHelpModal > Container {
        width: 70;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        help_text = """
[bold]Navigation[/bold]
  ↑/↓/←/→ or hjkl   Move between cards
  Tab               Jump to next waiting agent
  Enter             Expand focused card

[bold]Approval[/bold]
  y or 1            Send Yes/option 1 to focused agent
  n or 2            Send No/option 2
  3, 4              Send option 3 or 4
  t                 Type custom response
  a                 Approve ALL waiting agents

[bold]Views[/bold]
  g                 Grid view (default)
  s                 Stack view (waiting expanded at top)
  f                 Filtered tabs view
  1-4 (filtered)    Switch filter tabs

[bold]Other[/bold]
  r                 Refresh all outputs
  Escape            Return to dashboard
  ?                 Show this help
"""
        yield Container(
            Label("[bold]Watch Screen Help[/bold]"),
            Static(help_text),
        )
```

### Step 2: Add show_help action

Add to `WatchScreen`:

```python
    def action_show_help(self) -> None:
        """Show help overlay."""
        self.push_screen(WatchHelpModal())
```

### Step 3: Commit

```bash
git add src/agentctl/tui/watch_screen.py
git commit -m "feat: add help overlay to watch screen"
```

---

## Task 12: Add 'w' Keybinding to Main Dashboard

**Files:**
- Modify: `src/agentctl/tui.py`

### Step 1: Add WatchScreen import and binding

Add import at top of `tui.py`:

```python
from agentctl.tui.watch_screen import WatchScreen
```

Add keybinding to the main `AgentCtlApp` class BINDINGS:

```python
        ("w", "watch_screen", "Watch"),
```

Add action method:

```python
    def action_watch_screen(self) -> None:
        """Open multi-agent watch screen."""
        self.push_screen(WatchScreen())
```

### Step 2: Test from dashboard

```bash
uv run agentctl dash
# Press 'w' to open watch screen
```

### Step 3: Commit

```bash
git add src/agentctl/tui.py
git commit -m "feat: add 'w' keybinding to open watch screen from dashboard"
```

---

## Task 13: Add Safety Checks for Destructive Prompts

**Files:**
- Modify: `src/agentctl/core/output_parser.py`
- Modify: `tests/core/test_output_parser.py`

### Step 1: Write failing test for is_destructive_prompt

Add to `tests/core/test_output_parser.py`:

```python
from agentctl.core.output_parser import is_destructive_prompt


class TestIsDestructivePrompt:
    def test_detects_delete(self):
        prompt = PromptInfo("Do you want to delete this file?", ["Yes", "No"], 0)
        assert is_destructive_prompt(prompt) is True

    def test_detects_remove(self):
        prompt = PromptInfo("Do you want to remove all data?", ["Yes", "No"], 0)
        assert is_destructive_prompt(prompt) is True

    def test_detects_overwrite(self):
        prompt = PromptInfo("Do you want to overwrite existing.py?", ["Yes", "No"], 0)
        assert is_destructive_prompt(prompt) is True

    def test_safe_prompt_returns_false(self):
        prompt = PromptInfo("Do you want to create test.py?", ["Yes", "No"], 0)
        assert is_destructive_prompt(prompt) is False
```

### Step 2: Run test to verify it fails

```bash
uv run pytest tests/core/test_output_parser.py::TestIsDestructivePrompt -v
```

### Step 3: Implement is_destructive_prompt

Add to `src/agentctl/core/output_parser.py`:

```python
DESTRUCTIVE_KEYWORDS = ["delete", "remove", "overwrite", "destroy", "drop", "truncate", "wipe"]


def is_destructive_prompt(prompt: PromptInfo) -> bool:
    """Check if a prompt appears to be destructive.

    Args:
        prompt: PromptInfo to check

    Returns:
        True if the prompt contains destructive keywords
    """
    question_lower = prompt.question.lower()
    return any(keyword in question_lower for keyword in DESTRUCTIVE_KEYWORDS)
```

### Step 4: Run test to verify it passes

```bash
uv run pytest tests/core/test_output_parser.py::TestIsDestructivePrompt -v
```

### Step 5: Update approve_all to use is_destructive_prompt

In `src/agentctl/tui/watch_screen.py`, update `action_approve_all`:

```python
from agentctl.core.output_parser import is_destructive_prompt

    def action_approve_all(self) -> None:
        """Approve all waiting agents with option 1 (skip destructive)."""
        waiting = self._get_waiting_cards()
        approved = 0
        skipped = 0

        for card in waiting:
            if card.parsed_output and card.parsed_output.prompt:
                if is_destructive_prompt(card.parsed_output.prompt):
                    skipped += 1
                    continue
            card.send_approval(1)
            approved += 1

        msg = f"Approved {approved}"
        if skipped:
            msg += f", skipped {skipped} destructive"
        self.notify(msg)
```

### Step 6: Commit

```bash
git add src/agentctl/core/output_parser.py tests/core/test_output_parser.py src/agentctl/tui/watch_screen.py
git commit -m "feat: add safety checks for destructive prompts in approve-all"
```

---

## Task 14: Final Integration and Testing

**Files:**
- All files

### Step 1: Run all tests

```bash
cd /Users/tylersanders/dev/active/APPS/agentctl/agentctl
uv run pytest tests/ -v
```

Expected: All tests pass

### Step 2: Manual testing checklist

1. Start some test tmux sessions:
```bash
tmux new-session -d -s agent-TEST-001
tmux new-session -d -s agent-TEST-002
```

2. Run watch screen:
```bash
uv run agentctl watch
```

3. Verify:
- [ ] Grid view shows cards
- [ ] Press 's' for stack view
- [ ] Press 'f' for filtered view
- [ ] Arrow keys navigate
- [ ] Tab jumps to waiting agents
- [ ] 'y' sends approval (check tmux)
- [ ] 't' opens text input
- [ ] 'a' approves all
- [ ] '?' shows help
- [ ] Escape returns to dashboard

4. Clean up test sessions:
```bash
tmux kill-session -t agent-TEST-001
tmux kill-session -t agent-TEST-002
```

### Step 3: Final commit

```bash
git add -A
git commit -m "feat: complete multi-agent watch screen implementation"
```

---

## Summary

This plan implements the multi-agent watch screen in 14 tasks:

1. **Tasks 1-4:** Output parser with ANSI stripping, whitespace cleanup, and prompt extraction
2. **Tasks 5-6:** AgentCard widget and WatchScreen with grid layout
3. **Task 7:** CLI command `agentctl watch`
4. **Tasks 8-9:** Stack and filtered views
5. **Tasks 10-11:** Text input modal and help overlay
6. **Task 12:** Dashboard 'w' keybinding integration
7. **Tasks 13-14:** Safety checks and final testing

Each task is small (5-15 minutes) with explicit test-first approach and commits after each feature.
