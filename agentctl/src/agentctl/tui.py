"""Textual TUI Dashboard for agentctl"""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer, Center
from textual.widgets import Header, Footer, Static, DataTable, Log, Button, Input, Label, Select
from textual.reactive import reactive
from textual.screen import Screen, ModalScreen
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path

from agentctl.core import database, task_md
from agentctl.core import task_store
from agentctl.core.task import create_task, update_task, delete_task, copy_task_file_to_workdir
from agentctl.core.agent_monitor import (
    get_agent_status, get_all_agent_statuses, get_health_display, HEALTH_ICONS,
    check_and_notify_state_changes, save_session_log
)


class AgentStatusWidget(Static):
    """Widget showing active agents with real-time updates"""

    def compose(self) -> ComposeResult:
        yield Static("🤖 ACTIVE AGENTS", classes="widget-title")
        yield DataTable(id="agents-table")

    def on_mount(self) -> None:
        table = self.query_one("#agents-table", DataTable)
        table.add_columns("Task ID", "Health", "Status", "Output Preview")
        table.cursor_type = "row"
        self.update_agents()
        self.set_interval(3, self.update_agents)

    def update_agents(self) -> None:
        """Update agent list with real-time health from tmux monitoring"""
        # Get real-time agent health from tmux sessions
        agent_statuses = get_all_agent_statuses()

        table = self.query_one("#agents-table", DataTable)
        table.clear()

        if not agent_statuses:
            # Fall back to task_store for tasks without active tmux sessions
            agents = task_store.get_active_agents()
            for agent in agents:
                status_icon = {
                    "running": "🟢",
                    "blocked": "🟡",
                    "failed": "🔴",
                    "paused": "⏸️"
                }.get(agent['agent_status'], "⚪")

                table.add_row(
                    agent['task_id'],
                    "⚪ NO SESSION",
                    f"{status_icon} {agent['agent_status'].upper()}",
                    "(no tmux session)"
                )
            return

        for agent in agent_statuses:
            health = agent.get('health', 'unknown')
            health_icon = HEALTH_ICONS.get(health, "⚪")

            # Task status icon
            task_status = agent.get('task_agent_status', 'unknown')
            status_icon = {
                "running": "🟢",
                "blocked": "🟡",
                "failed": "🔴",
                "paused": "⏸️"
            }.get(task_status, "⚪")

            # Get output preview - last non-empty line, truncated
            output_preview = agent.get('last_output_preview', '')
            if not output_preview:
                recent = agent.get('recent_output', [])
                non_empty = [line.strip() for line in recent if line.strip()]
                output_preview = non_empty[-1] if non_empty else "(no output)"
            if len(output_preview) > 50:
                output_preview = output_preview[:47] + "..."

            table.add_row(
                agent['task_id'],
                f"{health_icon} {health.upper()}",
                f"{status_icon} {task_status.upper()}",
                output_preview
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
            Input(placeholder="Task ID (e.g., RRA-API-0042)", id="task-id"),
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

            if not task_id or not title or not project_id:
                self.app.notify("Task ID, Title, and Project are required", severity="error")
                return

            try:
                # Handle blank repository selection
                final_repo_id = None
                if repo_id and repo_id != Select.BLANK:
                    final_repo_id = repo_id

                # Check if project uses markdown tasks
                project = database.get_project(project_id)
                if project and project.get('tasks_path'):
                    # Create markdown task (task_id will be auto-generated)
                    actual_task_id = create_task(
                        project_id=project_id,
                        category=category,
                        title=title.strip(),
                        description=description.strip() if description else None,
                        repository_id=final_repo_id,
                        task_type=task_type.strip() or "feature",
                        priority=priority
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
  s          View status
  p          Manage projects
  t          Manage tasks
  a          Monitor agents
  y          View analytics
""",
            "TaskDetail": """[bold cyan]TASK ACTIONS[/bold cyan]
  s          Start task (create worktree/tmux)
  c          Complete task
  d          Delete task

[bold cyan]TASK PROPERTIES[/bold cyan]
  1          Cycle status
  2          Cycle priority
  3          Cycle category
  4          Advance to next phase
  5          Go to previous phase

[bold cyan]AGENT INTERACTION[/bold cyan]
  a          Attach to tmux session
  g          Open session in Ghostty
  l          Save session log
  p          View user prompts

[bold cyan]EDITING[/bold cyan]
  e          Edit task file in nvim
  n          Edit task notes
  f          Refresh TASK.md from file
""",
            "TaskManagement": """[bold cyan]TASK MANAGEMENT[/bold cyan]
  n          Create new task
  e          Edit selected task
  d          Delete selected task
  enter      View task details
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
            "AgentsMonitor": """[bold cyan]AGENT MONITORING[/bold cyan]
  a          Attach to tmux session
  g          Open session in Ghostty
  l          Save session log
  p          View user prompts
  enter      View task details
""",
            "Analytics": """[bold cyan]ANALYTICS[/bold cyan]
  p          View all user prompts
  r          Refresh analytics
""",
            "Prompts": """[bold cyan]PROMPTS BROWSER[/bold cyan]
  enter      View prompt details
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
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("question_mark", "show_help", "Help"),
        ("q", "quit", "Quit"),
    ]

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
            Static("📋 TASK MANAGEMENT", classes="screen-title"),
            DataTable(id="tasks-table"),
            id="tasks-container"
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
        tasks = task_store.list_all_tasks()

        table = self.query_one("#tasks-table", DataTable)

        # Save current cursor position before clearing
        current_row = table.cursor_row if table.row_count > 0 else 0

        table.clear()
        # Only add columns on first load
        if len(table.columns) == 0:
            # Full columns - use h/l to scroll horizontally
            table.add_columns(
                "ID", "Title", "Status", "Pri", "Cat", "Type",
                "Phase", "Project", "Agent", "Branch", "tmux", "Notes"
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

            # Agent health indicator
            tmux_session = task.get('tmux_session')
            if tmux_session:
                agent_status = get_agent_status(task['task_id'], tmux_session)
                agent_display = f"{agent_status.get('icon', '?')} {agent_status.get('health', 'unknown')}"
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
                task.get('title', '-')[:35],
                status_display,
                priority_display,
                category,
                task_type,
                phase_display,
                project,
                agent_display,
                branch,
                tmux_display,
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

    def action_show_help(self) -> None:
        """Show help overlay"""
        self.app.push_screen(HelpOverlay("TaskManagement"))


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


class TaskDetailScreen(Screen):
    """Screen showing comprehensive task details and actions"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("s", "start_task", "Start"),
        ("a", "attach_tmux", "Attach"),
        ("e", "edit_in_nvim", "Edit"),
        ("j", "scroll_down", "Down"),
        ("k", "scroll_up", "Up"),
        ("question_mark", "show_help", "Help"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, task_id: str):
        super().__init__()
        self.task_id = task_id
        self.task_data = None

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
        container = self.query_one("#task-detail-container", Container)
        container.scroll_down()

    def action_scroll_up(self) -> None:
        """Scroll up (vim k)"""
        container = self.query_one("#task-detail-container", Container)
        container.scroll_up()

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

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Container(id="task-detail-content"),
            id="task-detail-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        self.load_task_details()
        # Auto-refresh every 2 seconds for agent status updates
        self.set_interval(2, self.load_task_details)

    def load_task_details(self) -> None:
        """Load and display comprehensive task information"""
        self.task_data = task_store.get_task_with_details(self.task_id)

        if not self.task_data:
            self.app.notify(f"Task {self.task_id} not found", severity="error")
            self.app.pop_screen()
            return

        container = self.query_one("#task-detail-content", Container)

        # Remove all existing children to avoid duplicate IDs
        container.remove_children()

        # Build compact detail view for mobile
        desc = self.task_data.get('description') or '-'
        desc_short = desc[:50] + '...' if len(desc) > 50 else desc

        # Get agent health status if tmux session exists
        agent_status_line = "Agent: No tmux session"
        tmux_session = self.task_data.get('tmux_session')
        if tmux_session:
            agent_info = get_agent_status(self.task_id, tmux_session)
            health_display = get_health_display(agent_info['health'])
            agent_status_line = f"Agent: {health_display}"
            if agent_info.get('warnings'):
                agent_status_line += f" - {', '.join(agent_info['warnings'])}"
            if agent_info.get('last_output_preview'):
                agent_status_line += f"\nOutput: {agent_info['last_output_preview']}"

        # Get markdown body content
        markdown_body = self.task_data.get('_markdown_body', '')
        if markdown_body:
            # Clean up and format for display
            markdown_body = markdown_body.strip()
        else:
            markdown_body = "(no content)"

        # Build workflow progress display
        current_phase = self.task_data.get('phase')
        workflow_display = self._build_workflow_progress(current_phase)

        container.mount(
            Static(f"📋 {self.task_id}", classes="screen-title"),
            # Compact single-section layout
            Static(f"Title: {self.task_data['title']}", classes="detail-row"),
            Static(f"Project: {self.task_data.get('project_name', '-')} | Repo: {self.task_data.get('repository_name') or '-'}", classes="detail-row"),
            Static(f"[1] Status: {self._format_status(self.task_data['agent_status'])}", classes="detail-row"),
            Static(f"[2] Priority: {self.task_data['priority'].upper()} | [3] Category: {self.task_data['category']}", classes="detail-row"),
            Static(f"Type: {self.task_data['type']}", classes="detail-row"),
            Static(agent_status_line, classes="detail-row"),
            Static(f"Branch: {self.task_data.get('git_branch') or '-'} | tmux: {tmux_session or '-'}", classes="detail-row"),
            Static(f"[n] Notes: {self.task_data.get('notes') or '(none - press n to add)'}", classes="detail-row"),
            Static("─" * 60, classes="detail-row"),
            Static("[bold]Workflow Progress ([4] next / [5] prev):[/bold]", classes="detail-row"),
            Static(workflow_display, classes="detail-row"),
            Static("─" * 60, classes="detail-row"),
            Static("[bold]Task Content:[/bold]", classes="detail-row"),
            Static(markdown_body, classes="task-markdown-content"),
        )

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


class AgentCard(Static):
    """A card widget displaying a single agent's status and output"""

    def __init__(self, agent_data: Dict, selected: bool = False):
        super().__init__()
        self.agent_data = agent_data
        self.selected = selected
        self.task_id = agent_data.get("task_id", "")

    def compose(self) -> ComposeResult:
        yield Static("", id="card-header", classes="agent-card-header")

        # Three-column layout: tmux output | workflow | metadata
        yield Horizontal(
            Container(
                Static("", id="card-output", classes="agent-card-output"),
                classes="agent-card-left"
            ),
            Container(
                Static("", id="card-workflow", classes="agent-card-workflow"),
                classes="agent-card-middle"
            ),
            Container(
                Static("", id="card-metadata", classes="agent-card-metadata"),
                classes="agent-card-right"
            ),
            classes="agent-card-content"
        )

    def on_mount(self) -> None:
        """Update content after mounting"""
        self._refresh_content()

    def update_data(self, agent_data: Dict, selected: bool) -> None:
        """Update the card with new data without remounting"""
        self.agent_data = agent_data
        self.selected = selected
        self._refresh_content()
        # Update selection styling
        if selected:
            self.add_class("agent-card-selected")
        else:
            self.remove_class("agent-card-selected")

    def _refresh_content(self) -> None:
        """Refresh all content in the card"""
        agent = self.agent_data
        health_display = get_health_display(agent["health"])

        # Build header
        selector = "▶ " if self.selected else "  "
        header = f"{selector}[bold]{agent['task_id']}[/bold] | {health_display} | {agent.get('task_agent_status', '-')}"

        # Build output text
        recent_lines = agent.get("recent_output", [])
        non_empty = [line for line in recent_lines if line.strip()][-10:]
        output_text = "\n".join(non_empty) if non_empty else "(no output)"

        output_lines = []
        for line in output_text.split("\n"):
            if len(line) > 80:
                line = line[:77] + "..."
            output_lines.append(line)
        output_text = "\n".join(output_lines)

        # Build workflow progress
        workflow_text = self._build_workflow_text()

        # Update widgets
        try:
            self.query_one("#card-header", Static).update(header)
            self.query_one("#card-output", Static).update(output_text)
            self.query_one("#card-workflow", Static).update(workflow_text)
            self.query_one("#card-metadata", Static).update(self._build_metadata_text())
        except Exception:
            pass  # Widget not yet mounted

    def _build_workflow_text(self) -> str:
        """Build workflow progress text for middle column"""
        task_id = self.agent_data.get("task_id", "")
        task = task_store.get_task(task_id) if task_id else {}
        if not task:
            return "[dim]No workflow data[/dim]"

        current_phase = task.get("phase")
        if not current_phase:
            return "[dim]No phase set[/dim]"

        lines = ["[bold]Workflow:[/bold]"]
        workflow_lines = self._build_compact_workflow(current_phase)
        lines.extend(workflow_lines)
        return "\n".join(lines)

    def _build_metadata_text(self) -> str:
        """Build the metadata display text for the right panel"""
        agent = self.agent_data
        task_id = agent.get("task_id", "")

        # Get full task data for additional metadata
        task = task_store.get_task(task_id) if task_id else {}
        if not task:
            task = {}

        lines = []

        # Title (truncated)
        title = agent.get("task_title") or task.get("title", "-")
        if len(title) > 30:
            title = title[:27] + "..."
        lines.append(f"[bold]Title:[/bold] {title}")

        # Project
        project = agent.get("project") or task.get("project_name", "-")
        lines.append(f"[bold]Project:[/bold] {project}")

        # Category and Type
        category = task.get("category", "-")
        task_type = task.get("type", "-")
        lines.append(f"[bold]Category:[/bold] {category}")
        lines.append(f"[bold]Type:[/bold] {task_type}")

        # Priority
        priority = task.get("priority", "-")
        priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(priority, "")
        lines.append(f"[bold]Priority:[/bold] {priority_icon} {priority}")

        # Git Branch
        branch = task.get("git_branch") or "-"
        if len(branch) > 25:
            branch = branch[:22] + "..."
        lines.append(f"[bold]Branch:[/bold] {branch}")

        # Assignee
        assignee = task.get("assignee", "-")
        lines.append(f"[bold]Assignee:[/bold] {assignee}")

        # Due date
        due = task.get("due")
        if due:
            lines.append(f"[bold]Due:[/bold] {due}")

        # Notes (if any)
        notes = agent.get("notes") or task.get("notes", "")
        if notes:
            if len(notes) > 30:
                notes = notes[:27] + "..."
            lines.append(f"[bold]Notes:[/bold] 📝 {notes}")

        # Elapsed time
        elapsed = agent.get("elapsed", "-")
        if elapsed and elapsed != "-":
            lines.append(f"[bold]Elapsed:[/bold] {elapsed}")

        return "\n".join(lines)

    def _build_compact_workflow(self, current_phase: Optional[str]) -> List[str]:
        """Build compact workflow progress for agent card"""
        lines = []
        for phase in task_md.VALID_PHASE:
            display_name = task_md.get_phase_display_name(phase)

            # Shorten display names for compact view
            short_name = display_name[:12]  # Truncate long names

            if phase == current_phase:
                lines.append(f"▶ {short_name}")
            elif not current_phase or task_md.VALID_PHASE.index(phase) < task_md.VALID_PHASE.index(current_phase):
                lines.append(f"✓ [dim]{short_name}[/dim]")
            else:
                # Skip future phases in compact view to save space
                continue

        return lines

    def action_show_help(self) -> None:
        """Show help overlay"""
        self.app.push_screen(HelpOverlay("ProjectManagement"))


class AgentsMonitorScreen(Screen):
    """Dedicated screen for monitoring all agents"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("enter", "view_task", "View"),
        ("a", "attach_tmux", "Attach"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("question_mark", "show_help", "Help"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.selected_index = 0
        self.agents_data: List[Dict] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield ScrollableContainer(
            Static("🤖 ACTIVE AGENTS", classes="screen-title"),
            Container(id="agents-cards-container"),
            id="agents-monitor-scroll"
        )
        yield Footer()

    def on_mount(self) -> None:
        self._card_widgets: Dict[str, AgentCard] = {}
        self.load_agents()
        # Auto-refresh every 2 seconds
        self.set_interval(2, self.load_agents)

    def load_agents(self) -> None:
        """Load and display all agent statuses as cards"""
        self.agents_data = get_all_agent_statuses()

        # Check for state changes and send desktop notifications
        check_and_notify_state_changes(self.agents_data)

        container = self.query_one("#agents-cards-container", Container)

        if not self.agents_data:
            # Only clear if we have cards to remove
            if self._card_widgets:
                container.remove_children()
                self._card_widgets.clear()
                container.mount(Static("[dim]No agents with tmux sessions found[/dim]"))
            return

        # Clamp selected index
        if self.selected_index >= len(self.agents_data):
            self.selected_index = len(self.agents_data) - 1
        if self.selected_index < 0:
            self.selected_index = 0

        # Build set of current task IDs
        current_task_ids = {agent["task_id"] for agent in self.agents_data}

        # Remove cards for agents that no longer exist
        for task_id in list(self._card_widgets.keys()):
            if task_id not in current_task_ids:
                self._card_widgets[task_id].remove()
                del self._card_widgets[task_id]

        # Update existing cards or create new ones
        for i, agent in enumerate(self.agents_data):
            task_id = agent["task_id"]
            is_selected = (i == self.selected_index)

            if task_id in self._card_widgets:
                # Update existing card in place
                self._card_widgets[task_id].update_data(agent, is_selected)
            else:
                # Create new card
                card = AgentCard(agent, selected=is_selected)
                card.add_class("agent-card")
                if is_selected:
                    card.add_class("agent-card-selected")
                self._card_widgets[task_id] = card
                container.mount(card)

    def action_go_back(self) -> None:
        """Go back to main dashboard"""
        self.app.pop_screen()

    def action_cursor_down(self) -> None:
        """Move cursor down (vim j)"""
        if self.agents_data and self.selected_index < len(self.agents_data) - 1:
            self.selected_index += 1
            self.load_agents()

    def action_cursor_up(self) -> None:
        """Move cursor up (vim k)"""
        if self.agents_data and self.selected_index > 0:
            self.selected_index -= 1
            self.load_agents()

    def action_refresh(self) -> None:
        """Manually refresh agent list"""
        self.load_agents()
        self.app.notify("Agents refreshed", severity="information")

    def action_view_task(self) -> None:
        """Open task detail for selected agent"""
        if not self.agents_data:
            return
        task_id = self.agents_data[self.selected_index]["task_id"]
        self.app.push_screen(TaskDetailScreen(task_id))

    def action_attach_tmux(self) -> None:
        """Attach to selected agent's tmux session"""
        import subprocess
        import os
        from agentctl.core.tmux import session_exists

        if not self.agents_data:
            self.app.notify("No agent selected", severity="warning")
            return

        task_id = self.agents_data[self.selected_index]["task_id"]

        # Get task to find tmux session
        task = task_store.get_task(task_id)
        if not task:
            self.app.notify(f"Task {task_id} not found", severity="error")
            return

        tmux_session = task.get("tmux_session")
        if not tmux_session:
            self.app.notify("Task has no tmux session", severity="warning")
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

    def action_open_ghostty(self) -> None:
        """Open selected agent's tmux session in a new Ghostty window"""
        import subprocess
        import platform
        from agentctl.core.tmux import session_exists

        if not self.agents_data:
            self.app.notify("No agent selected", severity="warning")
            return

        agent = self.agents_data[self.selected_index]
        task_id = agent["task_id"]
        tmux_session = agent.get("tmux_session")

        if not tmux_session:
            # Try getting from task data
            task = task_store.get_task(task_id)
            if task:
                tmux_session = task.get("tmux_session")

        if not tmux_session:
            self.app.notify("Task has no tmux session", severity="warning")
            return

        if not session_exists(tmux_session):
            self.app.notify(f"Session '{tmux_session}' not found", severity="error")
            return

        try:
            if platform.system() == "Darwin":
                # macOS: Use open command with Ghostty's -e flag to run command
                subprocess.Popen(
                    ["open", "-na", "/Applications/Ghostty.app", "--args",
                     "-e", "tmux", "attach", "-t", tmux_session],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            else:
                # Linux: Use ghostty +new-window action
                subprocess.Popen(
                    ["ghostty", "+new-window", "-e", "tmux", "attach", "-t", tmux_session],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            self.app.notify(f"Opened {tmux_session} in Ghostty", severity="success")
        except FileNotFoundError:
            self.app.notify("Ghostty not found. Install from ghostty.org", severity="error")
        except Exception as e:
            self.app.notify(f"Failed to open Ghostty: {e}", severity="error")

    def action_save_session_log(self) -> None:
        """Save the selected agent's tmux session to a log file"""
        if not self.agents_data:
            self.app.notify("No agent selected", severity="warning")
            return

        agent = self.agents_data[self.selected_index]
        task_id = agent["task_id"]
        tmux_session = agent.get("tmux_session")

        if not tmux_session:
            self.app.notify("No tmux session for this agent", severity="warning")
            return

        filepath = save_session_log(task_id, tmux_session)
        if filepath:
            self.app.notify(f"Session saved: {filepath}", severity="success")
        else:
            self.app.notify("Failed to capture session", severity="error")

    def action_view_prompts(self) -> None:
        """View user prompts for the selected agent's session"""
        if not self.agents_data:
            self.app.notify("No agent selected", severity="warning")
            return

        agent = self.agents_data[self.selected_index]
        task_id = agent["task_id"]
        tmux_session = agent.get("tmux_session")

        # Check if we have prompts in the database for this task
        prompts = database.get_user_prompts(task_id=task_id, limit=1)

        if prompts:
            # We have stored prompts, show them
            self.app.push_screen(UserPromptsScreen(task_id=task_id))
        else:
            # No stored prompts - try to capture and parse the current session
            if not tmux_session:
                self.app.notify("No session data. Use 'l' to capture session first.", severity="warning")
                return

            # Capture session and parse it
            filepath = save_session_log(task_id, tmux_session)
            if filepath:
                # Now show the prompts
                self.app.push_screen(UserPromptsScreen(task_id=task_id))
            else:
                self.app.notify("Failed to capture session", severity="error")

    def action_show_help(self) -> None:
        """Show help overlay"""
        self.app.push_screen(HelpOverlay("AgentsMonitor"))


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
    #create-project-modal, #create-repo-modal, #edit-project-modal, #edit-repo-modal, #create-task-modal, #edit-task-modal, #start-task-modal {
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
        padding: 0;
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
    """

    BINDINGS = [
        ("p", "manage_projects", "Projects"),
        ("t", "manage_tasks", "Tasks"),
        ("a", "monitor_agents", "Agents"),
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

    def action_monitor_agents(self) -> None:
        """Open agents monitor screen"""
        self.push_screen(AgentsMonitorScreen())

    def action_view_analytics(self) -> None:
        """Open analytics screen"""
        self.push_screen(AnalyticsScreen())

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


def run_dashboard(open_agents: bool = False):
    """Run the dashboard application

    Args:
        open_agents: If True, open directly to agents monitor screen
    """
    app = AgentDashboard()
    if open_agents:
        app.push_screen(AgentsMonitorScreen())
    app.run()
