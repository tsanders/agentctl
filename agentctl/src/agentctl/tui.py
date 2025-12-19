"""Textual TUI Dashboard for agentctl"""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer, Center
from textual.widgets import Header, Footer, Static, DataTable, Log, Button, Input, Label, Select, Rule, Collapsible
from textual.reactive import reactive
from textual.screen import Screen, ModalScreen
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path

from agentctl.core import database, task_md
from agentctl.core import task_store
from agentctl.core import prompt_store
from agentctl.core.task import create_task, update_task, delete_task, copy_task_file_to_workdir
from agentctl.core.tmux import send_keys as tmux_send_keys
from agentctl.core.agent_monitor import (
    get_agent_status, get_all_agent_statuses, get_all_window_statuses,
    get_health_display, HEALTH_ICONS, check_and_notify_state_changes, save_session_log
)


class AgentStatusWidget(Static):
    """Widget showing active agents with real-time updates"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._row_keys: dict[str, any] = {}  # task_id -> row_key mapping

    def compose(self) -> ComposeResult:
        yield Static("🤖 ACTIVE AGENTS", classes="widget-title")
        yield DataTable(id="agents-table")

    def on_mount(self) -> None:
        table = self.query_one("#agents-table", DataTable)
        table.add_columns("Task ID", "Health", "Phase", "Status", "Elapsed", "Project")
        table.cursor_type = "row"
        self.update_agents()
        self.set_interval(3, self.update_agents)

    def _truncate(self, text: str, max_len: int) -> str:
        """Truncate text with ellipsis if too long"""
        if not text:
            return "-"
        if len(text) > max_len:
            return text[:max_len - 1] + "…"
        return text

    def _build_row(self, agent: dict, from_tmux: bool = True) -> tuple:
        """Build a row tuple from agent data"""
        if from_tmux:
            # Use pre-computed window_statuses if available (set in update_agents)
            window_statuses = agent.get('_window_statuses', [])
            if len(window_statuses) > 1:
                # Multi-window: show inline icons "🟢 Claude 🟡 Codex"
                health_display = " ".join(
                    f"{w['icon']} {w['name']}" for w in window_statuses
                )
            elif window_statuses:
                # Single window: show traditional format
                w = window_statuses[0]
                health_display = f"{w['icon']} {w['summary'][:20]}"
            else:
                health = agent.get('health', 'unknown')
                health_icon = HEALTH_ICONS.get(health, "⚪")
                health_display = f"{health_icon} {health.upper()}"
            task_status = agent.get('task_agent_status', 'unknown')
            project = agent.get('project', '')
        else:
            health_display = "⚪ NO SESSION"
            task_status = agent.get('agent_status', 'unknown')
            project = agent.get('project_name', '')

        status_icon = {
            "running": "🟢",
            "blocked": "🟡",
            "failed": "🔴",
            "paused": "⏸️"
        }.get(task_status, "⚪")

        return (
            agent['task_id'],
            health_display,
            self._truncate(agent.get('phase', ''), 15),
            f"{status_icon} {task_status.upper()}",
            agent.get('elapsed', '-'),
            self._truncate(project, 20),
        )

    def update_agents(self) -> None:
        """Update agent list with real-time health from tmux monitoring"""
        agent_statuses = get_all_agent_statuses()
        table = self.query_one("#agents-table", DataTable)

        # Build list of agents to display
        agents_to_show = []
        if agent_statuses:
            for agent in agent_statuses:
                # Pre-compute window statuses once per agent (avoid repeated tmux queries)
                tmux_session = agent.get('tmux_session')
                if tmux_session:
                    agent['_window_statuses'] = get_all_window_statuses(tmux_session, agent.get('task_id'))
                agents_to_show.append((agent['task_id'], self._build_row(agent, from_tmux=True)))
        else:
            # Fall back to task_store for tasks without active tmux sessions
            agents = task_store.get_active_agents()
            for agent in agents:
                agents_to_show.append((agent['task_id'], self._build_row(agent, from_tmux=False)))

        # Track which task_ids we've seen
        current_task_ids = set()

        for task_id, row_data in agents_to_show:
            current_task_ids.add(task_id)

            # Check if row exists in table (by checking row_locations directly)
            from textual.widgets._data_table import RowKey
            row_key = RowKey(task_id)
            row_exists = row_key in table._row_locations

            if row_exists:
                # Update existing row cell by cell
                try:
                    for col_idx, value in enumerate(row_data):
                        table.update_cell(row_key, table.columns[col_idx].key, value)
                    self._row_keys[task_id] = row_key
                except Exception:
                    pass
            else:
                # Add new row
                try:
                    new_key = table.add_row(*row_data, key=task_id)
                    self._row_keys[task_id] = new_key
                except Exception:
                    pass

        # Remove rows for agents that are no longer active
        for task_id in list(self._row_keys.keys()):
            if task_id not in current_task_ids:
                try:
                    table.remove_row(self._row_keys[task_id])
                except Exception:
                    pass
                del self._row_keys[task_id]


class TaskQueueWidget(Static):
    """Widget showing queued tasks"""

    def compose(self) -> ComposeResult:
        yield Static("📋 TASK QUEUE", classes="widget-title")
        yield DataTable(id="queue-table")

    def on_mount(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        table.add_columns("#", "Task ID", "Title", "Project", "Priority", "Category", "Type")
        table.cursor_type = "row"
        self.update_queue()
        self.set_interval(10, self.update_queue)

    def _truncate(self, text: str, max_len: int) -> str:
        """Truncate text with ellipsis if too long"""
        if not text:
            return "-"
        if len(text) > max_len:
            return text[:max_len - 1] + "…"
        return text

    def update_queue(self) -> None:
        """Update task queue"""
        tasks = task_store.get_queued_tasks()

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
                self._truncate(task.get('title', ''), 30),
                self._truncate(task.get('project_name', ''), 15),
                f"{priority_icon} {task.get('priority', 'medium').upper()}",
                task.get('category', 'UNKNOWN'),
                task.get('type', '-')
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
        agents = task_store.get_active_agents()
        queued = task_store.get_queued_tasks()

        stats_text = f"""
[bold]Projects:[/bold] {len(projects)}
[bold]Active Agents:[/bold] {len(agents)}
[bold]Queued Tasks:[/bold] {len(queued)}

