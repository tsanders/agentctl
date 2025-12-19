"""Multi-agent watch screen for monitoring many Claude Code agents."""

from textual.app import ComposeResult
from textual.containers import Container, ScrollableContainer, Horizontal, Vertical
from textual.widgets import Static, Label, Input, Button
from textual.screen import Screen, ModalScreen
from textual.reactive import reactive
from textual.css.query import NoMatches
from typing import List, Dict, Optional, Literal

from agentctl.core.output_parser import parse_output, ParsedOutput, is_destructive_prompt
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

    WatchScreen .tab-bar {
        height: 1;
        padding: 0 1;
    }

    WatchScreen #footer {
        dock: bottom;
        height: 1;
        background: $surface;
    }
    """

    view_mode: reactive[Literal["grid", "stack", "filtered"]] = reactive("grid")
    focused_index: reactive[int] = reactive(0)
    current_filter: reactive[str] = reactive("attention")

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

    def watch_view_mode(self, new_mode: str) -> None:
        """React to view mode changes."""
        self._render_current_view()

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

    def _render_current_view(self) -> None:
        """Render the appropriate view based on view_mode."""
        # Remove existing containers
        for container_id in ["grid-container", "stack-container", "filtered-container"]:
            try:
                existing = self.query_one(f"#{container_id}")
                existing.remove()
            except NoMatches:
                pass  # Container doesn't exist, which is expected

        # Render the appropriate view
        if self.view_mode == "grid":
            self._render_grid_view()
        elif self.view_mode == "stack":
            self._render_stack_view()
        elif self.view_mode == "filtered":
            self._render_filtered_view()

    def _render_grid_view(self) -> None:
        """Render grid view with all agent cards."""
        container = ScrollableContainer(id="grid-container")
        for card in self.agent_cards:
            container.mount(card)
        if not self.agent_cards:
            container.mount(Static("[dim]No agent sessions found[/dim]"))
        self.mount(container, before=self.query_one("#footer"))

    def _render_stack_view(self) -> None:
        """Render stack view with waiting cards expanded and active cards collapsed."""
        container = ScrollableContainer(id="stack-container")

        # Get waiting and active cards
        waiting_cards = self._get_waiting_cards()
        active_cards = [c for c in self.agent_cards if c not in waiting_cards]

        # Waiting section
        if waiting_cards:
            header = Static(f"🟠 NEEDS ATTENTION ({len(waiting_cards)})", classes="section-header")
            container.mount(header)
            for card in waiting_cards:
                container.mount(card)

        # Active section
        if active_cards:
            header = Static(f"🟢 ACTIVE ({len(active_cards)})", classes="section-header")
            container.mount(header)
            for card in active_cards:
                # Create collapsed single-line summary
                first_line = ""
                if card.parsed_output and card.parsed_output.clean_lines:
                    first_line = card.parsed_output.clean_lines[0][:40]
                collapsed = Static(f"{card.task_id}: {first_line}", classes="collapsed-card")
                container.mount(collapsed)

        if not self.agent_cards:
            container.mount(Static("[dim]No agent sessions found[/dim]"))

        self.mount(container, before=self.query_one("#footer"))

    def _render_filtered_view(self) -> None:
        """Render filtered view with tabs for attention/active/idle/all."""
        container = Vertical(id="filtered-container")

        # Categorize cards
        waiting_cards = self._get_waiting_cards()
        active_cards = [c for c in self.agent_cards if c not in waiting_cards and c.health == "active"]
        idle_cards = [c for c in self.agent_cards if c not in waiting_cards and c.health != "active"]

        # Create tab bar
        tab_bar = Horizontal(classes="tab-bar")

        # Format tabs with selection indicator
        attention_tab = f"[>Attention: {len(waiting_cards)}]" if self.current_filter == "attention" else f"[ Attention: {len(waiting_cards)}]"
        active_tab = f"[>Active: {len(active_cards)}]" if self.current_filter == "active" else f"[ Active: {len(active_cards)}]"
        idle_tab = f"[>Idle: {len(idle_cards)}]" if self.current_filter == "idle" else f"[ Idle: {len(idle_cards)}]"
        all_tab = f"[>All: {len(self.agent_cards)}]" if self.current_filter == "all" else f"[ All: {len(self.agent_cards)}]"

        tab_bar.mount(Static(f"{attention_tab} {active_tab} {idle_tab} {all_tab}"))
        container.mount(tab_bar)

        # Show cards based on current filter
        scroll_area = ScrollableContainer()

        if self.current_filter == "attention":
            cards_to_show = waiting_cards
        elif self.current_filter == "active":
            cards_to_show = active_cards
        elif self.current_filter == "idle":
            cards_to_show = idle_cards
        else:  # "all"
            cards_to_show = self.agent_cards

        if cards_to_show:
            for card in cards_to_show:
                scroll_area.mount(card)
        else:
            scroll_area.mount(Static(f"[dim]No {self.current_filter} agents[/dim]"))

        container.mount(scroll_area)
        self.mount(container, before=self.query_one("#footer"))

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

    def action_approve_no(self) -> None:
        """Send no/2 to focused agent."""
        self._send_to_focused(2)

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

    # View mode actions (stubs for future implementation)
    def action_grid_view(self) -> None:
        """Switch to grid view."""
        self.view_mode = "grid"
        self.notify("Grid view")

    def action_stack_view(self) -> None:
        """Switch to stack (priority) view."""
        self.view_mode = "stack"
        self.notify("Stack view")

    def action_filtered_view(self) -> None:
        """Switch to filtered tabs view."""
        self.view_mode = "filtered"
        self.notify("Filtered view")

    def action_filter_attention(self) -> None:
        """Filter to show only attention cards."""
        self.current_filter = "attention"
        if self.view_mode == "filtered":
            self._render_current_view()

    def action_filter_active(self) -> None:
        """Filter to show only active cards."""
        self.current_filter = "active"
        if self.view_mode == "filtered":
            self._render_current_view()

    def action_filter_idle(self) -> None:
        """Filter to show only idle cards."""
        self.current_filter = "idle"
        if self.view_mode == "filtered":
            self._render_current_view()

    def action_filter_all(self) -> None:
        """Filter to show all cards."""
        self.current_filter = "all"
        if self.view_mode == "filtered":
            self._render_current_view()

    def action_show_help(self) -> None:
        """Show help overlay."""
        self.push_screen(WatchHelpModal())

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
        else:
            self.notify("No agent focused", severity="warning")
