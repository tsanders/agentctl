"""Textual TUI Dashboard for agentctl"""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer, Center
from textual.widgets import Header, Footer, Static, DataTable, Log, Button, Input, Label
from textual.reactive import reactive
from textual.screen import Screen, ModalScreen
from datetime import datetime
from typing import List, Dict

from agentctl.core import database


class AgentStatusWidget(Static):
    """Widget showing active agents with real-time updates"""

    def compose(self) -> ComposeResult:
        yield Static("🤖 ACTIVE AGENTS", classes="widget-title")
        yield DataTable(id="agents-table")

    def on_mount(self) -> None:
        table = self.query_one("#agents-table", DataTable)
        table.add_columns("Task ID", "Project", "Status", "Phase", "Elapsed", "Commits")
        table.cursor_type = "row"
        self.update_agents()
        self.set_interval(5, self.update_agents)

    def update_agents(self) -> None:
        """Update agent list"""
        agents = database.get_active_agents()

        table = self.query_one("#agents-table", DataTable)
        table.clear()

        for agent in agents:
            status_icon = {
                "running": "🟢",
                "blocked": "🟡",
                "failed": "🔴"
            }.get(agent['status'], "⚪")

            table.add_row(
                agent['task_id'],
                agent['project'],
                f"{status_icon} {agent['status'].upper()}",
                agent['phase'],
                agent['elapsed'],
                str(agent['commits'])
            )


