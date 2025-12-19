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