[bold cyan]Running:[/bold cyan] {len([a for a in agents if a['agent_status'] == 'running'])}
[bold yellow]Blocked:[/bold yellow] {len([a for a in agents if a['agent_status'] == 'blocked'])}
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
            Input(placeholder="Tasks Path (optional, for markdown tasks)", id="project-tasks-path"),
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
            tasks_path = self.query_one("#project-tasks-path", Input).value

            if not project_id or not project_name:
                self.app.notify("Project ID and Name are required", severity="error")
                return

            # Validate and create tasks_path if provided
            final_tasks_path = None
            if tasks_path and tasks_path.strip():
                path = Path(tasks_path.strip()).expanduser().resolve()
                if not path.exists():
                    try:
                        path.mkdir(parents=True, exist_ok=True)
                        self.app.notify(f"Created tasks directory: {path}", severity="information")
                    except Exception as e:
                        self.app.notify(f"Failed to create directory: {e}", severity="error")
                        return
                final_tasks_path = str(path)

            try:
                database.create_project(
                    project_id=project_id.strip(),
                    name=project_name.strip(),
                    description=project_desc.strip() if project_desc else None,
                    tasks_path=final_tasks_path
                )
                self.dismiss(project_id)
                msg = f"Project {project_id} created"
                if final_tasks_path:
                    msg += f" with markdown tasks at {final_tasks_path}"
                self.app.notify(msg, severity="success")
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
            Input(placeholder="Tasks Path (optional, for markdown tasks)", id="project-tasks-path",
                  value=self.project_data.get('tasks_path') or ""),
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
            tasks_path = self.query_one("#project-tasks-path", Input).value

            if not project_name:
                self.app.notify("Project Name is required", severity="error")
                return

            # Validate and create tasks_path if provided
            final_tasks_path = None
            if tasks_path and tasks_path.strip():
                path = Path(tasks_path.strip()).expanduser().resolve()
                if not path.exists():
                    try:
                        path.mkdir(parents=True, exist_ok=True)
                        self.app.notify(f"Created tasks directory: {path}", severity="information")
                    except Exception as e:
                        self.app.notify(f"Failed to create directory: {e}", severity="error")
                        return
                final_tasks_path = str(path)

            try:
                database.update_project(
                    project_id=self.project_id,
                    name=project_name.strip(),
                    description=project_desc.strip() if project_desc else None,
                    default_repository_id=default_repo.strip() if default_repo else None,
                    tasks_path=final_tasks_path
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


class CreateTaskModal(ModalScreen):
    """Modal for creating a new task"""

    def __init__(self, project_id: Optional[str] = None, repository_id: Optional[str] = None):
        super().__init__()
        self.project_id = project_id
        self.repository_id = repository_id

    def compose(self) -> ComposeResult:
        # Get projects for dropdown (label, value) format
        projects = database.list_projects()
        project_options = [(p['name'], p['id']) for p in projects]

        # Get repositories for dropdown (label, value) format
        repositories = database.list_repositories()
        repo_options = [(r['name'], r['id']) for r in repositories]

        yield Container(
            Label("Create New Task", id="modal-title"),
            Input(placeholder="Task ID (optional, e.g., RRA-API-0042)", id="task-id"),
            Input(placeholder="Title", id="task-title"),
            Input(placeholder="Description (optional)", id="task-desc"),
            Select(
                options=project_options,
                prompt="Select Project",
                id="task-project",
                value=self.project_id if self.project_id else Select.BLANK
            ),
            Select(
                options=repo_options,
                prompt="Select Repository (optional)",
                id="task-repo",
                allow_blank=True,
                value=self.repository_id if self.repository_id else Select.BLANK
            ),
            Select(
                options=[
                    ("Feature", "FEATURE"),
                    ("Bug", "BUG"),
                    ("Refactor", "REFACTOR"),
                    ("Documentation", "DOCS"),
                    ("Test", "TEST"),
                    ("Chore", "CHORE")
                ],
                prompt="Category",
                id="task-category",
                value="FEATURE"
            ),
            Input(placeholder="Type (e.g., feature, bugfix)", id="task-type", value="feature"),
            Select(
                options=[
                    ("High", "high"),
                    ("Medium", "medium"),
                    ("Low", "low")
                ],
                prompt="Priority",
                id="task-priority",
                value="medium"
            ),
            Horizontal(
                Button("Create", variant="primary", id="create-btn"),
                Button("Cancel", variant="default", id="cancel-btn"),
                classes="button-row"
            ),
            id="create-task-modal"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "create-btn":
            task_id = self.query_one("#task-id", Input).value
            title = self.query_one("#task-title", Input).value
            description = self.query_one("#task-desc", Input).value
            project_id = self.query_one("#task-project", Select).value
            repo_id = self.query_one("#task-repo", Select).value
            category = self.query_one("#task-category", Select).value
            task_type = self.query_one("#task-type", Input).value
            priority = self.query_one("#task-priority", Select).value

            if not title or not project_id:
                self.app.notify("Title and Project are required", severity="error")
                return

            try:
                # Handle blank repository selection
                final_repo_id = None
                if repo_id and repo_id != Select.BLANK:
                    final_repo_id = repo_id

                # Check if project uses markdown tasks
                project = database.get_project(project_id)
                if project and project.get('tasks_path'):
                    # Markdown tasks: task_id is optional (auto-generated if not provided)
                    pass
                elif not task_id:
                    # Database tasks: task_id is required
                    self.app.notify("Task ID is required for database tasks", severity="error")
                    return

                if project and project.get('tasks_path'):
                    # Create markdown task with user-provided task_id
                    actual_task_id = create_task(
                        project_id=project_id,
                        category=category,
                        title=title.strip(),
                        description=description.strip() if description else None,
                        repository_id=final_repo_id,
                        task_type=task_type.strip() or "feature",
                        priority=priority,
                        task_id=task_id.strip() if task_id else None
                    )
                    if actual_task_id:
                        self.dismiss(actual_task_id)
                        self.app.notify(f"Markdown task {actual_task_id} created!", severity="success")
                    else:
                        self.app.notify("Failed to create markdown task", severity="error")
                else:
                    # Create database task
                    database.create_task(
                        task_id=task_id.strip(),
                        project_id=project_id,
                        category=category,
                        task_type=task_type.strip() or "feature",
                        title=title.strip(),
                        description=description.strip() if description else None,
                        priority=priority,
                        repository_id=final_repo_id
                    )
                    self.dismiss(task_id)
                    self.app.notify(f"Task {task_id} created!", severity="success")
            except Exception as e:
                self.app.notify(f"Error creating task: {e}", severity="error")


class EditTaskModal(ModalScreen):
    """Modal for editing an existing task"""

    def __init__(self, task_id: str):
        super().__init__()
        self.task_id = task_id
        self.task_data = task_store.get_task_with_details(task_id)

    def compose(self) -> ComposeResult:
        if not self.task_data:
            yield Container(
                Label("Task not found", id="modal-title"),
                Button("Close", id="cancel-btn", variant="error"),
                id="edit-task-modal"
            )
            return

        # Get projects and repositories for dropdowns (label, value) format
        projects = database.list_projects()
        project_options = [(p['name'], p['id']) for p in projects]

        repositories = database.list_repositories()
        repo_options = [(r['name'], r['id']) for r in repositories]

        yield Container(
            Label(f"Edit Task: {self.task_id}", id="modal-title"),
            Input(
                placeholder="Title",
                id="task-title",
                value=self.task_data['title']
            ),
            Input(
                placeholder="Description (optional)",
                id="task-desc",
                value=self.task_data.get('description') or ""
            ),
            Select(
                options=project_options,
                prompt="Select Project",
                id="task-project",
                value=self.task_data['project_id']
            ),
            Select(
                options=repo_options,
                prompt="Select Repository (optional)",
                id="task-repo",
                allow_blank=True,
                value=self.task_data.get('repository_id') if self.task_data.get('repository_id') else Select.BLANK
            ),
            Select(
                options=[
                    ("Feature", "FEATURE"),
                    ("Bug", "BUG"),
                    ("Refactor", "REFACTOR"),
                    ("Documentation", "DOCS"),
                    ("Test", "TEST"),
                    ("Chore", "CHORE")
                ],
                prompt="Category",
                id="task-category",
                value=self.task_data['category']
            ),
            Input(
                placeholder="Type (e.g., feature, bugfix)",
                id="task-type",
                value=self.task_data['type']
            ),
            Select(
                options=[
                    ("High", "high"),
                    ("Medium", "medium"),
                    ("Low", "low")
                ],
                prompt="Priority",
                id="task-priority",
                value=self.task_data['priority']
            ),
            Select(
                options=[
                    ("Queued", "queued"),
                    ("Running", "running"),
                    ("Blocked", "blocked"),
                    ("Completed", "completed"),
                    ("Failed", "failed")
                ],
                prompt="Agent Status",
                id="task-agent-status",
                value=self.task_data['agent_status']
            ),
            Container(
                Button("Save", id="save-btn", variant="success"),
                Button("Cancel", id="cancel-btn", variant="error"),
                classes="button-row"
            ),
            id="edit-task-modal"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            if not self.task_data:
                self.dismiss(None)
                return

            title = self.query_one("#task-title", Input).value
            description = self.query_one("#task-desc", Input).value
            project_id = self.query_one("#task-project", Select).value
            repo_id = self.query_one("#task-repo", Select).value
            category = self.query_one("#task-category", Select).value
            task_type = self.query_one("#task-type", Input).value
            priority = self.query_one("#task-priority", Select).value
            agent_status = self.query_one("#task-agent-status", Select).value

            if not title or not project_id:
                self.app.notify("Title and Project are required", severity="error")
                return

            try:
                # Handle blank repository selection
                final_repo_id = None
                if repo_id and repo_id != Select.BLANK:
                    final_repo_id = repo_id

                # Update task in markdown file
                updates = {
                    'title': title.strip(),
                    'description': description.strip() if description else None,
                    'project_id': project_id,
                    'repository_id': final_repo_id,
                    'category': category,
                    'type': task_type.strip(),
                    'priority': priority,
                    'agent_status': agent_status
                }
                success = update_task(self.task_id, updates)
                if not success:
                    self.app.notify("Failed to update task", severity="error")
                    return

                database.add_event(self.task_id, "updated")
                self.dismiss(self.task_id)
                self.app.notify(f"Task {self.task_id} updated!", severity="success")
            except Exception as e:
                self.app.notify(f"Error updating task: {e}", severity="error")


class StartTaskModal(ModalScreen):
    """Modal for starting a task with optional worktree creation"""

    def __init__(self, task_id: str):
        super().__init__()
        self.task_id = task_id
        self.task_data = task_store.get_task_with_details(task_id)
        self.create_worktree = False

    def compose(self) -> ComposeResult:
        if not self.task_data:
            yield Container(
                Label("Task not found", id="modal-title"),
                Button("Close", id="cancel-btn", variant="error"),
                id="start-task-modal"
            )
            return

        # Check if task has a repository
        if not self.task_data.get('repository_id'):
            tmux_session_name = f"agent-{self.task_id}"
            yield Container(
                Label(f"Start Task: {self.task_id}", id="modal-title"),
                Static("❌ No repository - cannot create worktree", classes="detail-row"),
                Static(f"🖥️ tmux: {tmux_session_name}", classes="detail-row"),
                Container(
                    Button("Start Anyway", id="start-btn", variant="success"),
                    Button("Cancel", id="cancel-btn", variant="error"),
                    classes="button-row"
                ),
                id="start-task-modal"
            )
            return

        from pathlib import Path
        from agentctl.core.worktree import get_worktree_path, get_branch_name

        # Calculate worktree path and branch name
        repo_path = Path(self.task_data['repository_path']).expanduser()
        worktree_path = get_worktree_path(repo_path, self.task_id)
        branch_name = get_branch_name(self.task_data['category'], self.task_id)

        tmux_session_name = f"agent-{self.task_id}"

        yield Container(
            Label(f"Start Task: {self.task_id}", id="modal-title"),
            Static(f"Title: {self.task_data['title'][:40]}", classes="detail-row"),
            Static(f"Repo: {self.task_data['repository_name']}", classes="detail-row"),
            Static(f"Branch: {branch_name}", classes="detail-row"),
            Static(f"Worktree: {worktree_path}", classes="detail-row"),
            Static(f"tmux: {tmux_session_name}", classes="detail-row"),
            Select(
                options=[
                    ("Yes - Create worktree", True),
                    ("No - Status only", False)
                ],
                prompt="Create Worktree?",
                id="worktree-option",
                value=True
            ),
            Container(
                Button("Start", id="start-btn", variant="success"),
                Button("Cancel", id="cancel-btn", variant="error"),
                classes="button-row"
            ),
            id="start-task-modal"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "start-btn":
            if not self.task_data:
                self.dismiss(None)
                return

            from datetime import datetime
            from pathlib import Path

            # Get worktree option if repository exists
            create_worktree = False
            if self.task_data.get('repository_id'):
                try:
                    create_worktree = self.query_one("#worktree-option", Select).value
                except Exception:
                    pass

            try:
                from agentctl.core.tmux import create_session
                from datetime import datetime as dt

                # Update task status
                updates = {
                    'agent_status': 'running',
                    'started_at': dt.now().isoformat()
                }
                update_task(self.task_id, updates)

                # Determine working directory and session name
                tmux_session_name = f"agent-{self.task_id}"
                working_dir = None

                # Create worktree if requested
                if create_worktree and self.task_data.get('repository_path'):
                    from agentctl.core.worktree import create_worktree, get_worktree_path, get_branch_name

                    repo_path = Path(self.task_data['repository_path']).expanduser()
                    # Try both key names for compatibility (task_store uses 'default_branch', database uses 'repository_default_branch')
                    base_branch = self.task_data.get('default_branch') or self.task_data.get('repository_default_branch', 'main')

                    worktree_info = create_worktree(
                        repo_path,
                        self.task_id,
                        self.task_data['category'],
                        base_branch
                    )

                    # Use worktree path as working directory
                    working_dir = Path(worktree_info['worktree_path'])

                    # Update task with worktree and branch info
                    update_task(self.task_id, {
                        'git_branch': worktree_info['branch_name'],
                        'worktree_path': worktree_info['worktree_path']
                    })
                else:
                    # Use repository path or current directory
                    if self.task_data.get('repository_path'):
                        working_dir = Path(self.task_data['repository_path']).expanduser()
                    else:
                        working_dir = Path.cwd()

                # Create tmux session
                try:
                    tmux_session = create_session(tmux_session_name, working_dir)

                    # Update task with tmux session info
                    update_task(self.task_id, {'tmux_session': tmux_session})

                    # Copy task file to working directory
                    copy_task_file_to_workdir(self.task_id, working_dir)

                    success_msg = f"Task started"
                    if create_worktree:
                        success_msg += f" with worktree at {working_dir}"
                    success_msg += f"\nTmux session: {tmux_session}\nAttach: tmux attach -t {tmux_session}"

                    self.app.notify(success_msg, severity="success", timeout=8)
                except Exception as tmux_error:
                    self.app.notify(f"Warning: Failed to create tmux session: {tmux_error}", severity="warning")
                    # Continue even if tmux fails - still copy task file
                    copy_task_file_to_workdir(self.task_id, working_dir)
                    success_msg = f"Task started"
                    if create_worktree:
                        success_msg += f" with worktree at {working_dir}"
                    self.app.notify(success_msg, severity="success", timeout=5)

                database.add_event(self.task_id, "started")
                self.dismiss(self.task_id)

            except Exception as e:
                self.app.notify(f"Error starting task: {e}", severity="error")


class ConfirmDeleteModal(ModalScreen):
    """Modal for confirming task deletion"""

    def __init__(self, task_id: str, task_title: str):
        super().__init__()
        self.task_id = task_id
        self.task_title = task_title

    def compose(self) -> ComposeResult:
        yield Container(
            Label("⚠️ Confirm Delete", id="modal-title"),
            Static(f"Task: [bold]{self.task_id}[/bold]", classes="detail-row"),
            Static(f"Title: {self.task_title[:50]}", classes="detail-row"),
            Static("[red]This action cannot be undone![/red]", classes="detail-row"),
            Container(
                Button("Delete", id="delete-btn", variant="error"),
                Button("Cancel", id="cancel-btn", variant="primary"),
                classes="button-row"
            ),
            id="confirm-delete-modal"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(False)
        elif event.button.id == "delete-btn":
            self.dismiss(True)


class EditNotesModal(ModalScreen):
    """Modal for editing task notes"""

    def __init__(self, task_id: str, current_notes: str = ""):
        super().__init__()
        self.task_id = task_id
        self.current_notes = current_notes or ""

    def compose(self) -> ComposeResult:
        yield Container(
            Label(f"📝 Notes: {self.task_id}", id="modal-title"),
            Static("Quick notes about this task/agent:", classes="detail-row"),
            Input(value=self.current_notes, placeholder="e.g., waiting on API fix, needs PR review", id="notes-input"),
            Container(
                Button("Save", id="save-btn", variant="success"),
                Button("Clear", id="clear-btn", variant="warning"),
                Button("Cancel", id="cancel-btn", variant="primary"),
                classes="button-row"
            ),
            id="edit-notes-modal"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "clear-btn":
            # Return empty string to clear notes
            self.dismiss("")
        elif event.button.id == "save-btn":
            notes_input = self.query_one("#notes-input", Input)
            self.dismiss(notes_input.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input"""
        self.dismiss(event.value)


class SendPromptModal(ModalScreen):
    """Modal for sending a prompt to an agent's tmux session"""

    def __init__(self, task_id: str, tmux_session: str):
        super().__init__()
        self.task_id = task_id
        self.tmux_session = tmux_session

    def compose(self) -> ComposeResult:
        yield Container(
            Label(f"📤 Send Prompt: {self.task_id}", id="modal-title"),
            Static(f"[dim]Session: {self.tmux_session}[/dim]", classes="detail-row"),
            Input(placeholder="Enter prompt to send to agent...", id="prompt-input"),
            Container(
                Button("Send", id="send-btn", variant="success"),
                Button("Send (no Enter)", id="send-no-enter-btn", variant="warning"),
                Button("Cancel", id="cancel-btn", variant="primary"),
                classes="button-row"
            ),
            id="send-prompt-modal"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "send-btn":
            prompt = self.query_one("#prompt-input", Input).value
            if prompt:
                success = tmux_send_keys(self.tmux_session, prompt, enter=True)
                if success:
                    prompt_store.add_to_history(prompt, task_id=self.task_id)
                self.dismiss(("sent", success, prompt))
            else:
                self.app.notify("Please enter a prompt", severity="warning")
        elif event.button.id == "send-no-enter-btn":
            prompt = self.query_one("#prompt-input", Input).value
            if prompt:
                success = tmux_send_keys(self.tmux_session, prompt, enter=False)
                if success:
                    prompt_store.add_to_history(prompt, task_id=self.task_id)
                self.dismiss(("sent_no_enter", success, prompt))
            else:
                self.app.notify("Please enter a prompt", severity="warning")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input - send with Enter"""
        if event.value:
            success = tmux_send_keys(self.tmux_session, event.value, enter=True)
            if success:
                prompt_store.add_to_history(event.value, task_id=self.task_id)
            self.dismiss(("sent", success, event.value))


class HelpOverlay(ModalScreen):
    """Modal overlay showing all keybindings organized by category"""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("question_mark", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
    ]

    def __init__(self, screen_name: str = "General"):
        super().__init__()
        self.screen_name = screen_name

    def compose(self) -> ComposeResult:
        help_content = self._get_help_content()
        yield Container(
            Static(f"⌨️  AGENTCTL KEYBINDINGS - {self.screen_name.upper()}", id="help-title"),
            ScrollableContainer(
                Static(help_content, id="help-content", markup=True),
                id="help-scroll"
            ),
            Static("Press ? or esc to close", id="help-footer"),
            id="help-overlay"
        )

    def _get_help_content(self) -> str:
        """Generate help content based on current screen"""

        # Common keybindings for all screens
        common = """[bold cyan]NAVIGATION[/bold cyan]
  j / ↓      Move cursor down
  k / ↑      Move cursor up
  h / ←      Scroll/Move left
  l / →      Scroll/Move right
  enter      Select / View details
  esc        Go back / Close

[bold cyan]SYSTEM[/bold cyan]
  r          Refresh current view
  q          Quit application
  ?          Show this help
"""

        # Screen-specific keybindings
        screen_specific = {
            "Dashboard": """[bold cyan]QUICK ACCESS[/bold cyan]
  p          Manage projects
  t          Manage tasks
  a          View active agents (tasks with tmux sessions)
  u          Open prompt library
""",
            "TaskDetail": """[bold cyan]TASK ACTIONS[/bold cyan]
  s          Start task (create worktree/tmux)
  c          Complete task
  d          Delete task

[bold cyan]TASK PROPERTIES[/bold cyan]
  1          Send suggestion 1 / Cycle status
  2          Send suggestion 2 / Cycle priority
  3          Send suggestion 3 / Cycle category
  4          Advance to next phase
  5          Go to previous phase

[bold cyan]AGENT INTERACTION[/bold cyan]
  a          Attach to tmux session
  t          Toggle tmux output (10 ↔ 100 lines)
  g          Open session in Ghostty
  l          Save session log
  p          Send prompt to agent

[bold cyan]PROMPT BAR (when open)[/bold cyan]
  ↑/↓        Browse prompt history (bookmarks first)
  Ctrl+r     Open prompt library to select
  Enter      Send prompt
  Escape     Cancel

[bold cyan]EDITING[/bold cyan]
  e          Edit task file in nvim
  n          Edit task notes
  f          Refresh TASK.md from file
""",
            "TaskManagement": """[bold cyan]TASK MANAGEMENT[/bold cyan]
  n          Create new task
  p          Send prompt to selected task
  f          Cycle filter (all → active agents → running → queued → blocked → completed)
  a          Toggle active agents filter
  r          Refresh task list
  enter      View task details

[bold cyan]PROMPT BAR (when open)[/bold cyan]
  ↑/↓        Browse prompt history
  Enter      Send prompt
  Escape     Cancel
""",
            "ProjectManagement": """[bold cyan]PROJECT MANAGEMENT[/bold cyan]
  n          Create new project
  e          Edit selected project
  enter      View project details
""",
            "ProjectDetail": """[bold cyan]PROJECT ACTIONS[/bold cyan]
  r          Add repository
  e          Edit selected repository
  t          Create task in project
  enter      View task/repo details
""",
            "Analytics": """[bold cyan]ANALYTICS[/bold cyan]
  p          View all user prompts
  r          Refresh analytics
""",
            "Prompts": """[bold cyan]PROMPTS BROWSER[/bold cyan]
  enter      View prompt details
""",
            "PromptLibrary": """[bold cyan]PROMPT LIBRARY[/bold cyan]
  n          Create new prompt
  e          Edit selected prompt
  d          Delete selected prompt
  b          Toggle bookmark
  w          Configure workflow phases
  f          Cycle filter (all → bookmarked → history)
  /          Search prompts
"""
        }

        specific = screen_specific.get(self.screen_name, "")
        return specific + "\n" + common

    def action_dismiss(self) -> None:
        """Close the help overlay"""
        self.dismiss()


class ProjectDetailScreen(Screen):
    """Screen showing project details with repositories and tasks"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("t", "create_task", "Create Task"),
        ("r", "add_repo", "Add Repo"),
        ("e", "edit_repo", "Edit Repo"),
        ("tab", "switch_table", "Switch Table"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("question_mark", "show_help", "Help"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, project_id: str):
        super().__init__()
        self.project_id = project_id
        self.active_table = "repos"  # Track which table is focused

    def action_cursor_down(self) -> None:
        """Move cursor down (vim j)"""
        table_id = "#repos-table" if self.active_table == "repos" else "#tasks-table"
        table = self.query_one(table_id, DataTable)
        table.action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up (vim k)"""
        table_id = "#repos-table" if self.active_table == "repos" else "#tasks-table"
        table = self.query_one(table_id, DataTable)
        table.action_cursor_up()

    def action_switch_table(self) -> None:
        """Switch focus between repos and tasks tables"""
        if self.active_table == "repos":
            self.active_table = "tasks"
            self.query_one("#tasks-table", DataTable).focus()
        else:
            self.active_table = "repos"
            self.query_one("#repos-table", DataTable).focus()

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
        tasks = task_store.query_tasks(project=self.project_id)
        # Sort by task ID
        tasks = sorted(tasks, key=lambda t: t.get('task_id', ''))

        table = self.query_one("#tasks-table", DataTable)
        table.clear()
        table.add_columns("Task ID", "Title", "Status", "Priority")
        table.cursor_type = "row"

        for task in tasks:
            table.add_row(
                task['task_id'],
                task.get('title', '-')[:40],
                task['agent_status'],
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

    def action_create_task(self) -> None:
        """Show modal to create a task for this project"""
        def check_result(result):
            if result:
                self.load_tasks()

        self.app.push_screen(CreateTaskModal(project_id=self.project_id), check_result)

    def action_show_help(self) -> None:
        """Show help overlay"""
        self.app.push_screen(HelpOverlay("ProjectDetail"))


class TaskManagementScreen(Screen):
    """Screen showing all tasks across all projects"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("n", "create_task", "New Task"),
        ("p", "send_prompt", "Prompt"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("f", "toggle_filter", "Filter"),
        ("a", "filter_active", "Active"),
        ("r", "refresh", "Refresh"),
        ("s", "cycle_sort", "Sort"),
        ("S", "toggle_sort_order", "Sort↕"),
        ("question_mark", "show_help", "Help"),
        ("q", "quit", "Quit"),
    ]

    # Sort column options: id, agent, status, phase
    SORT_COLUMNS = ["id", "agent", "status", "phase"]

    def __init__(self):
        super().__init__()
        self.filter_mode = "all"  # Options: all, active_agents, running, queued, blocked, completed
        self.sort_column = "id"  # Default sort by ID
        self.sort_reverse = False  # Ascending by default
        # Prompt history navigation state
        self._prompt_history: List[str] = []
        self._history_index: int = -1  # -1 means not browsing history
        self._current_input: str = ""  # Store current input when browsing history

    def action_cursor_down(self) -> None:
        """Move cursor down (vim j)"""
        table = self.query_one("#tasks-table", DataTable)
        table.action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up (vim k)"""
        table = self.query_one("#tasks-table", DataTable)
        table.action_cursor_up()

    def action_scroll_left(self) -> None:
        """Scroll table left (vim h)"""
        table = self.query_one("#tasks-table", DataTable)
        table.action_scroll_left()

    def action_scroll_right(self) -> None:
        """Scroll table right (vim l)"""
        table = self.query_one("#tasks-table", DataTable)
        table.action_scroll_right()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static("📋 TASK MANAGEMENT", id="tasks-screen-title", classes="screen-title"),
            DataTable(id="tasks-table"),
            id="tasks-container"
        )
        yield Horizontal(
            Static("prompt> ", id="prompt-label"),
            Input(placeholder="Enter prompt (Enter=send, Esc=cancel)", id="prompt-input"),
            id="prompt-bar",
            classes="prompt-bar-hidden"
        )
        yield Footer()

    def on_mount(self) -> None:
        # Sync markdown tasks before loading
        self._sync_markdown_tasks()
        self.load_tasks()
        # Auto-refresh every 5 seconds for agent status updates
        self.set_interval(5, self.load_tasks)

    def _sync_markdown_tasks(self) -> None:
        """No longer needed - tasks are read directly from markdown files"""
        pass

    def load_tasks(self) -> None:
        """Load and display all tasks with full metadata (scroll h/l for more columns)"""
        all_tasks = task_store.list_all_tasks()

        # Apply filter
        if self.filter_mode == "active_agents":
            tasks = [t for t in all_tasks if t.get('tmux_session')]
        elif self.filter_mode == "running":
            tasks = [t for t in all_tasks if t.get('agent_status') == 'running']
        elif self.filter_mode == "queued":
            tasks = [t for t in all_tasks if t.get('agent_status') == 'queued']
        elif self.filter_mode == "blocked":
            tasks = [t for t in all_tasks if t.get('agent_status') == 'blocked']
        elif self.filter_mode == "completed":
            tasks = [t for t in all_tasks if t.get('agent_status') == 'completed']
        else:  # "all"
            tasks = all_tasks

        # Sort by selected column
        def get_sort_key(task):
            if self.sort_column == "id":
                return task.get('task_id', '')
            elif self.sort_column == "agent":
                return task.get('agent_status', '')
            elif self.sort_column == "status":
                return task.get('agent_status', '')
            elif self.sort_column == "phase":
                return task.get('phase', '')
            return task.get('task_id', '')

        tasks = sorted(tasks, key=get_sort_key, reverse=self.sort_reverse)

        # Check agent health and send desktop notifications
        # (only when viewing all tasks or active agents to avoid duplicate checks)
        if self.filter_mode in ["all", "active_agents"]:
            from agentctl.core.agent_monitor import get_all_agent_statuses, check_and_notify_state_changes
            agent_statuses = get_all_agent_statuses()
            check_and_notify_state_changes(agent_statuses)

        # Update title to show current filter and sort
        title_prefix = "📋 TASK MANAGEMENT"
        filter_indicators = {
            "all": "",
            "active_agents": " - 🤖 ACTIVE AGENTS",
            "running": " - 🟢 RUNNING",
            "queued": " - ⚪ QUEUED",
            "blocked": " - 🟡 BLOCKED",
            "completed": " - ✅ COMPLETED"
        }
        title_text = title_prefix + filter_indicators.get(self.filter_mode, "")

        # Add task count if filtered
        if self.filter_mode != "all":
            title_text += f" ({len(tasks)}/{len(all_tasks)})"

        # Add sort indicator
        sort_arrow = "↓" if not self.sort_reverse else "↑"
        title_text += f" [dim][s] {self.sort_column.upper()}{sort_arrow}[/dim]"

        # Update title dynamically
        try:
            title_widget = self.query_one("#tasks-screen-title", Static)
            title_widget.update(title_text)
        except:
            pass

        table = self.query_one("#tasks-table", DataTable)

        # Save current cursor position before clearing
        current_row = table.cursor_row if table.row_count > 0 else 0

        table.clear()
        # Only add columns on first load
        if len(table.columns) == 0:
            # Full columns - use h/l to scroll horizontally
            table.add_columns(
                "ID", "Agent", "Title", "Status", "Phase", "Category",
                "Project", "tmux", "Branch", "Notes"
            )
            table.cursor_type = "row"

        for task in tasks:
            status_display = {
                "queued": "⚪ queued",
                "running": "🟢 running",
                "blocked": "🟡 blocked",
                "completed": "✅ done",
                "failed": "🔴 failed"
            }.get(task.get('agent_status', 'queued'), "⚪ ?")

            priority_display = {
                "high": "🔴 high",
                "medium": "🟡 med",
                "low": "🟢 low"
            }.get(task.get('priority', 'medium'), "?")

            # Agent indicator (simple check, no expensive tmux queries)
            tmux_session = task.get('tmux_session')
            if tmux_session:
                from agentctl.core.tmux import session_exists
                if session_exists(tmux_session):
                    agent_display = "🟢 active"
                else:
                    agent_display = "🔴 exited"
            else:
                agent_display = "- none"

            # Category and type
            category = task.get('category', '-')[:8]
            task_type = task.get('type', '-')[:10]

            # Project name
            project = task.get('project_name', task.get('project', '-'))[:15]

            # Branch (truncated)
            branch = task.get('git_branch') or '-'
            if len(branch) > 20:
                branch = branch[:17] + "..."

            # tmux session name
            tmux_display = tmux_session[:15] if tmux_session else "-"

            # Notes preview
            notes = task.get('notes', '')
            notes_preview = notes[:20] + "..." if len(notes) > 20 else (notes or "-")

            # Phase (full display name)
            phase = task.get('phase')
            phase_display = task_md.get_phase_display_name(phase) if phase else '-'

            table.add_row(
                task['task_id'],
                agent_display,
                task.get('title', '-')[:35],
                status_display,
                phase_display,
                category,
                project,
                tmux_display,
                branch,
                notes_preview
            )

        # Restore cursor position (clamped to valid range)
        if table.row_count > 0:
            restored_row = min(current_row, table.row_count - 1)
            table.move_cursor(row=restored_row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection - open task detail view"""
        if event.data_table.id == "tasks-table":
            row = event.data_table.get_row_at(event.cursor_row)
            task_id = str(row[0])  # Task ID is first column
            self.app.push_screen(TaskDetailScreen(task_id))

    def action_go_back(self) -> None:
        """Go back to main dashboard"""
        self.app.pop_screen()

    def action_send_prompt(self) -> None:
        """Show inline prompt input bar for the selected task"""
        from agentctl.core.tmux import session_exists

        table = self.query_one("#tasks-table", DataTable)
        if table.row_count == 0 or table.cursor_row is None:
            self.app.notify("No task selected", severity="warning")
            return

        row = table.get_row_at(table.cursor_row)
        task_id = str(row[0])  # Task ID is first column

        # Get task data to find tmux session
        task_data = task_store.get_task_with_details(task_id)
        if not task_data:
            self.app.notify(f"Task {task_id} not found", severity="error")
            return

        tmux_session = task_data.get('tmux_session')
        if not tmux_session:
            self.app.notify("No tmux session for this task", severity="warning")
            return

        if not session_exists(tmux_session):
            self.app.notify(f"Session '{tmux_session}' not found", severity="error")
            return

        # Store task info for when prompt is submitted
        self._prompt_task_id = task_id
        self._prompt_tmux_session = tmux_session

        # Load bookmarked prompts first, then recent history
        bookmarked = prompt_store.get_bookmarked_prompts(limit=10)
        recent = prompt_store.get_recent_prompts(limit=20)

        # Combine: bookmarked first, then history (deduplicated)
        self._prompt_history = []
        seen_texts = set()
        for p in bookmarked:
            if p['text'] not in seen_texts:
                self._prompt_history.append(p['text'])
                seen_texts.add(p['text'])
        for p in recent:
            if p['text'] not in seen_texts:
                self._prompt_history.append(p['text'])
                seen_texts.add(p['text'])

        self._history_index = -1
        self._current_input = ""

        # Show the prompt bar and focus the input
        prompt_bar = self.query_one("#prompt-bar")
        prompt_bar.remove_class("prompt-bar-hidden")
        prompt_bar.add_class("prompt-bar-visible")
        prompt_input = self.query_one("#prompt-input", Input)
        prompt_input.value = ""
        prompt_input.focus()

    def _hide_prompt_bar(self) -> None:
        """Hide the inline prompt bar"""
        prompt_bar = self.query_one("#prompt-bar")
        prompt_bar.remove_class("prompt-bar-visible")
        prompt_bar.add_class("prompt-bar-hidden")
        prompt_input = self.query_one("#prompt-input", Input)
        prompt_input.value = ""
        self._prompt_task_id = None
        self._prompt_tmux_session = None
        # Reset history navigation state
        self._history_index = -1
        self._current_input = ""

    def _navigate_history(self, direction: int) -> None:
        """Navigate through prompt history. direction: -1 for older, +1 for newer"""
        prompt_input = self.query_one("#prompt-input", Input)

        if not self._prompt_history:
            return

        # Save current input when starting to browse history
        if self._history_index == -1 and direction == -1:
            self._current_input = prompt_input.value

        new_index = self._history_index + direction

        if new_index < -1:
            new_index = -1
        elif new_index >= len(self._prompt_history):
            new_index = len(self._prompt_history) - 1

        self._history_index = new_index

        if self._history_index == -1:
            # Back to current input
            prompt_input.value = self._current_input
        else:
            # Show history item
            prompt_input.value = self._prompt_history[self._history_index]

        # Move cursor to end
        prompt_input.cursor_position = len(prompt_input.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter in the prompt input"""
        if event.input.id == "prompt-input" and event.value:
            tmux_session = getattr(self, '_prompt_tmux_session', None)
            task_id = getattr(self, '_prompt_task_id', None)
            if tmux_session:
                success = tmux_send_keys(tmux_session, event.value, enter=True)
                if success:
                    # Log to prompt history
                    prompt_store.add_to_history(event.value, task_id=task_id)
                    preview = event.value[:40] + "..." if len(event.value) > 40 else event.value
                    self.app.notify(f"✓ {preview} [u=library]", severity="success")
                else:
                    self.app.notify("Failed to send prompt", severity="error")
            self._hide_prompt_bar()

    def on_key(self, event) -> None:
        """Handle special keys in prompt input"""
        try:
            prompt_bar = self.query_one("#prompt-bar")
            if "prompt-bar-visible" not in prompt_bar.classes:
                return

            if event.key == "escape":
                self._hide_prompt_bar()
                event.prevent_default()
                event.stop()
            elif event.key == "up":
                # Navigate to older history
                self._navigate_history(-1)
                event.prevent_default()
                event.stop()
            elif event.key == "down":
                # Navigate to newer history
                self._navigate_history(1)
                event.prevent_default()
                event.stop()
            elif event.key == "ctrl+r":
                # Open prompt library for selection
                self._open_prompt_selector()
                event.prevent_default()
                event.stop()
        except Exception:
            pass

    def _open_prompt_selector(self) -> None:
        """Open PromptLibraryScreen for selecting a prompt"""
        def handle_selection(selected_text: Optional[str]) -> None:
            if selected_text:
                prompt_input = self.query_one("#prompt-input", Input)
                prompt_input.value = selected_text
                prompt_input.cursor_position = len(selected_text)
                prompt_input.focus()

        self.app.push_screen(PromptLibraryScreen(select_mode=True), handle_selection)

    def _build_repository_comment(self, project_id: str) -> str:
        """Build a helpful comment showing available repositories"""
        repositories = database.list_repositories()

        # Filter to repositories for this project (if any association exists)
        # For now, show all repositories
        if not repositories:
            return "<!-- No repositories configured -->"

        lines = ["<!-- Available Repositories:"]
        for repo in repositories:
            repo_path = repo.get('path', 'N/A')
            lines.append(f"  {repo['id']}: {repo_path}")
        lines.append("-->")
        lines.append("")
        lines.append("<!-- To use a repository, set repository_id in frontmatter above -->")

        return "\n".join(lines)

    def action_create_task(self) -> None:
        """Create a new task using step-by-step prompts"""
        def check_result(result):
            if result:
                self.load_tasks()

        self.app.push_screen(CreateTaskPromptScreen(), check_result)

    def action_edit_task(self) -> None:
        """Edit selected task in nvim"""
        table = self.query_one("#tasks-table", DataTable)
        if table.row_count > 0 and table.cursor_row is not None:
            row = table.get_row_at(table.cursor_row)
            task_id = str(row[0])  # Task ID is first column

            # Get task to find the markdown file path
            task = task_store.get_task(task_id)
            if task:
                project = database.get_project(task['project_id'])
                if project and project.get('tasks_path'):
                    from pathlib import Path
                    task_file = Path(project['tasks_path']) / f"{task_id}.md"

                    if task_file.exists():
                        # Define callback to reload after nvim closes
                        def after_nvim():
                            # Reload the task list to show updated data
                            self.load_tasks()
                            self.app.notify(f"Task {task_id} updated", severity="success")

                        # Suspend TUI and open nvim
                        import subprocess

                        # Store the callback for after resume
                        self._after_resume_callback = after_nvim

                        # Exit TUI, run nvim, then re-enter
                        with self.app.suspend():
                            subprocess.run(['nvim', str(task_file)])

                        # Execute callback
                        if hasattr(self, '_after_resume_callback'):
                            self._after_resume_callback()
                            delattr(self, '_after_resume_callback')
                    else:
                        self.app.notify(f"Task file not found: {task_file}", severity="error")
                else:
                    self.app.notify("Task has no tasks_path configured", severity="error")
            else:
                self.app.notify(f"Task {task_id} not found", severity="error")

    def action_delete_task(self) -> None:
        """Delete selected task with confirmation"""
        table = self.query_one("#tasks-table", DataTable)
        if table.row_count > 0 and table.cursor_row is not None:
            row = table.get_row_at(table.cursor_row)
            task_id = str(row[0])  # Task ID is first column

            # Get task details for confirmation
            task_data = task_store.get_task(task_id)
            task_title = task_data.get('title', 'Unknown') if task_data else 'Unknown'

            def handle_delete(confirmed: bool) -> None:
                if confirmed:
                    try:
                        success = delete_task(task_id)
                        if not success:
                            self.app.notify("Failed to delete task", severity="error")
                            return
                        self.load_tasks()
                        self.app.notify(f"Task {task_id} deleted", severity="warning")
                    except Exception as e:
                        self.app.notify(f"Error deleting task: {e}", severity="error")

            self.app.push_screen(ConfirmDeleteModal(task_id, task_title), handle_delete)

    def action_toggle_filter(self) -> None:
        """Cycle through filter modes"""
        filters = ["all", "active_agents", "running", "queued", "blocked", "completed"]
        current_idx = filters.index(self.filter_mode) if self.filter_mode in filters else 0
        self.filter_mode = filters[(current_idx + 1) % len(filters)]
        self.load_tasks()
        filter_display = self.filter_mode.replace('_', ' ').title()
        self.app.notify(f"Filter: {filter_display}", severity="information")

    def action_filter_active(self) -> None:
        """Quick toggle to active agents filter"""
        self.filter_mode = "active_agents" if self.filter_mode != "active_agents" else "all"
        self.load_tasks()
        filter_label = "Active Agents Only" if self.filter_mode == "active_agents" else "All Tasks"
        self.app.notify(f"Filter: {filter_label}", severity="information")

    def action_refresh(self) -> None:
        """Manually refresh task list"""
        self.load_tasks()
        self.app.notify("Tasks refreshed", severity="information")

    def action_cycle_sort(self) -> None:
        """Cycle through sort columns (s key)"""
        current_idx = self.SORT_COLUMNS.index(self.sort_column) if self.sort_column in self.SORT_COLUMNS else 0
        self.sort_column = self.SORT_COLUMNS[(current_idx + 1) % len(self.SORT_COLUMNS)]
        self.load_tasks()
        sort_arrow = "↓" if not self.sort_reverse else "↑"
        self.app.notify(f"Sort: {self.sort_column.upper()} {sort_arrow}", severity="information")

    def action_toggle_sort_order(self) -> None:
        """Toggle sort order ascending/descending (S key)"""
        self.sort_reverse = not self.sort_reverse
        self.load_tasks()
        order_label = "Descending" if self.sort_reverse else "Ascending"
        sort_arrow = "↑" if self.sort_reverse else "↓"
        self.app.notify(f"Sort: {self.sort_column.upper()} {sort_arrow} ({order_label})", severity="information")

    def action_show_help(self) -> None:
        """Show help overlay"""
        self.app.push_screen(HelpOverlay("TaskManagement"))


class WorkflowConfigModal(ModalScreen):
    """Modal for configuring prompt-to-phase workflow mappings"""

    def __init__(self, prompt_id: str, prompt_title: str):
        super().__init__()
        self.prompt_id = prompt_id
        self.prompt_title = prompt_title
        self.current_phases: List[str] = []

    def compose(self) -> ComposeResult:
        # Get phases this prompt is currently assigned to
        for phase in task_md.VALID_PHASE:
            if prompt_store.is_prompt_in_workflow(self.prompt_id, phase):
                self.current_phases.append(phase)

        yield Container(
            Label(f"⚙️ Workflow: {self.prompt_title[:30]}", id="modal-title"),
            Static("Select phases where this prompt should be suggested:", classes="detail-row"),
            DataTable(id="phase-table"),
            Static("[dim]Space/Enter to toggle, Esc to close[/dim]", classes="detail-row"),
            Container(
                Button("Done", id="done-btn", variant="success"),
                classes="button-row"
            ),
            id="workflow-config-modal"
        )

    def on_mount(self) -> None:
        table = self.query_one("#phase-table", DataTable)
        table.add_columns("Enabled", "Phase")
        table.cursor_type = "row"

        for phase in task_md.VALID_PHASE:
            enabled = "✓" if phase in self.current_phases else ""
            display_name = task_md.get_phase_display_name(phase)
            table.add_row(enabled, display_name, key=phase)

        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Toggle phase assignment on Enter/Space"""
        self._toggle_selected_phase()

    def _toggle_selected_phase(self) -> None:
        """Toggle the currently selected phase"""
        table = self.query_one("#phase-table", DataTable)
        if table.cursor_row is None:
            return

        phase = task_md.VALID_PHASE[table.cursor_row]

        if phase in self.current_phases:
            # Remove from workflow
            prompt_store.remove_prompt_from_workflow(self.prompt_id, phase)
            self.current_phases.remove(phase)
            self.app.notify(f"Removed from {phase}", severity="information")
        else:
            # Add to workflow
            prompt_store.add_prompt_to_workflow(self.prompt_id, phase)
            self.current_phases.append(phase)
            self.app.notify(f"Added to {phase}", severity="success")

        # Refresh table
        self._refresh_table()

    def _refresh_table(self) -> None:
        """Refresh the table display"""
        table = self.query_one("#phase-table", DataTable)
        cursor_row = table.cursor_row
        table.clear()

        for phase in task_md.VALID_PHASE:
            enabled = "✓" if phase in self.current_phases else ""
            display_name = task_md.get_phase_display_name(phase)
            table.add_row(enabled, display_name, key=phase)

        # Restore cursor position
        if cursor_row is not None and cursor_row < table.row_count:
            table.move_cursor(row=cursor_row)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "done-btn":
            self.dismiss(True)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(True)
        elif event.key == "space":
            self._toggle_selected_phase()
            event.prevent_default()
            event.stop()


class PromptLibraryScreen(Screen):
    """Screen for managing the prompt library and viewing history"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("enter", "select_prompt", "Select"),
        ("n", "new_prompt", "New"),
        ("e", "edit_prompt", "Edit"),
        ("d", "delete_prompt", "Delete"),
        ("b", "toggle_bookmark", "Bookmark"),
        ("w", "configure_workflow", "Workflow"),
        ("f", "toggle_filter", "Filter"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("slash", "search", "Search"),
        ("question_mark", "show_help", "Help"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, select_mode: bool = False):
        super().__init__()
        self.select_mode = select_mode  # If True, Enter returns selected prompt
        self.filter_mode = "history" if select_mode else "all"  # Start with history in select mode
        self.search_term = ""
        self.prompts_data: List[Dict] = []

    def compose(self) -> ComposeResult:
        title = "🔍 SELECT PROMPT (Enter=select, Esc=cancel)" if self.select_mode else "📚 PROMPT LIBRARY"
        yield Header()
        yield Container(
            Static(title, id="prompts-screen-title", classes="screen-title"),
            Static("", id="filter-status"),
            DataTable(id="prompts-table"),
            id="prompts-container"
        )
        yield Horizontal(
            Static("search> ", id="search-label"),
            Input(placeholder="Type to search prompts (Enter=search, Esc=cancel)", id="search-input"),
            id="search-bar",
            classes="prompt-bar-hidden"
        )
        yield Footer()

    def on_mount(self) -> None:
        self.load_prompts()
        # Focus table so Enter key works immediately
        table = self.query_one("#prompts-table", DataTable)
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle DataTable row selection (Enter key on a row)"""
        self.action_select_prompt()

    def load_prompts(self) -> None:
        """Load prompts based on current filter"""
        table = self.query_one("#prompts-table", DataTable)
        table.clear()

        if len(table.columns) == 0:
            table.add_columns("★", "Title", "Category", "Phase", "Uses", "Last Used")
            table.cursor_type = "row"

        # Get prompts based on filter mode
        if self.filter_mode == "bookmarked":
            self.prompts_data = prompt_store.list_prompts(is_bookmarked=True, search=self.search_term or None)
        elif self.filter_mode == "history":
            # Show recent history entries
            history = prompt_store.get_recent_prompts(limit=50)
            self.prompts_data = []
            for h in history:
                self.prompts_data.append({
                    'id': None,
                    'title': h['text'][:30] + "..." if len(h['text']) > 30 else h['text'],
                    'text': h['text'],
                    'category': None,
                    'phase': None,
                    'is_bookmarked': False,
                    'use_count': h['send_count'],
                    'updated_at': h['last_sent'],
                })
        else:
            self.prompts_data = prompt_store.list_prompts(search=self.search_term or None)

        for prompt in self.prompts_data:
            bookmark_icon = "★" if prompt.get('is_bookmarked') else " "
            title = prompt.get('title') or prompt.get('text', '')[:30]
            title = self._truncate(title, 30)
            category = prompt.get('category') or "-"
            phase = prompt.get('phase') or "-"
            use_count = str(prompt.get('use_count', 0))

            updated = prompt.get('updated_at')
            if updated:
                if hasattr(updated, 'strftime'):
                    last_used = updated.strftime("%Y-%m-%d %H:%M")
                else:
                    last_used = str(updated)[:16]
            else:
                last_used = "-"

            table.add_row(bookmark_icon, title, category, phase, use_count, last_used)

        # Update filter status
        filter_status = self.query_one("#filter-status", Static)
        filter_labels = {
            "all": "All Prompts",
            "bookmarked": "★ Bookmarked",
            "history": "📜 Recent History",
        }
        count = len(self.prompts_data)
        search_info = f" matching '{self.search_term}'" if self.search_term else ""
        filter_status.update(f"[dim]{filter_labels.get(self.filter_mode, 'All')} ({count} items){search_info}[/dim]")

    def _truncate(self, text: str, max_len: int) -> str:
        """Truncate text with ellipsis if too long"""
        if not text:
            return "-"
        if len(text) > max_len:
            return text[:max_len - 1] + "…"
        return text

    def action_cursor_down(self) -> None:
        """Move cursor down (vim j)"""
        table = self.query_one("#prompts-table", DataTable)
        table.action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up (vim k)"""
        table = self.query_one("#prompts-table", DataTable)
        table.action_cursor_up()

    def action_go_back(self) -> None:
        """Return to previous screen"""
        if self.select_mode:
            self.dismiss(None)  # Return None to indicate cancellation
        else:
            self.app.pop_screen()

    def action_select_prompt(self) -> None:
        """Select the current prompt (in select mode, returns to caller)"""
        table = self.query_one("#prompts-table", DataTable)
        if table.row_count == 0 or table.cursor_row is None:
            return

        if table.cursor_row >= len(self.prompts_data):
            return

        prompt = self.prompts_data[table.cursor_row]
        prompt_text = prompt.get('text', '')

        if self.select_mode:
            # Return the selected prompt text
            self.dismiss(prompt_text)
        else:
            # Normal mode - could open detail view or do nothing
            pass

    def action_toggle_filter(self) -> None:
        """Cycle through filter modes"""
        filters = ["all", "bookmarked", "history"]
        current_idx = filters.index(self.filter_mode) if self.filter_mode in filters else 0
        self.filter_mode = filters[(current_idx + 1) % len(filters)]
        self.load_prompts()
        self.app.notify(f"Filter: {self.filter_mode.title()}", severity="information")

    def action_toggle_bookmark(self) -> None:
        """Toggle bookmark on selected prompt"""
        table = self.query_one("#prompts-table", DataTable)
        if table.row_count == 0 or table.cursor_row is None:
            return

        if table.cursor_row >= len(self.prompts_data):
            return

        prompt = self.prompts_data[table.cursor_row]
        prompt_id = prompt.get('id')

        if not prompt_id:
            # History entry - save to library first, then bookmark
            prompt_text = prompt.get('text', '')
            if not prompt_text:
                return
            # Create prompt with bookmark already set
            new_id = prompt_store.create_prompt(
                text=prompt_text,
                title=prompt_text[:30] + "..." if len(prompt_text) > 30 else prompt_text,
                is_bookmarked=True
            )
            self.app.notify("★ Saved to library and bookmarked", severity="success")
            self.load_prompts()
            return

        new_status = prompt_store.toggle_bookmark(prompt_id)
        if new_status is not None:
            icon = "★" if new_status else "☆"
            self.app.notify(f"{icon} Bookmark {'added' if new_status else 'removed'}", severity="success")
            self.load_prompts()

    def action_configure_workflow(self) -> None:
        """Configure which workflow phases this prompt appears in"""
        table = self.query_one("#prompts-table", DataTable)
        if table.row_count == 0 or table.cursor_row is None:
            return

        if table.cursor_row >= len(self.prompts_data):
            return

        prompt = self.prompts_data[table.cursor_row]
        prompt_id = prompt.get('id')

        if not prompt_id:
            # History entry - need to save first
            self.app.notify("Save prompt to library first (press 'b' to bookmark)", severity="warning")
            return

        prompt_title = prompt.get('title') or prompt['text'][:30]

        def handle_result(result):
            if result:
                self.load_prompts()

        self.app.push_screen(WorkflowConfigModal(prompt_id, prompt_title), handle_result)

    def action_new_prompt(self) -> None:
        """Create a new prompt in the library"""
        def handle_result(result):
            if result:
                self.load_prompts()

        self.app.push_screen(CreatePromptModal(), handle_result)

    def action_edit_prompt(self) -> None:
        """Edit selected prompt"""
        table = self.query_one("#prompts-table", DataTable)
        if table.row_count == 0 or table.cursor_row is None:
            return

        if table.cursor_row >= len(self.prompts_data):
            return

        prompt = self.prompts_data[table.cursor_row]
        prompt_id = prompt.get('id')
        if not prompt_id:
            # For history items, offer to save as new prompt
            def handle_save(result):
                if result:
                    self.load_prompts()

            self.app.push_screen(CreatePromptModal(initial_text=prompt.get('text', '')), handle_save)
            return

        def handle_result(result):
            if result:
                self.load_prompts()

        self.app.push_screen(EditPromptModal(prompt_id), handle_result)

    def action_delete_prompt(self) -> None:
        """Delete selected prompt"""
        table = self.query_one("#prompts-table", DataTable)
        if table.row_count == 0 or table.cursor_row is None:
            return

        if table.cursor_row >= len(self.prompts_data):
            return

        prompt = self.prompts_data[table.cursor_row]
        prompt_id = prompt.get('id')
        if not prompt_id:
            self.app.notify("Cannot delete history entry", severity="warning")
            return

        title = prompt.get('title') or prompt.get('text', '')[:30]

        def handle_delete(confirmed: bool) -> None:
            if confirmed:
                if prompt_store.delete_prompt(prompt_id):
                    self.app.notify(f"Prompt deleted", severity="warning")
                    self.load_prompts()
                else:
                    self.app.notify("Failed to delete prompt", severity="error")

        self.app.push_screen(ConfirmDeleteModal(prompt_id, title), handle_delete)

    def action_search(self) -> None:
        """Show search bar"""
        search_bar = self.query_one("#search-bar")
        search_bar.remove_class("prompt-bar-hidden")
        search_bar.add_class("prompt-bar-visible")
        search_input = self.query_one("#search-input", Input)
        search_input.value = self.search_term
        search_input.focus()

    def _hide_search_bar(self) -> None:
        """Hide the search bar"""
        search_bar = self.query_one("#search-bar")
        search_bar.remove_class("prompt-bar-visible")
        search_bar.add_class("prompt-bar-hidden")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search input"""
        if event.input.id == "search-input":
            self.search_term = event.value
            self._hide_search_bar()
            self.load_prompts()

    def on_key(self, event) -> None:
        """Handle Escape to cancel search"""
        if event.key == "escape":
            try:
                search_bar = self.query_one("#search-bar")
                if "prompt-bar-visible" in search_bar.classes:
                    self._hide_search_bar()
                    event.prevent_default()
                    event.stop()
            except Exception:
                pass

    def action_show_help(self) -> None:
        """Show help overlay"""
        self.app.push_screen(HelpOverlay("PromptLibrary"))


class CreatePromptModal(ModalScreen):
    """Modal for creating a new prompt in the library"""

    def __init__(self, initial_text: str = ""):
        super().__init__()
        self.initial_text = initial_text

    def compose(self) -> ComposeResult:
        yield Container(
            Label("📝 New Prompt", id="modal-title"),
            Static("Title (optional):", classes="detail-row"),
            Input(placeholder="e.g., Fix failing tests", id="title-input"),
            Static("Prompt text:", classes="detail-row"),
            Input(value=self.initial_text, placeholder="Enter the prompt content...", id="text-input"),
            Static("Category (optional):", classes="detail-row"),
            Input(placeholder="e.g., debugging, testing, code-review", id="category-input"),
            Static("Tags (optional):", classes="detail-row"),
            Input(placeholder="e.g., python, api, refactor (comma-separated)", id="tags-input"),
            Static("Phase (optional):", classes="detail-row"),
            Input(placeholder="e.g., planning, implementing, testing", id="phase-input"),
            Container(
                Button("Save", id="save-btn", variant="success"),
                Button("Cancel", id="cancel-btn", variant="primary"),
                classes="button-row"
            ),
            id="create-prompt-modal"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            text = self.query_one("#text-input", Input).value
            if not text:
                self.app.notify("Prompt text is required", severity="warning")
                return

            title = self.query_one("#title-input", Input).value or None
            category = self.query_one("#category-input", Input).value or None
            tags = self.query_one("#tags-input", Input).value or None
            phase = self.query_one("#phase-input", Input).value or None

            try:
                prompt_store.create_prompt(
                    text=text,
                    title=title,
                    category=category,
                    tags=tags,
                    phase=phase,
                )
                self.app.notify("Prompt saved to library", severity="success")
                self.dismiss(True)
            except Exception as e:
                self.app.notify(f"Error saving prompt: {e}", severity="error")


class EditPromptModal(ModalScreen):
    """Modal for editing a prompt in the library"""

    def __init__(self, prompt_id: str):
        super().__init__()
        self.prompt_id = prompt_id
        self.prompt_data = None

    def compose(self) -> ComposeResult:
        self.prompt_data = prompt_store.get_prompt(self.prompt_id)
        if not self.prompt_data:
            yield Container(
                Label("❌ Prompt not found", id="modal-title"),
                Button("Close", id="cancel-btn", variant="primary"),
                id="edit-prompt-modal"
            )
            return

        yield Container(
            Label("✏️ Edit Prompt", id="modal-title"),
            Static("Title (optional):", classes="detail-row"),
            Input(value=self.prompt_data.get('title') or "", placeholder="e.g., Fix failing tests", id="title-input"),
            Static("Prompt text:", classes="detail-row"),
            Input(value=self.prompt_data.get('text', ''), placeholder="Enter the prompt content...", id="text-input"),
            Static("Category (optional):", classes="detail-row"),
            Input(value=self.prompt_data.get('category') or "", placeholder="e.g., debugging, testing, code-review", id="category-input"),
            Static("Tags (optional):", classes="detail-row"),
            Input(value=self.prompt_data.get('tags') or "", placeholder="e.g., python, api, refactor (comma-separated)", id="tags-input"),
            Static("Phase (optional):", classes="detail-row"),
            Input(value=self.prompt_data.get('phase') or "", placeholder="e.g., planning, implementing, testing", id="phase-input"),
            Container(
                Button("Save", id="save-btn", variant="success"),
                Button("Cancel", id="cancel-btn", variant="primary"),
                classes="button-row"
            ),
            id="edit-prompt-modal"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            text = self.query_one("#text-input", Input).value
            if not text:
                self.app.notify("Prompt text is required", severity="warning")
                return

            title = self.query_one("#title-input", Input).value or None
            category = self.query_one("#category-input", Input).value or None
            tags = self.query_one("#tags-input", Input).value or None
            phase = self.query_one("#phase-input", Input).value or None

            try:
                prompt_store.update_prompt(
                    self.prompt_id,
                    text=text,
                    title=title,
                    category=category,
                    tags=tags,
                    phase=phase,
                )
                self.app.notify("Prompt updated", severity="success")
                self.dismiss(True)
            except Exception as e:
                self.app.notify(f"Error updating prompt: {e}", severity="error")


class CreateTaskPromptScreen(Screen):
    """Screen for collecting task metadata via simple prompts"""

    def __init__(self):
        super().__init__()
        self.step = 0
        self.project_id = None
        self.repository_id = None
        self.category = 'FEATURE'
        self.priority = 'medium'
        self.projects = []
        self.repositories = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static("", id="prompt-text"),
            Static("", id="options-text"),
            id="prompt-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        self.projects = database.list_projects()
        self.repositories = database.list_repositories()
        self.show_next_prompt()

    def show_next_prompt(self) -> None:
        prompt_text = self.query_one("#prompt-text", Static)
        options_text = self.query_one("#options-text", Static)

        if self.step == 0:
            # Select project
            prompt_text.update("📦 SELECT PROJECT (press number):")
            if not self.projects:
                options_text.update("\nNo projects found. Press ESC to go back.")
            else:
                options = "\n".join([f"  [{i+1}] {p['name']} ({p['id']})"
                                    for i, p in enumerate(self.projects)])
                options_text.update(f"\n{options}\n\nPress ESC to cancel")

        elif self.step == 1:
            # Select repository
            prompt_text.update(f"📂 SELECT REPOSITORY for {self.project_id} (press number or 'n' for none):")
            if not self.repositories:
                options_text.update("\nNo repositories found. Press 'n' for none or ESC to go back.")
            else:
                options = "\n".join([f"  [{i+1}] {r['name']} ({r['id']})"
                                    for i, r in enumerate(self.repositories)])
                options_text.update(f"\n{options}\n  [n] None\n\nPress ESC to go back")

        elif self.step == 2:
            # Select category
            prompt_text.update("📋 SELECT CATEGORY (press number):")
            options_text.update("""
  [1] FEATURE
  [2] BUG
  [3] REFACTOR
  [4] DOCS
  [5] TEST
  [6] CHORE

Press ESC to go back""")

        elif self.step == 3:
            # Select priority
            prompt_text.update("⚡ SELECT PRIORITY (press number):")
            options_text.update("""
  [1] Low
  [2] Medium
  [3] High

Press ESC to go back""")

    def on_key(self, event) -> None:
        if event.key == "escape":
            if self.step == 0:
                # Cancel and go back
                self.dismiss(False)
            else:
                # Go back one step
                self.step -= 1
                self.show_next_prompt()
            return

        if self.step == 0:
            # Project selection
            try:
                choice = int(event.key) - 1
                if 0 <= choice < len(self.projects):
                    self.project_id = self.projects[choice]['id']
                    self.step += 1
                    self.show_next_prompt()
            except (ValueError, IndexError):
                pass

        elif self.step == 1:
            # Repository selection
            if event.key == 'n':
                self.repository_id = None
                self.step += 1
                self.show_next_prompt()
            else:
                try:
                    choice = int(event.key) - 1
                    if 0 <= choice < len(self.repositories):
                        self.repository_id = self.repositories[choice]['id']
                        self.step += 1
                        self.show_next_prompt()
                except (ValueError, IndexError):
                    pass

        elif self.step == 2:
            # Category selection
            categories = ['FEATURE', 'BUG', 'REFACTOR', 'DOCS', 'TEST', 'CHORE']
            try:
                choice = int(event.key) - 1
                if 0 <= choice < len(categories):
                    self.category = categories[choice]
                    self.step += 1
                    self.show_next_prompt()
            except (ValueError, IndexError):
                pass

        elif self.step == 3:
            # Priority selection
            priorities = ['low', 'medium', 'high']
            try:
                choice = int(event.key) - 1
                if 0 <= choice < len(priorities):
                    self.priority = priorities[choice]
                    # Done with prompts, open nvim
                    self.open_nvim_template()
            except (ValueError, IndexError):
                pass

    def open_nvim_template(self) -> None:
        """Open nvim with pre-filled template"""
        from pathlib import Path
        import subprocess

        try:
            # Get project
            project = database.get_project(self.project_id)
            if not project or not project.get('tasks_path'):
                self.app.notify("Project has no tasks_path configured", severity="error")
                self.dismiss(False)
                return

            tasks_path = Path(project['tasks_path'])

            # Generate next task ID based on selected category
            next_id = task_md.get_next_task_id(tasks_path, self.project_id, self.category)

            # Generate template with collected metadata
            template_data = task_md.generate_task_template(
                task_id=next_id,
                title="New task - edit this title",
                project_id=self.project_id,
                repository_id=self.repository_id,
                category=self.category,
                priority=self.priority
            )

            # Create temporary file
            temp_file = tasks_path / f".{next_id}.md.tmp"
            task_md.write_task_file(temp_file, template_data, "# New Task\n\nEdit the title above and add description here...")

            # Open in nvim
            with self.app.suspend():
                subprocess.run(['nvim', str(temp_file)])

            # After nvim closes, validate and save
            task_created = False
            if temp_file.exists():
                task_data, body, errors = task_md.parse_task_file(temp_file)

                if errors:
                    self.app.notify(f"Task validation failed: {'; '.join(errors)}", severity="error")
                    temp_file.unlink()
                elif task_data:
                    # Check if user made any meaningful edits (title or body changed)
                    title_changed = task_data.get('title') != "New task - edit this title"
                    body_unchanged = body.strip() == "# New Task\n\nEdit the title above and add description here..."

                    if title_changed or not body_unchanged:
                        # Valid task that was edited - move to permanent location
                        final_file = tasks_path / f"{next_id}.md"
                        temp_file.rename(final_file)

                        self.app.notify(f"Task {next_id} created!", severity="success")
                        task_created = True
                    else:
                        # User didn't edit - discard
                        temp_file.unlink()
                        self.app.notify("Task creation cancelled - no changes made", severity="information")
                else:
                    # No task data parsed
                    temp_file.unlink()
                    self.app.notify("Task creation cancelled", severity="information")

            # Go back to task list with result
            self.dismiss(task_created)
        except Exception as e:
            self.app.notify(f"Error creating task: {str(e)}", severity="error")
            self.dismiss(False)


class WindowPickerModal(ModalScreen):
    """Modal for selecting which window to send a prompt to"""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, windows: List[Dict]):
        super().__init__()
        self.windows = windows

    def compose(self) -> ComposeResult:
        yield Container(
            Static("[bold cyan]Select Window[/bold cyan]", classes="modal-title"),
            DataTable(id="windows-table"),
            Static("[dim]Enter to select, Escape to cancel[/dim]", classes="modal-hint"),
            id="window-picker-container",
            classes="modal-container"
        )

    def on_mount(self) -> None:
        table = self.query_one("#windows-table", DataTable)
        table.add_columns("#", "Window", "Status")
        table.cursor_type = "row"

        for i, w in enumerate(self.windows):
            table.add_row(str(i), f"{w['name']} ({w['index']})", f"{w['icon']} {w['summary'][:30]}")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle Enter on a row"""
        self.dismiss(self.windows[event.cursor_row]["index"])

    def action_cancel(self) -> None:
        self.dismiss(None)


class TaskDetailScreen(Screen):
    """Screen showing comprehensive task details and actions"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("s", "start_task", "Start"),
        ("a", "attach_tmux", "Attach"),
        ("p", "send_prompt", "Prompt"),
        ("P", "prompt_with_picker", "Prompt→Win"),
        ("e", "edit_in_nvim", "Edit"),
        ("t", "toggle_tmux_output", "tmux↕"),
        ("w", "switch_window", "Switch Win"),
        ("j", "scroll_down", "Down"),
        ("k", "scroll_up", "Up"),
        ("1", "send_suggestion_1", "Suggest 1"),
        ("2", "send_suggestion_2", "Suggest 2"),
        ("3", "send_suggestion_3", "Suggest 3"),
        ("4", "advance_phase", "Next Phase"),
        ("5", "regress_phase", "Prev Phase"),
        ("question_mark", "show_help", "Help"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, task_id: str):
        super().__init__()
        self.task_id = task_id
        self.task_data = None
        self.tmux_output_expanded = False  # Toggle between 10 and 100 lines
        # Prompt history navigation state
        self._prompt_history: List[str] = []
        self._history_index: int = -1  # -1 means not browsing history
        self._current_input: str = ""  # Store current input when browsing history
        # Suggested prompts for current phase
        self._suggested_prompts: List[Dict] = []
        # Multi-window tracking
        self.selected_window: int = 0  # Currently selected window index
        self._window_statuses: List[Dict] = []  # Cached window statuses
        self._prompt_target_window: Optional[int] = None  # Target window for prompt

    def action_save_session_log(self) -> None:
        """Save the tmux session output to a log file"""
        tmux_session = self.task_data.get('tmux_session') if self.task_data else None
        if not tmux_session:
            self.app.notify("No tmux session for this task", severity="warning")
            return

        filepath = save_session_log(self.task_id, tmux_session)
        if filepath:
            self.app.notify(f"Session saved: {filepath}", severity="success")
        else:
            self.app.notify("Failed to capture session", severity="error")

    def action_scroll_down(self) -> None:
        """Scroll down (vim j)"""
        container = self.query_one("#task-detail-container", ScrollableContainer)
        container.scroll_down()

    def action_scroll_up(self) -> None:
        """Scroll up (vim k)"""
        container = self.query_one("#task-detail-container", ScrollableContainer)
        container.scroll_up()

    def action_toggle_tmux_output(self) -> None:
        """Toggle tmux output between 10 and 100 lines"""
        self.tmux_output_expanded = not self.tmux_output_expanded
        line_count = 100 if self.tmux_output_expanded else 10

        # Update tmux content and collapsible state
        try:
            tmux_content = self._build_tmux_output_content()
            self.query_one("#tmux-content", Static).update(tmux_content)

            collapsible = self.query_one("#tmux-collapsible", Collapsible)
            collapsible.title = f"📺 tmux Output ({line_count} lines) [t]"
            collapsible.collapsed = False  # Expand when toggling
        except Exception:
            pass

        self.app.notify(f"tmux output: {line_count} lines", severity="information")

    def action_attach_tmux(self) -> None:
        """Attach to task's tmux session"""
        import subprocess
        import os
        from agentctl.core.tmux import session_exists

        tmux_session = self.task_data.get('tmux_session') if self.task_data else None
        if not tmux_session:
            self.app.notify("No tmux session for this task", severity="warning")
            return

        if not session_exists(tmux_session):
            self.app.notify(f"Session '{tmux_session}' not found", severity="error")
            return

        # Check if we're inside tmux already
        if os.environ.get('TMUX'):
            # Use switch-client to switch to the target session
            with self.app.suspend():
                subprocess.run(["tmux", "switch-client", "-t", tmux_session])
        else:
            # Not in tmux, use regular attach
            with self.app.suspend():
                subprocess.run(["tmux", "attach", "-t", tmux_session])

    def action_send_prompt(self) -> None:
        """Show inline prompt input bar"""
        from agentctl.core.tmux import session_exists

        tmux_session = self.task_data.get('tmux_session') if self.task_data else None
        if not tmux_session:
            self.app.notify("No tmux session for this task", severity="warning")
            return

        if not session_exists(tmux_session):
            self.app.notify(f"Session '{tmux_session}' not found", severity="error")
            return

        # Load bookmarked prompts first, then recent history
        bookmarked = prompt_store.get_bookmarked_prompts(limit=10)
        recent = prompt_store.get_recent_prompts(limit=20)

        # Combine: bookmarked first, then history (deduplicated)
        self._prompt_history = []
        seen_texts = set()
        for p in bookmarked:
            if p['text'] not in seen_texts:
                self._prompt_history.append(p['text'])
                seen_texts.add(p['text'])
        for p in recent:
            if p['text'] not in seen_texts:
                self._prompt_history.append(p['text'])
                seen_texts.add(p['text'])

        self._history_index = -1
        self._current_input = ""

        # Show the prompt bar and focus the input
        prompt_bar = self.query_one("#prompt-bar")
        prompt_bar.remove_class("prompt-bar-hidden")
        prompt_bar.add_class("prompt-bar-visible")
        prompt_input = self.query_one("#prompt-input", Input)
        prompt_input.value = ""
        prompt_input.focus()

    def _hide_prompt_bar(self) -> None:
        """Hide the inline prompt bar"""
        prompt_bar = self.query_one("#prompt-bar")
        prompt_bar.remove_class("prompt-bar-visible")
        prompt_bar.add_class("prompt-bar-hidden")
        prompt_input = self.query_one("#prompt-input", Input)
        prompt_input.value = ""
        # Reset history navigation state
        self._history_index = -1
        self._current_input = ""

    def action_prompt_with_picker(self) -> None:
        """Show window picker, then prompt input (P key)"""
        from agentctl.core.tmux import session_exists

        tmux_session = self.task_data.get('tmux_session') if self.task_data else None
        if not tmux_session:
            self.app.notify("No tmux session for this task", severity="warning")
            return

        if not session_exists(tmux_session):
            self.app.notify(f"Session '{tmux_session}' not found", severity="error")
            return

        if not self._window_statuses:
            # Refresh window statuses
            self._update_windows_display()

        if not self._window_statuses or len(self._window_statuses) < 2:
            # Only one window, just use regular prompt
            self.action_send_prompt()
            return

        def handle_window_selection(window_index: Optional[int]) -> None:
            if window_index is not None:
                self._prompt_target_window = window_index
                self.action_send_prompt()

        self.app.push_screen(WindowPickerModal(self._window_statuses), handle_window_selection)

    def _send_suggestion(self, index: int) -> None:
        """Send a suggested prompt by index (0-2)"""
        from agentctl.core.tmux import send_keys as tmux_send_keys, session_exists

        if index >= len(self._suggested_prompts):
            self.app.notify("No suggestion at that position", severity="warning")
            return

        tmux_session = self.task_data.get('tmux_session') if self.task_data else None
        if not tmux_session:
            self.app.notify("No tmux session for this task", severity="warning")
            return

        if not session_exists(tmux_session):
            self.app.notify(f"Session '{tmux_session}' not found", severity="error")
            return

        prompt = self._suggested_prompts[index]
        prompt_text = prompt['text']

        success = tmux_send_keys(tmux_session, prompt_text, enter=True)
        if success:
            phase = self.task_data.get('phase') if self.task_data else None
            prompt_store.add_to_history(prompt_text, task_id=self.task_id, phase=phase)
            preview = prompt_text[:40] + "..." if len(prompt_text) > 40 else prompt_text
            self.app.notify(f"✓ {preview}", severity="success")
        else:
            self.app.notify("Failed to send prompt", severity="error")

    def action_send_suggestion_1(self) -> None:
        """Send first suggested prompt, or cycle status if no suggestions"""
        if self._suggested_prompts:
            self._send_suggestion(0)
        else:
            self.action_cycle_status()

    def action_send_suggestion_2(self) -> None:
        """Send second suggested prompt, or cycle priority if no suggestions"""
        if len(self._suggested_prompts) >= 2:
            self._send_suggestion(1)
        else:
            self.action_cycle_priority()

    def action_send_suggestion_3(self) -> None:
        """Send third suggested prompt, or cycle category if no suggestions"""
        if len(self._suggested_prompts) >= 3:
            self._send_suggestion(2)
        else:
            self.action_cycle_category()

    def _navigate_history(self, direction: int) -> None:
        """Navigate through prompt history. direction: -1 for older, +1 for newer"""
        prompt_input = self.query_one("#prompt-input", Input)

        if not self._prompt_history:
            return

        # Save current input when starting to browse history
        if self._history_index == -1 and direction == -1:
            self._current_input = prompt_input.value

        new_index = self._history_index + direction

        if new_index < -1:
            new_index = -1
        elif new_index >= len(self._prompt_history):
            new_index = len(self._prompt_history) - 1

        self._history_index = new_index

        if self._history_index == -1:
            # Back to current input
            prompt_input.value = self._current_input
        else:
            # Show history item
            prompt_input.value = self._prompt_history[self._history_index]

        # Move cursor to end
        prompt_input.cursor_position = len(prompt_input.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter in the prompt input"""
        if event.input.id == "prompt-input" and event.value:
            tmux_session = self.task_data.get('tmux_session') if self.task_data else None
            if tmux_session:
                # Use target window if set, otherwise use selected window
                target_window = self._prompt_target_window if self._prompt_target_window is not None else self.selected_window
                success = tmux_send_keys(tmux_session, event.value, enter=True, window=target_window)
                if success:
                    # Log to prompt history with task context
                    phase = self.task_data.get('phase') if self.task_data else None
                    prompt_store.add_to_history(event.value, task_id=self.task_id, phase=phase)
                    window_name = self._window_statuses[target_window]["name"] if self._window_statuses and target_window < len(self._window_statuses) else f"Window {target_window}"
                    preview = event.value[:30] + "..." if len(event.value) > 30 else event.value
                    self.app.notify(f"✓ [{window_name}] {preview}", severity="success")
                else:
                    self.app.notify("Failed to send prompt", severity="error")
                self._prompt_target_window = None  # Reset after use
            self._hide_prompt_bar()

    def on_key(self, event) -> None:
        """Handle special keys in prompt input"""
        try:
            prompt_bar = self.query_one("#prompt-bar")
            if "prompt-bar-visible" not in prompt_bar.classes:
                return

            if event.key == "escape":
                self._hide_prompt_bar()
                event.prevent_default()
                event.stop()
            elif event.key == "up":
                # Navigate to older history
                self._navigate_history(-1)
                event.prevent_default()
                event.stop()
            elif event.key == "down":
                # Navigate to newer history
                self._navigate_history(1)
                event.prevent_default()
                event.stop()
            elif event.key == "ctrl+r":
                # Open prompt library for selection
                self._open_prompt_selector()
                event.prevent_default()
                event.stop()
        except Exception:
            pass

    def _open_prompt_selector(self) -> None:
        """Open PromptLibraryScreen for selecting a prompt"""
        def handle_selection(selected_text: Optional[str]) -> None:
            if selected_text:
                prompt_input = self.query_one("#prompt-input", Input)
                prompt_input.value = selected_text
                prompt_input.cursor_position = len(selected_text)
                prompt_input.focus()

        self.app.push_screen(PromptLibraryScreen(select_mode=True), handle_selection)

    def compose(self) -> ComposeResult:
        yield Header()
        yield ScrollableContainer(
            # Header
            Static("", id="task-header", classes="task-header"),

            # Metadata Section
            Container(
                Static("", id="meta-row-1"),
                Static("", id="meta-row-2"),
                Static("", id="meta-row-3"),
                Static("", id="meta-row-4"),
                Static("", id="meta-row-5"),
                classes="metadata-section",
            ),

            # Workflow Section
            Container(
                Static("[bold cyan]Workflow Progress[/bold cyan] [dim]([4] next / [5] prev)[/dim]"),
                Rule(line_style="heavy", classes="-workflow"),
                Static("", id="workflow-content"),
                classes="workflow-section",
            ),

            # Suggested Prompts Section
            Container(
                Static("", id="suggestions-header"),
                Static("", id="suggestions-content"),
                id="suggestions-section",
                classes="suggestions-section",
            ),

            # Agent Windows Section (multi-window tracking)
            Container(
                Static("[bold cyan]Agent Windows[/bold cyan] [dim]([w] switch)[/dim]"),
                Rule(line_style="heavy"),
                Static("", id="windows-list"),
                id="windows-section",
                classes="windows-section",
            ),

            # tmux Output Section (Collapsible)
            Container(
                Collapsible(
                    Static("", id="tmux-content", classes="tmux-output"),
                    title="📺 tmux Output",
                    collapsed=True,
                    id="tmux-collapsible",
                ),
                classes="tmux-section",
            ),

            # Task Content Section
            Container(
                Static("[bold cyan]Task Content[/bold cyan]"),
                Rule(line_style="heavy"),
                Static("", id="task-body", classes="task-markdown-content"),
                classes="content-section",
            ),

            id="task-detail-container"
        )
        yield Horizontal(
            Static("prompt> ", id="prompt-label"),
            Input(placeholder="Enter prompt (Enter=send, Esc=cancel)", id="prompt-input"),
            id="prompt-bar",
            classes="prompt-bar-hidden"
        )
        yield Footer()

    def on_mount(self) -> None:
        self.load_task_details()
        # Auto-refresh every 3 seconds for agent status updates
        self.set_interval(3, self._refresh_dynamic_content)

    def load_task_details(self) -> None:
        """Load and display comprehensive task information (initial load)"""
        self.task_data = task_store.get_task_with_details(self.task_id)

        if not self.task_data:
            self.app.notify(f"Task {self.task_id} not found", severity="error")
            self.app.pop_screen()
            return

        self._update_all_widgets()

    def _refresh_dynamic_content(self) -> None:
        """Refresh only dynamic content (tmux output, agent status) without full reload"""
        self.task_data = task_store.get_task_with_details(self.task_id)
        if not self.task_data:
            return

        # Update agent health in metadata
        tmux_session = self.task_data.get('tmux_session')
        agent_health = "[dim]No session[/dim]"
        if tmux_session:
            agent_info = get_agent_status(self.task_id, tmux_session)
            health_display = get_health_display(agent_info['health'])
            agent_health = health_display
            if agent_info.get('warnings'):
                agent_health += f" [dim]({', '.join(agent_info['warnings'])})[/dim]"

        # Update status row (includes agent health)
        status = self.task_data['agent_status']
        status_display = self._format_status(status)
        priority = self.task_data['priority']
        priority_colors = {'high': 'red', 'medium': 'yellow', 'low': 'green'}
        priority_color = priority_colors.get(priority, 'white')

        try:
            self.query_one("#meta-row-2", Static).update(
                f"[cyan][1] Status:[/cyan] {status_display}  │  [cyan][2] Priority:[/cyan] [{priority_color}]{priority.upper()}[/{priority_color}]  │  [cyan][3] Category:[/cyan] {self.task_data['category']}"
            )
            self.query_one("#meta-row-3", Static).update(
                f"[cyan]Type:[/cyan] {self.task_data['type']}  │  [cyan]Agent:[/cyan] {agent_health}"
            )

            # Update windows display
            self._update_windows_display()

            # Update tmux output
            tmux_content = self._build_tmux_output_content()
            self.query_one("#tmux-content", Static).update(tmux_content)

            # Update collapsible title with window name
            window_name = self._window_statuses[self.selected_window]["name"] if self._window_statuses else "tmux"
            line_count = 100 if self.tmux_output_expanded else 10
            collapsible = self.query_one("#tmux-collapsible", Collapsible)
            collapsible.title = f"📺 {window_name} Output ({line_count} lines) [t/w]"
        except Exception:
            pass  # Widget not ready yet

    def _update_all_widgets(self) -> None:
        """Update all widget content (called on initial load and manual refresh)"""
        if not self.task_data:
            return

        # Get agent health status
        tmux_session = self.task_data.get('tmux_session')
        agent_health = "[dim]No session[/dim]"
        if tmux_session:
            agent_info = get_agent_status(self.task_id, tmux_session)
            health_display = get_health_display(agent_info['health'])
            agent_health = health_display
            if agent_info.get('warnings'):
                agent_health += f" [dim]({', '.join(agent_info['warnings'])})[/dim]"

        # Get markdown body content
        markdown_body = self.task_data.get('_markdown_body', '')
        if markdown_body:
            markdown_body = markdown_body.strip()
        else:
            markdown_body = "[dim](no content)[/dim]"

        # Build workflow progress display
        current_phase = self.task_data.get('phase')
        workflow_display = self._build_workflow_progress(current_phase)

        # Load suggested prompts for current phase
        self._suggested_prompts = []
        suggestions_header = ""
        suggestions_content = ""
        if current_phase:
            self._suggested_prompts = prompt_store.get_workflow_prompts(current_phase)
            if self._suggested_prompts:
                suggestions_header = f"[bold cyan]Suggested for {current_phase}[/bold cyan] [dim](1-3 to send)[/dim]"
                suggestion_lines = []
                for i, prompt in enumerate(self._suggested_prompts[:3]):
                    title = prompt.get('title') or prompt['text'][:40]
                    suggestion_lines.append(f"  [yellow][{i+1}][/yellow] {title}")
                suggestions_content = "\n".join(suggestion_lines)

        # Build tmux output content
        tmux_content = self._build_tmux_output_content()

        # Status with color coding
        status = self.task_data['agent_status']
        status_display = self._format_status(status)

        # Priority with color
        priority = self.task_data['priority']
        priority_colors = {'high': 'red', 'medium': 'yellow', 'low': 'green'}
        priority_color = priority_colors.get(priority, 'white')

        # Update all widgets by ID
        try:
            self.query_one("#task-header", Static).update(
                f"📋 {self.task_id}: {self.task_data['title']}"
            )
            self.query_one("#meta-row-1", Static).update(
                f"[cyan]Project:[/cyan] {self.task_data.get('project_name', '-')}  │  [cyan]Repo:[/cyan] {self.task_data.get('repository_name') or '-'}"
            )
            self.query_one("#meta-row-2", Static).update(
                f"[cyan][1] Status:[/cyan] {status_display}  │  [cyan][2] Priority:[/cyan] [{priority_color}]{priority.upper()}[/{priority_color}]  │  [cyan][3] Category:[/cyan] {self.task_data['category']}"
            )
            self.query_one("#meta-row-3", Static).update(
                f"[cyan]Type:[/cyan] {self.task_data['type']}  │  [cyan]Agent:[/cyan] {agent_health}"
            )
            self.query_one("#meta-row-4", Static).update(
                f"[cyan]Branch:[/cyan] {self.task_data.get('git_branch') or '[dim]-[/dim]'}  │  [cyan]tmux:[/cyan] {tmux_session or '[dim]-[/dim]'}"
            )
            self.query_one("#meta-row-5", Static).update(
                f"[cyan][n] Notes:[/cyan] {self.task_data.get('notes') or '[dim](press n to add)[/dim]'}"
            )
            self.query_one("#workflow-content", Static).update(workflow_display)
            self.query_one("#suggestions-header", Static).update(suggestions_header)
            self.query_one("#suggestions-content", Static).update(suggestions_content)
            # Hide suggestions section if empty
            suggestions_section = self.query_one("#suggestions-section", Container)
            suggestions_section.display = bool(self._suggested_prompts)

            # Update windows display
            self._update_windows_display()

            self.query_one("#tmux-content", Static).update(tmux_content)
            self.query_one("#task-body", Static).update(markdown_body)

            # Update collapsible title with window name
            window_name = self._window_statuses[self.selected_window]["name"] if self._window_statuses else "tmux"
            line_count = 100 if self.tmux_output_expanded else 10
            collapsible = self.query_one("#tmux-collapsible", Collapsible)
            collapsible.title = f"📺 {window_name} Output ({line_count} lines) [t/w]"
            collapsible.collapsed = not self.tmux_output_expanded
        except Exception:
            pass  # Widgets not ready yet

    def _build_workflow_progress(self, current_phase: Optional[str]) -> str:
        """Build workflow progress display string"""
        lines = []
        for phase in task_md.VALID_PHASE:
            display_name = task_md.get_phase_display_name(phase)

            if phase == current_phase:
                # Current phase
                lines.append(f"▶ [bold green]{display_name}[/bold green] [current]")
            elif not current_phase or task_md.VALID_PHASE.index(phase) < task_md.VALID_PHASE.index(current_phase):
                # Completed phase
                lines.append(f"✓ [dim]{display_name}[/dim]")
            else:
                # Future phase
                lines.append(f"○ [dim]{display_name}[/dim]")

        return "\n".join(lines)

    def _build_tmux_output_content(self) -> str:
        """Build tmux output content string for Collapsible widget"""
        tmux_session = self.task_data.get('tmux_session')

        if not tmux_session:
            return "[dim]No tmux session for this task[/dim]"

        from agentctl.core.tmux import capture_window_pane

        # Determine how many lines to show based on toggle state
        max_lines = 100 if self.tmux_output_expanded else 10

        # Capture from selected window
        recent_output = capture_window_pane(tmux_session, window=self.selected_window, lines=200)

        if not recent_output:
            return "[dim](session exists but no output captured)[/dim]"

        # Split into lines and get the last N lines (don't filter empty lines)
        all_lines = recent_output.split('\n')
        output_lines = all_lines[-max_lines:] if len(all_lines) > max_lines else all_lines

        if not output_lines or (len(output_lines) == 1 and not output_lines[0].strip()):
            return "[dim](no output)[/dim]"

        # Truncate long lines to prevent layout issues
        formatted_lines = []
        for line in output_lines:
            # Don't skip empty lines, but truncate long ones
            if len(line) > 120:
                line = line[:117] + "..."
            formatted_lines.append(line)

        return "\n".join(formatted_lines)

    def _format_status(self, status: str) -> str:
        """Format status with icon"""
        status_icons = {
            "queued": "⚪ QUEUED",
            "running": "🟢 RUNNING",
            "blocked": "🟡 BLOCKED",
            "completed": "✅ COMPLETED",
            "failed": "🔴 FAILED"
        }
        return status_icons.get(status, status.upper())

    def _format_timestamp(self, timestamp) -> str:
        """Format timestamp for display"""
        if not timestamp:
            return "Not set"

        from datetime import datetime
        try:
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return "Invalid"

    def _update_windows_display(self) -> None:
        """Update the windows list display"""
        tmux_session = self.task_data.get('tmux_session') if self.task_data else None

        if not tmux_session:
            try:
                self.query_one("#windows-section", Container).display = False
            except Exception:
                pass
            return

        # Get window statuses
        self._window_statuses = get_all_window_statuses(tmux_session, self.task_id)

        if not self._window_statuses:
            try:
                self.query_one("#windows-section", Container).display = False
            except Exception:
                pass
            return

        # Show the section
        try:
            self.query_one("#windows-section", Container).display = True
        except Exception:
            pass

        # Build display lines
        lines = []
        for w in self._window_statuses:
            marker = "▶ " if w["index"] == self.selected_window else "  "
            lines.append(f"{marker}{w['name']} ({w['index']})  {w['icon']} {w['summary']}")

        try:
            self.query_one("#windows-list", Static).update("\n".join(lines))
        except Exception:
            pass

    def action_switch_window(self) -> None:
        """Cycle through windows (w key)"""
        if not self._window_statuses:
            self.app.notify("No windows available", severity="warning")
            return

        # Cycle to next window
        self.selected_window = (self.selected_window + 1) % len(self._window_statuses)

        # Update displays
        self._update_windows_display()

        # Update tmux output for new window
        try:
            tmux_content = self._build_tmux_output_content()
            self.query_one("#tmux-content", Static).update(tmux_content)

            # Update collapsible title to show current window
            window_name = self._window_statuses[self.selected_window]["name"] if self._window_statuses else "?"
            line_count = 100 if self.tmux_output_expanded else 10
            collapsible = self.query_one("#tmux-collapsible", Collapsible)
            collapsible.title = f"📺 {window_name} Output ({line_count} lines) [t/w]"
        except Exception:
            pass

        self.app.notify(f"Switched to {self._window_statuses[self.selected_window]['name']}", severity="information")

    def action_go_back(self) -> None:
        """Go back to previous screen"""
        self.app.pop_screen()

    def action_edit_in_nvim(self) -> None:
        """Open nvim to edit task markdown file"""
        # Get task file path
        project = database.get_project(self.task_data['project_id'])
        if project and project.get('tasks_path'):
            from pathlib import Path
            task_file = Path(project['tasks_path']) / f"{self.task_id}.md"

            if task_file.exists():
                # Define callback to reload after nvim closes
                def after_nvim():
                    # Reload the task details to show updated data
                    self.load_task_details()
                    self.app.notify(f"Task {self.task_id} updated", severity="success")

                # Suspend TUI and open nvim
                import subprocess

                # Store the callback for after resume
                self._after_resume_callback = after_nvim

                # Exit TUI, run nvim, then re-enter
                with self.app.suspend():
                    subprocess.run(['nvim', str(task_file)])

                # Execute callback
                if hasattr(self, '_after_resume_callback'):
                    self._after_resume_callback()
                    delattr(self, '_after_resume_callback')
            else:
                self.app.notify(f"Task file not found: {task_file}", severity="error")
        else:
            self.app.notify("Task has no tasks_path configured", severity="error")

    def action_start_task(self) -> None:
        """Open start modal to begin work on task"""
        if self.task_data['agent_status'] in ['running', 'completed']:
            self.app.notify(f"Task is already {self.task_data['agent_status']}", severity="warning")
            return

        def check_result(result):
            if result:
                self.load_task_details()

        self.app.push_screen(StartTaskModal(self.task_id), check_result)

    def action_refresh_task_file(self) -> None:
        """Re-copy source task file to TASK.md in working directory"""
        # Determine working directory
        if self.task_data.get('worktree_path'):
            work_dir = Path(self.task_data['worktree_path']).expanduser()
        elif self.task_data.get('repository_path'):
            work_dir = Path(self.task_data['repository_path']).expanduser()
        else:
            self.app.notify("No working directory found for task", severity="error")
            return

        if not work_dir.exists():
            self.app.notify(f"Working directory does not exist: {work_dir}", severity="error")
            return

        # Copy the task file
        result = copy_task_file_to_workdir(self.task_id, work_dir)

        if result:
            self.app.notify(f"Refreshed TASK.md in {work_dir}", severity="success")
        else:
            self.app.notify("Failed to copy task file", severity="error")

    def action_complete_task(self) -> None:
        """Mark task as completed"""
        if self.task_data['agent_status'] == 'completed':
            self.app.notify("Task is already completed", severity="information")
            return

        from datetime import datetime

        # Update task status
        updates = {
            'agent_status': 'completed',
            'completed_at': datetime.now().isoformat()
        }
        success = update_task(self.task_id, updates)
        if not success:
            self.app.notify("Failed to update task", severity="error")
            return

        database.add_event(self.task_id, "completed")
        self.app.notify(f"Task {self.task_id} marked as completed", severity="success")
        self.load_task_details()

    def action_delete_task(self) -> None:
        """Delete this task with confirmation"""
        task_title = self.task_data.get('title', 'Unknown')

        def handle_delete(confirmed: bool) -> None:
            if confirmed:
                # Delete task
                success = delete_task(self.task_id)
                if not success:
                    self.app.notify("Failed to delete task", severity="error")
                    return

                database.add_event(self.task_id, "deleted")
                self.app.notify(f"Task {self.task_id} deleted", severity="warning")
                self.app.pop_screen()

        self.app.push_screen(ConfirmDeleteModal(self.task_id, task_title), handle_delete)

    def action_cycle_status(self) -> None:
        """Cycle through agent_status options"""
        statuses = ['queued', 'running', 'blocked', 'completed', 'failed']
        current = self.task_data['agent_status']
        current_idx = statuses.index(current) if current in statuses else 0
        next_status = statuses[(current_idx + 1) % len(statuses)]

        self._update_field('agent_status', next_status)

    def action_cycle_priority(self) -> None:
        """Cycle through priority options"""
        priorities = ['low', 'medium', 'high']
        current = self.task_data['priority']
        current_idx = priorities.index(current) if current in priorities else 1
        next_priority = priorities[(current_idx + 1) % len(priorities)]

        self._update_field('priority', next_priority)

    def action_cycle_category(self) -> None:
        """Cycle through category options"""
        categories = ['FEATURE', 'BUG', 'REFACTOR', 'DOCS', 'TEST', 'CHORE']
        current = self.task_data['category']
        current_idx = categories.index(current) if current in categories else 0
        next_category = categories[(current_idx + 1) % len(categories)]

        self._update_field('category', next_category)

    def action_advance_phase(self) -> None:
        """Advance to next phase in workflow"""
        current_phase = self.task_data.get('phase')
        next_phase = task_md.get_next_phase(current_phase)

        if not next_phase:
            self.app.notify("Already at final phase", severity="warning")
            return

        self._update_field('phase', next_phase)
        display_name = task_md.get_phase_display_name(next_phase)
        self.app.notify(f"Advanced to: {display_name}", severity="success")

    def action_regress_phase(self) -> None:
        """Go back to previous phase in workflow"""
        current_phase = self.task_data.get('phase')
        prev_phase = task_md.get_previous_phase(current_phase)

        if not prev_phase:
            self.app.notify("Already at first phase", severity="warning")
            return

        self._update_field('phase', prev_phase)
        display_name = task_md.get_phase_display_name(prev_phase)
        self.app.notify(f"Regressed to: {display_name}", severity="success")

    def _update_field(self, field: str, value: str) -> None:
        """Update a single field in the task"""
        success = update_task(self.task_id, {field: value})
        if not success:
            self.app.notify(f"Failed to update {field}", severity="error")
            return

        self.app.notify(f"{field.capitalize()} changed to: {value}", severity="success")
        self.load_task_details()

    def action_edit_notes(self) -> None:
        """Edit notes for this task"""
        current_notes = self.task_data.get('notes', '')

        def handle_notes(new_notes) -> None:
            if new_notes is None:
                # User cancelled
                return

            # Update notes (empty string clears them)
            success = update_task(self.task_id, {'notes': new_notes if new_notes else None})
            if not success:
                self.app.notify("Failed to update notes", severity="error")
                return

            if new_notes:
                self.app.notify("Notes updated", severity="success")
            else:
                self.app.notify("Notes cleared", severity="information")
            self.load_task_details()

        self.app.push_screen(EditNotesModal(self.task_id, current_notes), handle_notes)

    def action_view_prompts(self) -> None:
        """View user prompts for this task's session"""
        # First check if we have prompts in the database for this task
        prompts = database.get_user_prompts(task_id=self.task_id, limit=1)

        if prompts:
            # We have stored prompts, show them
            self.app.push_screen(UserPromptsScreen(task_id=self.task_id))
        else:
            # No stored prompts - try to capture and parse the current session
            tmux_session = self.task_data.get('tmux_session') if self.task_data else None
            if not tmux_session:
                self.app.notify("No session data. Use 'l' to capture session first.", severity="warning")
                return

            # Capture session and parse it
            filepath = save_session_log(self.task_id, tmux_session)
            if filepath:
                # Now show the prompts
                self.app.push_screen(UserPromptsScreen(task_id=self.task_id))
            else:
                self.app.notify("Failed to capture session", severity="error")

    def action_show_help(self) -> None:
        """Show help overlay"""
        self.app.push_screen(HelpOverlay("TaskDetail"))


class ProjectListScreen(Screen):
    """Screen showing all projects"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("n", "new_project", "New"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("question_mark", "show_help", "Help"),
        ("q", "quit", "Quit"),
    ]

    def action_cursor_down(self) -> None:
        """Move cursor down (vim j)"""
        table = self.query_one("#projects-table", DataTable)
        table.action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up (vim k)"""
        table = self.query_one("#projects-table", DataTable)
        table.action_cursor_up()

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


class UserPromptsScreen(Screen):
    """Screen for browsing user prompts from sessions"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("question_mark", "show_help", "Help"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, task_id: Optional[str] = None):
        super().__init__()
        self.task_id = task_id
        self.prompts_data: List[Dict] = []
        self.selected_index = 0

    def compose(self) -> ComposeResult:
        title = f"💬 USER PROMPTS - {self.task_id}" if self.task_id else "💬 USER PROMPTS (All Tasks)"
        yield Header()
        yield Container(
            Static(title, classes="screen-title"),
            Horizontal(
                Container(
                    DataTable(id="prompts-table"),
                    id="prompts-list-container"
                ),
                Container(
                    Static("[bold]Prompt Detail[/bold]", id="prompt-detail-title"),
                    ScrollableContainer(
                        Static("Select a prompt to view details", id="prompt-detail-content"),
                        id="prompt-detail-scroll"
                    ),
                    id="prompt-detail-container"
                ),
                id="prompts-split-view"
            ),
            id="prompts-screen-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        self.load_prompts()

    def load_prompts(self) -> None:
        """Load prompts from database"""
        self.prompts_data = database.get_user_prompts(task_id=self.task_id, limit=100)

        table = self.query_one("#prompts-table", DataTable)
        table.clear()

        if len(table.columns) == 0:
            table.add_columns("Type", "Task", "Prompt")
            table.cursor_type = "row"

        for prompt in self.prompts_data:
            type_icon = {
                'message': '💬',
                'command': '⚡',
                'file_reference': '📄',
                'interrupt': '⏹️'
            }.get(prompt['prompt_type'], '•')

            # Truncate for table display
            prompt_preview = prompt['prompt'][:50] + "..." if len(prompt['prompt']) > 50 else prompt['prompt']

            table.add_row(
                f"{type_icon} {prompt['prompt_type'][:7]}",
                prompt['task_id'][:12],
                prompt_preview
            )

        # Show first prompt detail
        if self.prompts_data:
            self._show_prompt_detail(0)

    def _show_prompt_detail(self, index: int) -> None:
        """Show full prompt detail"""
        if not self.prompts_data or index >= len(self.prompts_data):
            return

        prompt = self.prompts_data[index]
        detail = self.query_one("#prompt-detail-content", Static)

        type_icon = {
            'message': '💬 Message',
            'command': '⚡ Command',
            'file_reference': '📄 File Reference',
            'interrupt': '⏹️ Interrupt'
        }.get(prompt['prompt_type'], prompt['prompt_type'])

        detail_text = f"""[bold cyan]Type:[/bold cyan] {type_icon}
[bold cyan]Task:[/bold cyan] {prompt['task_id']}
[bold cyan]Order:[/bold cyan] #{prompt['prompt_order']}

[bold cyan]Full Prompt:[/bold cyan]
{prompt['prompt']}
"""
        detail.update(detail_text)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Update detail when cursor moves"""
        if event.data_table.id == "prompts-table" and event.cursor_row is not None:
            self._show_prompt_detail(event.cursor_row)
            self.selected_index = event.cursor_row

    def action_cursor_down(self) -> None:
        """Move cursor down"""
        table = self.query_one("#prompts-table", DataTable)
        table.action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up"""
        table = self.query_one("#prompts-table", DataTable)
        table.action_cursor_up()

    def action_go_back(self) -> None:
        """Go back"""
        self.app.pop_screen()

    def action_view_prompt(self) -> None:
        """View full prompt (already shown in detail pane)"""
        pass  # Detail is already shown

    def action_show_help(self) -> None:
        """Show help overlay"""
        self.app.push_screen(HelpOverlay("Prompts"))


class AnalyticsScreen(Screen):
    """Screen showing session analytics and metrics"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("r", "refresh", "Refresh"),
        ("j", "scroll_down", "Down"),
        ("k", "scroll_up", "Up"),
        ("question_mark", "show_help", "Help"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield ScrollableContainer(
            Static("📊 SESSION ANALYTICS", classes="screen-title"),
            Container(id="analytics-content"),
            id="analytics-scroll"
        )
        yield Footer()

    def on_mount(self) -> None:
        self.load_analytics()

    def action_scroll_down(self) -> None:
        """Scroll down (vim j)"""
        scroll = self.query_one("#analytics-scroll", ScrollableContainer)
        scroll.scroll_down()

    def action_scroll_up(self) -> None:
        """Scroll up (vim k)"""
        scroll = self.query_one("#analytics-scroll", ScrollableContainer)
        scroll.scroll_up()

    def load_analytics(self) -> None:
        """Load and display analytics data"""
        container = self.query_one("#analytics-content", Container)
        container.remove_children()

        # Get analytics summary
        summary = database.get_analytics_summary()

        if summary['total_sessions'] == 0:
            container.mount(
                Static("[dim]No session data yet. Use 'l' in Agents view to capture sessions.[/dim]")
            )
            return

        # Summary section
        summary_text = f"""[bold cyan]Overall Summary[/bold cyan]
Sessions Captured: {summary['total_sessions']}
Total Tool Calls: {summary['total_tool_calls']}
Total File Operations: {summary['total_file_operations']}
Total Commands: {summary['total_commands']}
Total Errors: {summary['total_errors']}
"""
        container.mount(Static(summary_text, classes="analytics-section"))

        # Top tools section
        if summary['top_tools']:
            tools_lines = ["[bold cyan]Top Tools Used[/bold cyan]"]
            for tool in summary['top_tools']:
                bar_len = min(int(tool['total'] / 5), 30)  # Scale bar
                bar = "█" * bar_len
                tools_lines.append(f"  {tool['tool_name']}: {tool['total']} {bar}")
            container.mount(Static("\n".join(tools_lines), classes="analytics-section"))

        # Get detailed tool stats
        tool_stats = database.get_tool_usage_stats()
        if tool_stats:
            detailed_lines = ["[bold cyan]All Tool Usage[/bold cyan]"]
            for stat in tool_stats[:15]:  # Top 15
                detailed_lines.append(f"  {stat['tool_name']}: {stat['total_calls']}")
            container.mount(Static("\n".join(detailed_lines), classes="analytics-section"))

        # File activity
        file_stats = database.get_file_activity_stats(limit=10)
        if file_stats:
            file_lines = ["[bold cyan]Most Accessed Files[/bold cyan]"]
            for stat in file_stats:
                # Truncate long paths
                path = stat['file_path']
                if len(path) > 50:
                    path = "..." + path[-47:]
                ops = f"R:{stat['reads']} W:{stat['writes']} E:{stat['edits']}"
                file_lines.append(f"  {path}")
                file_lines.append(f"    {ops} (total: {stat['total_operations']})")
            container.mount(Static("\n".join(file_lines), classes="analytics-section"))

        # Error stats
        error_stats = database.get_error_stats()
        if error_stats:
            error_lines = ["[bold cyan]Errors by Type[/bold cyan]"]
            for stat in error_stats:
                error_lines.append(f"  {stat['error_type']}: {stat['count']}")
            container.mount(Static("\n".join(error_lines), classes="analytics-section"))

        # Recent errors
        if summary['recent_errors']:
            recent_lines = ["[bold red]Recent Errors[/bold red]"]
            for err in summary['recent_errors']:
                msg = err['error_message'][:60] + "..." if len(err['error_message']) > 60 else err['error_message']
                recent_lines.append(f"  [{err['task_id']}] {err['error_type']}: {msg}")
            container.mount(Static("\n".join(recent_lines), classes="analytics-section"))

        # User prompts section
        if summary.get('total_user_prompts', 0) > 0:
            prompts_summary = f"""[bold cyan]User Prompts[/bold cyan]
Total Prompts: {summary['total_user_prompts']}
  Messages: {summary.get('prompt_messages', 0)}
  Commands: {summary.get('prompt_commands', 0)}
  File Refs: {summary.get('prompt_file_refs', 0)}
"""
            container.mount(Static(prompts_summary, classes="analytics-section"))

            # Recent prompts
            if summary.get('recent_prompts'):
                prompt_lines = ["[bold cyan]Recent User Messages[/bold cyan]"]
                for p in summary['recent_prompts']:
                    prompt_text = p['prompt'][:70] + "..." if len(p['prompt']) > 70 else p['prompt']
                    prompt_lines.append(f"  [{p['task_id']}] {prompt_text}")
                container.mount(Static("\n".join(prompt_lines), classes="analytics-section"))

    def action_go_back(self) -> None:
        """Go back to main dashboard"""
        self.app.pop_screen()

    def action_refresh(self) -> None:
        """Refresh analytics data"""
        self.load_analytics()
        self.app.notify("Analytics refreshed", severity="information")

    def action_view_prompts(self) -> None:
        """Open user prompts browser"""
        self.app.push_screen(UserPromptsScreen())

    def action_show_help(self) -> None:
        """Show help overlay"""
        self.app.push_screen(HelpOverlay("Analytics"))


class AgentDashboard(App):
    """Main TUI dashboard application for agentctl"""

    CSS = """
    Screen {
        background: $surface;
    }

    .widget-title {
        background: $boost;
        color: $text;
        padding: 0;
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

    /* Modal styles - compact for mobile */
    #create-project-modal, #create-repo-modal, #edit-project-modal, #edit-repo-modal, #create-task-modal, #edit-task-modal, #start-task-modal, #send-prompt-modal {
        align: center middle;
        width: 60;
        height: auto;
        border: solid $accent;
        background: $surface;
        padding: 0 1;
    }

    /* Help overlay styles */
    #help-overlay {
        align: center middle;
        width: 70;
        max-height: 90%;
        border: thick $accent;
        background: $surface;
        padding: 0;
    }

    #help-title {
        text-align: center;
        text-style: bold;
        background: $accent;
        color: $text;
        padding: 1;
    }

    #help-scroll {
        height: 1fr;
        padding: 0 2;
        background: $surface;
    }

    #help-content {
        padding: 1 0;
    }

    #help-footer {
        text-align: center;
        background: $boost;
        color: $text-muted;
        padding: 1;
        text-style: italic;
    }

    Select {
        margin: 0;
    }

    #modal-title {
        text-align: center;
        text-style: bold;
        padding: 0;
        color: $accent;
    }

    Input {
        margin: 0;
    }

    .button-row {
        align: center middle;
        margin-top: 0;
    }

    Button {
        margin: 0 1;
    }

    /* Screen styles - compact for mobile */
    .screen-title {
        text-align: center;
        text-style: bold;
        padding: 0;
        background: $boost;
        color: $text;
    }

    #projects-container, #project-detail-container, #tasks-container {
        height: 100%;
    }

    #projects-table {
        height: 1fr;
    }

    #repos-section, #tasks-section {
        border: solid $accent;
        margin: 0;
        height: 1fr;
    }

    /* Task detail styles - compact for mobile */
    #task-detail-container {
        height: 100%;
        overflow-y: auto;
    }

    #task-detail-content {
        height: auto;
        padding: 0 1;
    }

    #task-detail-content > Static {
        height: auto;
    }

    #task-detail-content > Container {
        height: auto;
    }

    .detail-section {
        border: solid $accent;
        margin: 0;
        padding: 0;
    }

    .detail-row {
        padding: 0;
        margin: 0;
    }

    /* Agent cards for monitoring screen */
    #agents-monitor-scroll {
        height: 100%;
        overflow-y: auto;
    }

    #agents-cards-container {
        height: auto;
        padding: 0 1;
    }

    .agent-card {
        border: solid $accent;
        margin: 1 0;
        padding: 0 1;
        height: auto;
        max-height: 14;
    }

    .agent-card-selected {
        border: solid $success;
        background: $boost;
    }

    .agent-card-header {
        text-style: bold;
        padding: 0;
        height: 1;
    }

    .agent-card-content {
        height: auto;
        max-height: 11;
    }

    .agent-card-left {
        width: 1fr;
        height: auto;
    }

    .agent-card-middle {
        width: 20;
        height: auto;
        padding-left: 1;
        border-left: solid $primary-darken-2;
    }

    .agent-card-right {
        width: 35;
        height: auto;
        padding-left: 1;
        border-left: solid $primary-darken-2;
    }

    .agent-card-output {
        color: $text-muted;
        height: auto;
        margin-left: 2;
    }

    .agent-card-workflow {
        color: $text;
        height: auto;
    }

    .agent-card-metadata {
        color: $text;
        height: auto;
    }

    /* Analytics screen styles */
    #analytics-scroll {
        height: 100%;
        overflow-y: auto;
    }

    #analytics-content {
        height: auto;
        padding: 0 1;
    }

    .analytics-section {
        margin: 1 0;
        padding: 0;
    }

    /* Inline prompt bar styles */
    #prompt-bar {
        dock: bottom;
        height: auto;
        background: $boost;
        border-top: solid $accent;
        padding: 0 1;
    }

    #prompt-bar.prompt-bar-hidden {
        display: none;
    }

    #prompt-bar.prompt-bar-visible {
        display: block;
    }

    #prompt-label {
        color: $success;
        text-style: bold;
        width: auto;
    }

    #prompt-bar Input {
        width: 1fr;
        border: none;
        background: transparent;
    }

    #prompt-bar Horizontal {
        height: auto;
    }

    /* User prompts screen styles */
    #prompts-screen-container {
        height: 100%;
    }

    #prompts-split-view {
        height: 1fr;
    }

    #prompts-list-container {
        width: 1fr;
        height: 100%;
        border: solid $accent;
    }

    #prompts-table {
        height: 100%;
    }

    #prompt-detail-container {
        width: 1fr;
        height: 100%;
        border: solid $accent;
        padding: 0 1;
    }

    #prompt-detail-scroll {
        height: 1fr;
    }

    #prompt-detail-content {
        padding: 1;
    }

    #prompt-detail-title {
        text-style: bold;
        background: $boost;
        padding: 0 1;
    }

    /* Task Detail Screen - Section styling (shrink-to-fit) */
    .task-header {
        background: $primary;
        color: $text;
        text-style: bold;
        padding: 0 1;
        text-align: center;
        height: auto;
    }

    .metadata-section {
        border: solid $accent;
        border-title-color: $accent;
        border-title-style: bold;
        margin-bottom: 0;
        padding: 0 1;
        height: auto;
    }

    .workflow-section {
        border: solid $success;
        border-title-color: $success;
        border-title-style: bold;
        margin-bottom: 0;
        padding: 0 1;
        height: auto;
    }

    .tmux-section {
        border: solid $warning;
        border-title-color: $warning;
        border-title-style: bold;
        margin-bottom: 0;
        padding: 0;
        height: auto;
    }

    .tmux-section Collapsible {
        padding: 0;
        height: auto;
    }

    .tmux-section CollapsibleTitle {
        background: $warning 20%;
        color: $text;
        padding: 0 1;
    }

    .tmux-output {
        padding: 0 1;
        color: $text-muted;
        background: $surface-darken-1;
        height: auto;
    }

    .content-section {
        border: solid $primary;
        border-title-color: $primary;
        border-title-style: bold;
        margin: 0;
        padding: 0 1;
        height: auto;
    }

    .section-label {
        color: $text-muted;
    }

    .section-value {
        color: $text;
    }

    Rule {
        margin: 0;
        color: $primary-darken-2;
        height: 1;
    }

    Rule.-workflow {
        color: $success;
    }

    Rule.-tmux {
        color: $warning;
    }
    """

    BINDINGS = [
        ("p", "manage_projects", "Projects"),
        ("t", "manage_tasks", "Tasks"),
        ("a", "view_active_agents", "Active Agents"),
        ("u", "view_prompts", "Prompts"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("question_mark", "show_help", "Help"),
        ("q", "quit", "Quit"),
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
        agents = task_store.get_active_agents()
        queued = task_store.get_queued_tasks()
        self.notify(f"Active: {len(agents)} | Queued: {len(queued)}", title="Status")

    def action_manage_projects(self) -> None:
        """Open projects management screen"""
        self.push_screen(ProjectListScreen())

    def action_manage_tasks(self) -> None:
        """Open tasks management screen"""
        self.push_screen(TaskManagementScreen())

    def action_view_active_agents(self) -> None:
        """Open tasks screen filtered to active agents"""
        screen = TaskManagementScreen()
        screen.filter_mode = "active_agents"
        self.push_screen(screen)

    def action_view_analytics(self) -> None:
        """Open analytics screen"""
        self.push_screen(AnalyticsScreen())

    def action_view_prompts(self) -> None:
        """Open prompt library screen"""
        self.push_screen(PromptLibraryScreen())

    def action_cursor_down(self) -> None:
        """Move cursor down in agents table (vim j)"""
        try:
            table = self.query_one("#agents-table", DataTable)
            table.action_cursor_down()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        """Move cursor up in agents table (vim k)"""
        try:
            table = self.query_one("#agents-table", DataTable)
            table.action_cursor_up()
        except Exception:
            pass

    def action_select_agent(self) -> None:
        """Open task detail for selected agent"""
        try:
            table = self.query_one("#agents-table", DataTable)
            if table.row_count > 0 and table.cursor_row is not None:
                row = table.get_row_at(table.cursor_row)
                if row:
                    task_id = str(row[0])
                    self.push_screen(TaskDetailScreen(task_id))
        except Exception:
            pass

    def action_show_help(self) -> None:
        """Show help overlay"""
        self.push_screen(HelpOverlay("Dashboard"))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection - navigate to task detail view"""
        table_id = event.data_table.id
        row = event.data_table.get_row_at(event.cursor_row)
        if not row:
            return

        if table_id == "agents-table":
            # Task ID is in column 0
            task_id = str(row[0])
            self.push_screen(TaskDetailScreen(task_id))
        elif table_id == "queue-table":
            # Task ID is in column 1 (column 0 is row number)
            task_id = str(row[1])
            self.push_screen(TaskDetailScreen(task_id))


def run_dashboard(open_agents: bool = False):
    """Run the dashboard application

    Args:
        open_agents: If True, open directly to tasks screen with active agents filter
    """
    app = AgentDashboard()
    if open_agents:
        screen = TaskManagementScreen()
        screen.filter_mode = "active_agents"
        app.push_screen(screen)
    app.run()
