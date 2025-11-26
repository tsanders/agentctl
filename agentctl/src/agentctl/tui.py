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
from agentctl.core.agent_monitor import get_agent_status, get_all_agent_statuses, get_health_display, HEALTH_ICONS


class AgentStatusWidget(Static):
    """Widget showing active agents with real-time updates"""

    def compose(self) -> ComposeResult:
        yield Static("🤖 ACTIVE AGENTS", classes="widget-title")
        yield DataTable(id="agents-table")

    def on_mount(self) -> None:
        table = self.query_one("#agents-table", DataTable)
        table.add_columns("Task ID", "Project", "Health", "Status", "Elapsed")
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
                    agent['project'],
                    "⚪ NO SESSION",
                    f"{status_icon} {agent['agent_status'].upper()}",
                    agent['elapsed']
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

            # Format elapsed time
            elapsed = agent.get('elapsed', '-')

            # Truncate title
            title = agent.get('task_title', '-')
            if len(title) > 25:
                title = title[:22] + "..."

            table.add_row(
                agent['task_id'],
                title,
                f"{health_icon} {health.upper()}",
                f"{status_icon} {task_status.upper()}",
                elapsed
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
        repo_path = Path(self.task_data['repository_path'])
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

                    repo_path = Path(self.task_data['repository_path'])
                    base_branch = self.task_data.get('repository_default_branch', 'main')

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
                        working_dir = Path(self.task_data['repository_path'])
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


class ProjectDetailScreen(Screen):
    """Screen showing project details with repositories and tasks"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("r", "add_repo", "Add Repo"),
        ("e", "edit_repo", "Edit Repo"),
        ("t", "create_task", "Create Task"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
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


class TaskManagementScreen(Screen):
    """Screen showing all tasks across all projects"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("n", "create_task", "New Task"),
        ("e", "edit_task", "Edit Task"),
        ("d", "delete_task", "Delete Task"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
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
        """Load and display all tasks - compact for mobile"""
        tasks = task_store.list_all_tasks()

        table = self.query_one("#tasks-table", DataTable)
        table.clear()
        # Only add columns on first load
        if len(table.columns) == 0:
            # Compact columns: S=Status, P=Priority, A=Agent health
            table.add_columns("ID", "Title", "S", "P", "A")
            table.cursor_type = "row"

        for task in tasks:
            status_icon = {
                "queued": "⚪",
                "running": "🟢",
                "blocked": "🟡",
                "completed": "✅",
                "failed": "🔴"
            }.get(task.get('agent_status', 'queued'), "⚪")

            priority_icon = {
                "high": "🔴",
                "medium": "🟡",
                "low": "🟢"
            }.get(task.get('priority', 'medium'), "⚪")

            # Agent health indicator
            tmux_session = task.get('tmux_session')
            if tmux_session:
                agent_status = get_agent_status(task['task_id'], tmux_session)
                agent_icon = agent_status.get('icon', '-')
            else:
                agent_icon = "-"

            table.add_row(
                task['task_id'],
                task.get('title', '-')[:40],
                status_icon,
                priority_icon,
                agent_icon
            )

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
        """Edit selected task - open nvim for markdown, modal for database"""
        table = self.query_one("#tasks-table", DataTable)
        if table.row_count > 0 and table.cursor_row is not None:
            row = table.get_row_at(table.cursor_row)
            source = str(row[0])  # "[MD]" or "[DB]"
            task_id = str(row[1])  # Task ID is second column now

            # Check if this is a markdown task
            if source == "[MD]":
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
                            import os

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
            else:
                # Database task - use modal
                def check_result(result):
                    if result:
                        self.load_tasks()

                self.app.push_screen(EditTaskModal(task_id), check_result)

    def action_delete_task(self) -> None:
        """Delete selected task with confirmation"""
        table = self.query_one("#tasks-table", DataTable)
        if table.row_count > 0 and table.cursor_row is not None:
            row = table.get_row_at(table.cursor_row)
            task_id = str(row[1])  # Task ID is second column now

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
        ("s", "start_task", "Start Task"),
        ("e", "edit_in_nvim", "Edit in nvim"),
        ("a", "attach_tmux", "Attach tmux"),
        ("f", "refresh_task_file", "Refresh TASK.md"),
        ("1", "cycle_status", "Cycle Status"),
        ("2", "cycle_priority", "Cycle Priority"),
        ("3", "cycle_category", "Cycle Category"),
        ("c", "complete_task", "Complete"),
        ("d", "delete_task", "Delete"),
        ("j", "scroll_down", "Down"),
        ("k", "scroll_up", "Up"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, task_id: str):
        super().__init__()
        self.task_id = task_id
        self.task_data = None

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

        container.mount(
            Static(f"📋 {self.task_id}", classes="screen-title"),
            # Compact single-section layout
            Static(f"Title: {self.task_data['title']}", classes="detail-row"),
            Static(f"Desc: {desc_short}", classes="detail-row"),
            Static(f"Project: {self.task_data.get('project_name', '-')} | Repo: {self.task_data.get('repository_name') or '-'}", classes="detail-row"),
            Static(f"[1] Status: {self._format_status(self.task_data['agent_status'])}", classes="detail-row"),
            Static(f"[2] Priority: {self.task_data['priority'].upper()} | [3] Category: {self.task_data['category']}", classes="detail-row"),
            Static(f"Type: {self.task_data['type']} | Phase: {self.task_data.get('phase') or '-'}", classes="detail-row"),
            Static(agent_status_line, classes="detail-row"),
            Static(f"Commits: {self.task_data.get('commits', 0)}", classes="detail-row"),
            Static(f"Created: {self._format_timestamp(self.task_data.get('created_at'))} | Started: {self._format_timestamp(self.task_data.get('started_at'))}", classes="detail-row"),
            Static(f"Branch: {self.task_data.get('git_branch') or '-'}", classes="detail-row"),
            Static(f"Worktree: {self.task_data.get('worktree_path') or '-'}", classes="detail-row"),
            Static(f"tmux: {tmux_session or '-'}", classes="detail-row"),
        )

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
            work_dir = Path(self.task_data['worktree_path'])
        elif self.task_data.get('repository_path'):
            work_dir = Path(self.task_data['repository_path'])
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

    def _update_field(self, field: str, value: str) -> None:
        """Update a single field in the task"""
        success = update_task(self.task_id, {field: value})
        if not success:
            self.app.notify(f"Failed to update {field}", severity="error")
            return

        self.app.notify(f"{field.capitalize()} changed to: {value}", severity="success")
        self.load_task_details()


class ProjectListScreen(Screen):
    """Screen showing all projects"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("n", "new_project", "New Project"),
        ("e", "edit_project", "Edit Project"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
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

    def compose(self) -> ComposeResult:
        agent = self.agent_data
        health_display = get_health_display(agent["health"])

        # Get multiple lines of recent output
        recent_lines = agent.get("recent_output", [])
        # Filter to non-empty lines and get last 10
        non_empty = [line for line in recent_lines if line.strip()][-10:]
        output_text = "\n".join(non_empty) if non_empty else "(no output)"

        # Truncate each line if too long
        output_lines = []
        for line in output_text.split("\n"):
            if len(line) > 100:
                line = line[:97] + "..."
            output_lines.append(line)
        output_text = "\n".join(output_lines)

        selector = "▶ " if self.selected else "  "

        yield Static(f"{selector}[bold]{agent['task_id']}[/bold] | {health_display} | {agent.get('task_agent_status', '-')}", classes="agent-card-header")
        yield Static(output_text, classes="agent-card-output")


class AgentsMonitorScreen(Screen):
    """Dedicated screen for monitoring all agents"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("enter", "view_task", "View Task"),
        ("a", "attach_tmux", "Attach tmux"),
        ("g", "open_ghostty", "Ghostty"),
        ("r", "refresh", "Refresh"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
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
        self.load_agents()
        # Auto-refresh every 2 seconds
        self.set_interval(2, self.load_agents)

    def load_agents(self) -> None:
        """Load and display all agent statuses as cards"""
        self.agents_data = get_all_agent_statuses()

        container = self.query_one("#agents-cards-container", Container)
        container.remove_children()

        if not self.agents_data:
            container.mount(Static("[dim]No agents with tmux sessions found[/dim]"))
            return

        # Clamp selected index
        if self.selected_index >= len(self.agents_data):
            self.selected_index = len(self.agents_data) - 1
        if self.selected_index < 0:
            self.selected_index = 0

        for i, agent in enumerate(self.agents_data):
            is_selected = (i == self.selected_index)
            card = AgentCard(agent, selected=is_selected)
            card.add_class("agent-card")
            if is_selected:
                card.add_class("agent-card-selected")
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
    }

    .agent-card-selected {
        border: solid $success;
        background: $boost;
    }

    .agent-card-header {
        text-style: bold;
        padding: 0;
    }

    .agent-card-output {
        color: $text-muted;
        padding: 0;
        margin-left: 2;
    }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("q", "quit", "Quit"),
        ("s", "status", "Status"),
        ("p", "manage_projects", "Projects"),
        ("t", "manage_tasks", "Tasks"),
        ("a", "monitor_agents", "Agents"),
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


def run_dashboard():
    """Run the dashboard application"""
    app = AgentDashboard()
    app.run()
