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