class TaskQueueWidget(Static):
    """Widget showing queued tasks"""

    def compose(self) -> ComposeResult:
        yield Static("📋 TASK QUEUE", classes="widget-title")
        yield DataTable(id="queue-table")

    def on_mount(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        table.add_columns("#", "Task ID", "Priority", "Category")
        table.cursor_type = "row"
        self.update_queue()
        self.set_interval(10, self.update_queue)

    def update_queue(self) -> None:
        """Update task queue"""
        tasks = database.get_queued_tasks()

        table = self.query_one("#queue-table", DataTable)
        table.clear()

        for i, task in enumerate(tasks[:10], 1):
            priority_icon = {
                "high": "🔴",
                "medium": "🟡",
                "low": "🟢"
            }.get(task.get('priority', 'medium'), "⚪")

            table.add_row(
                str(i),
                task['id'],
                f"{priority_icon} {task.get('priority', 'medium').upper()}",
                task.get('category', 'UNKNOWN')
            )


class ActivityLogWidget(Static):
    """Widget showing recent activity"""

    def compose(self) -> ComposeResult:
        yield Static("📊 RECENT ACTIVITY", classes="widget-title")
        yield ScrollableContainer(Log(id="activity-log", auto_scroll=True))

    def on_mount(self) -> None:
        self.update_activity()
        self.set_interval(3, self.update_activity)

    def update_activity(self) -> None:
        """Update activity log"""
        events = database.get_recent_events(limit=15)

        log_widget = self.query_one("#activity-log", Log)
        log_widget.clear()

        for event in reversed(events):
            timestamp = event['timestamp'].strftime("%H:%M:%S")
            icon = {
                "task_started": "▶️",
                "task_completed": "✅",
                "task_paused": "⏸️",
                "task_resumed": "▶️",
                "commit": "💾",
                "phase_change": "➡️",
            }.get(event['type'], "•")

            log_widget.write_line(f"{timestamp}  {event['task_id']}  {icon} {event['type']}")


class ProjectStatsWidget(Static):
    """Widget showing project statistics"""

    def compose(self) -> ComposeResult:
        yield Static("📈 PROJECT STATS", classes="widget-title")
        yield Static(id="stats-content", classes="stats-content")

    def on_mount(self) -> None:
        self.update_stats()
        self.set_interval(30, self.update_stats)

    def update_stats(self) -> None:
        """Update project statistics"""
        projects = database.list_projects()
        agents = database.get_active_agents()
        queued = database.get_queued_tasks()

        stats_text = f"""
[bold]Projects:[/bold] {len(projects)}
[bold]Active Agents:[/bold] {len(agents)}
[bold]Queued Tasks:[/bold] {len(queued)}

[bold cyan]Running:[/bold cyan] {len([a for a in agents if a['status'] == 'running'])}
[bold yellow]Blocked:[/bold yellow] {len([a for a in agents if a['status'] == 'blocked'])}
"""

        content = self.query_one("#stats-content", Static)
        content.update(stats_text)


class CreateProjectModal(ModalScreen):
    """Modal for creating a new project"""

    def compose(self) -> ComposeResult:
        yield Container(
            Label("Create New Project", id="modal-title"),
            Input(placeholder="Project ID (e.g., RRA)", id="project-id"),
            Input(placeholder="Project Name", id="project-name"),
            Input(placeholder="Description (optional)", id="project-desc"),
            Horizontal(
                Button("Create", variant="primary", id="create-btn"),
                Button("Cancel", variant="default", id="cancel-btn"),
                classes="button-row"
            ),
            id="create-project-modal"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "create-btn":
            project_id = self.query_one("#project-id", Input).value
            project_name = self.query_one("#project-name", Input).value
            project_desc = self.query_one("#project-desc", Input).value

            if not project_id or not project_name:
                self.app.notify("Project ID and Name are required", severity="error")
                return

            try:
                database.create_project(
                    project_id=project_id.strip(),
                    name=project_name.strip(),
                    description=project_desc.strip() if project_desc else None
                )
                self.dismiss(project_id)
                self.app.notify(f"Project {project_id} created!", severity="success")
            except Exception as e:
                self.app.notify(f"Error creating project: {e}", severity="error")


class EditProjectModal(ModalScreen):
    """Modal for editing an existing project"""

    def __init__(self, project_id: str):
        super().__init__()
        self.project_id = project_id
        self.project_data = database.get_project(project_id)

    def compose(self) -> ComposeResult:
        yield Container(
            Label(f"Edit Project: {self.project_id}", id="modal-title"),
            Input(placeholder="Project Name", id="project-name", value=self.project_data['name']),
            Input(placeholder="Description (optional)", id="project-desc",
                  value=self.project_data.get('description') or ""),
            Input(placeholder="Default Repository ID (optional)", id="default-repo-id",
                  value=self.project_data.get('default_repository_id') or ""),
            Horizontal(
                Button("Save", variant="primary", id="save-btn"),
                Button("Cancel", variant="default", id="cancel-btn"),
                classes="button-row"
            ),
            id="edit-project-modal"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            project_name = self.query_one("#project-name", Input).value
            project_desc = self.query_one("#project-desc", Input).value
            default_repo = self.query_one("#default-repo-id", Input).value

            if not project_name:
                self.app.notify("Project Name is required", severity="error")
                return

            try:
                database.update_project(
                    project_id=self.project_id,
                    name=project_name.strip(),
                    description=project_desc.strip() if project_desc else None,
                    default_repository_id=default_repo.strip() if default_repo else None
                )
                self.dismiss(self.project_id)
                self.app.notify(f"Project {self.project_id} updated!", severity="success")
            except Exception as e:
                self.app.notify(f"Error updating project: {e}", severity="error")


class CreateRepositoryModal(ModalScreen):
    """Modal for creating a new repository"""

    def __init__(self, project_id: str):
        super().__init__()
        self.project_id = project_id

    def compose(self) -> ComposeResult:
        yield Container(
            Label(f"Add Repository to Project: {self.project_id}", id="modal-title"),
            Input(placeholder="Repository ID (e.g., RRA-API)", id="repo-id"),
            Input(placeholder="Repository Name", id="repo-name"),
            Input(placeholder="Path to repository", id="repo-path"),
            Input(placeholder="Default branch (default: main)", id="repo-branch", value="main"),
            Horizontal(
                Button("Create", variant="primary", id="create-btn"),
                Button("Cancel", variant="default", id="cancel-btn"),
                classes="button-row"
            ),
            id="create-repo-modal"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "create-btn":
            from pathlib import Path

            repo_id = self.query_one("#repo-id", Input).value
            repo_name = self.query_one("#repo-name", Input).value
            repo_path = self.query_one("#repo-path", Input).value
            repo_branch = self.query_one("#repo-branch", Input).value

            if not repo_id or not repo_name or not repo_path:
                self.app.notify("All fields except branch are required", severity="error")
                return

            # Validate path exists
            path = Path(repo_path).expanduser().resolve()
            if not path.exists():
                self.app.notify(f"Path does not exist: {path}", severity="error")
                return

            try:
                database.create_repository(
                    repository_id=repo_id.strip(),
                    project_id=self.project_id,
                    name=repo_name.strip(),
                    path=str(path),
                    default_branch=repo_branch.strip() or "main"
                )
                self.dismiss(repo_id)
                self.app.notify(f"Repository {repo_id} created!", severity="success")
            except Exception as e:
                self.app.notify(f"Error creating repository: {e}", severity="error")


class EditRepositoryModal(ModalScreen):
    """Modal for editing an existing repository"""

    def __init__(self, repository_id: str):
        super().__init__()
        self.repository_id = repository_id
        self.repo_data = database.get_repository(repository_id)

    def compose(self) -> ComposeResult:
        yield Container(
            Label(f"Edit Repository: {self.repository_id}", id="modal-title"),
            Input(placeholder="Repository Name", id="repo-name", value=self.repo_data['name']),
            Input(placeholder="Path to repository", id="repo-path", value=self.repo_data['path']),
            Input(placeholder="Default branch", id="repo-branch",
                  value=self.repo_data.get('default_branch') or "main"),
            Horizontal(
                Button("Save", variant="primary", id="save-btn"),
                Button("Cancel", variant="default", id="cancel-btn"),
                classes="button-row"
            ),
            id="edit-repo-modal"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            from pathlib import Path

            repo_name = self.query_one("#repo-name", Input).value
            repo_path = self.query_one("#repo-path", Input).value
            repo_branch = self.query_one("#repo-branch", Input).value

            if not repo_name or not repo_path:
                self.app.notify("Name and Path are required", severity="error")
                return

            # Validate path exists
            path = Path(repo_path).expanduser().resolve()
            if not path.exists():
                self.app.notify(f"Path does not exist: {path}", severity="error")
                return

            try:
                database.update_repository(
                    repository_id=self.repository_id,
                    name=repo_name.strip(),
                    path=str(path),
                    default_branch=repo_branch.strip() or "main"
                )
                self.dismiss(self.repository_id)
                self.app.notify(f"Repository {self.repository_id} updated!", severity="success")
            except Exception as e:
                self.app.notify(f"Error updating repository: {e}", severity="error")


class ProjectDetailScreen(Screen):
    """Screen showing project details with repositories and tasks"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("r", "add_repo", "Add Repo"),
        ("e", "edit_repo", "Edit Repo"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, project_id: str):
        super().__init__()
        self.project_id = project_id

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static(f"📦 Project: {self.project_id}", classes="screen-title"),
            Container(
                Static("📁 REPOSITORIES", classes="widget-title"),
                DataTable(id="repos-table"),
                id="repos-section"
            ),
            Container(
                Static("📋 TASKS", classes="widget-title"),
                DataTable(id="tasks-table"),
                id="tasks-section"
            ),
            id="project-detail-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        self.load_repositories()
        self.load_tasks()

    def load_repositories(self) -> None:
        """Load and display repositories for this project"""
        repos = database.list_repositories(project_id=self.project_id)

        table = self.query_one("#repos-table", DataTable)
        table.clear()
        table.add_columns("Repository ID", "Name", "Path", "Default Branch")
        table.cursor_type = "row"

        for repo in repos:
            table.add_row(
                repo['id'],
                repo['name'],
                repo['path'],
                repo.get('default_branch', 'main')
            )

    def load_tasks(self) -> None:
        """Load and display tasks for this project"""
        tasks = database.query_tasks(project=self.project_id)

        table = self.query_one("#tasks-table", DataTable)
        table.clear()
        table.add_columns("Task ID", "Title", "Status", "Priority")
        table.cursor_type = "row"

        for task in tasks:
            table.add_row(
                task['task_id'],
                task.get('title', '-')[:40],
                task['status'],
                task.get('priority', 'medium').upper()
            )

    def action_go_back(self) -> None:
        """Go back to project list"""
        self.app.pop_screen()

    def action_add_repo(self) -> None:
        """Show modal to add a repository"""
        def check_result(result):
            if result:
                self.load_repositories()

        self.app.push_screen(CreateRepositoryModal(self.project_id), check_result)

    def action_edit_repo(self) -> None:
        """Show modal to edit selected repository"""
        repos_table = self.query_one("#repos-table", DataTable)

        # Check if repos table has focus and a selected row
        if repos_table.has_focus and repos_table.row_count > 0 and repos_table.cursor_row is not None:
            row = repos_table.get_row_at(repos_table.cursor_row)
            repository_id = str(row[0])

            def check_result(result):
                if result:
                    self.load_repositories()

            self.app.push_screen(EditRepositoryModal(repository_id), check_result)
        else:
            self.app.notify("Select a repository to edit", severity="warning")


class ProjectListScreen(Screen):
    """Screen showing all projects"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("n", "new_project", "New Project"),
        ("e", "edit_project", "Edit Project"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static("📦 PROJECT MANAGEMENT", classes="screen-title"),
            DataTable(id="projects-table"),
            id="projects-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        self.load_projects()

    def load_projects(self) -> None:
        """Load and display all projects"""
        projects = database.list_projects()

        table = self.query_one("#projects-table", DataTable)
        table.clear()
        table.add_columns("Project ID", "Name", "Description", "Created")
        table.cursor_type = "row"

        for project in projects:
            created = datetime.fromtimestamp(project['created_at']).strftime("%Y-%m-%d")
            table.add_row(
                project['id'],
                project['name'],
                project.get('description') or '-',
                created
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in projects table"""
        if event.data_table.id == "projects-table":
            row = event.data_table.get_row_at(event.cursor_row)
            project_id = str(row[0])
            self.app.push_screen(ProjectDetailScreen(project_id))

    def action_go_back(self) -> None:
        """Go back to main dashboard"""
        self.app.pop_screen()

    def action_new_project(self) -> None:
        """Show modal to create a new project"""
        def check_result(result):
            if result:
                self.load_projects()

        self.app.push_screen(CreateProjectModal(), check_result)

    def action_edit_project(self) -> None:
        """Show modal to edit selected project"""
        table = self.query_one("#projects-table", DataTable)
        if table.row_count > 0 and table.cursor_row is not None:
            row = table.get_row_at(table.cursor_row)
            project_id = str(row[0])

            def check_result(result):
                if result:
                    self.load_projects()

            self.app.push_screen(EditProjectModal(project_id), check_result)

    def action_select_project(self) -> None:
        """Open selected project details"""
        table = self.query_one("#projects-table", DataTable)
        if table.row_count > 0 and table.cursor_row is not None:
            row = table.get_row_at(table.cursor_row)
            project_id = str(row[0])
            self.app.push_screen(ProjectDetailScreen(project_id))


class AgentDashboard(App):
    """Main TUI dashboard application for agentctl"""

    CSS = """
    Screen {
        background: $surface;
    }

    .widget-title {
        background: $boost;
        color: $text;
        padding: 1;
        text-align: center;
        text-style: bold;
    }

    #main-container {
        layout: grid;
        grid-size: 2 3;
        grid-rows: 2fr 1fr 1fr;
        height: 100%;
    }

    #agents-widget {
        column-span: 2;
        border: solid $accent;
        height: 100%;
    }

    #queue-widget {
        border: solid $accent;
        height: 100%;
    }

    #activity-widget {
        border: solid $accent;
        height: 100%;
    }

    #stats-widget {
        column-span: 2;
        border: solid $accent;
        height: 100%;
    }

    DataTable {
        height: 1fr;
    }

    .stats-content {
        padding: 1 2;
    }

    #activity-log {
        height: 1fr;
    }

    /* Modal styles */
    #create-project-modal, #create-repo-modal, #edit-project-modal, #edit-repo-modal {
        align: center middle;
        width: 60;
        height: auto;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }

    #modal-title {
        text-align: center;
        text-style: bold;
        padding: 1;
        color: $accent;
    }

    Input {
        margin: 1 0;
    }

    .button-row {
        align: center middle;
        margin-top: 1;
    }

    Button {
        margin: 0 1;
    }

    /* Screen styles */
    .screen-title {
        text-align: center;
        text-style: bold;
        padding: 1;
        background: $boost;
        color: $text;
    }

    #projects-container, #project-detail-container {
        height: 100%;
    }

    #projects-table {
        height: 1fr;
    }

    #repos-section, #tasks-section {
        border: solid $accent;
        margin: 1;
        height: 1fr;
    }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("q", "quit", "Quit"),
        ("s", "status", "Status"),
        ("p", "manage_projects", "Projects"),
    ]

    def compose(self) -> ComposeResult:
        """Create child widgets for the app"""
        yield Header(show_clock=True)
        yield Container(
            AgentStatusWidget(id="agents-widget"),
            TaskQueueWidget(id="queue-widget"),
            ActivityLogWidget(id="activity-widget"),
            ProjectStatsWidget(id="stats-widget"),
            id="main-container"
        )
        yield Footer()

    def action_refresh(self) -> None:
        """Refresh all widgets"""
        self.query_one("#agents-widget", AgentStatusWidget).update_agents()
        self.query_one("#queue-widget", TaskQueueWidget).update_queue()
        self.query_one("#activity-widget", ActivityLogWidget).update_activity()
        self.query_one("#stats-widget", ProjectStatsWidget).update_stats()
        self.notify("Dashboard refreshed", severity="information")

    def action_status(self) -> None:
        """Show status notification"""
        agents = database.get_active_agents()
        queued = database.get_queued_tasks()
        self.notify(f"Active: {len(agents)} | Queued: {len(queued)}", title="Status")

    def action_manage_projects(self) -> None:
        """Open projects management screen"""
        self.push_screen(ProjectListScreen())


def run_dashboard():
    """Run the dashboard application"""
    app = AgentDashboard()
    app.run()
