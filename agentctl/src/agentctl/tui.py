"""Textual TUI Dashboard for agentctl"""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer, Center
from textual.widgets import Header, Footer, Static, DataTable, Log, Button, Input, Label, Select
from textual.reactive import reactive
from textual.screen import Screen, ModalScreen
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path

from agentctl.core import database, task_sync, task_md
from agentctl.core.task import create_markdown_task, update_markdown_task, delete_markdown_task


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
                    actual_task_id = create_markdown_task(
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
        self.task_data = database.get_task_with_details(task_id)

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
                prompt="Status",
                id="task-status",
                value=self.task_data['status']
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
            status = self.query_one("#task-status", Select).value

            if not title or not project_id:
                self.app.notify("Title and Project are required", severity="error")
                return

            try:
                # Handle blank repository selection
                final_repo_id = None
                if repo_id and repo_id != Select.BLANK:
                    final_repo_id = repo_id

                # Check if this is a markdown task
                task_source = self.task_data.get('source', 'database')
                if task_source == 'markdown':
                    # Update markdown task
                    updates = {
                        'title': title.strip(),
                        'description': description.strip() if description else None,
                        'project_id': project_id,
                        'repository_id': final_repo_id,
                        'category': category,
                        'type': task_type.strip(),
                        'priority': priority,
                        'status': status
                    }
                    success = update_markdown_task(self.task_id, updates)
                    if not success:
                        self.app.notify("Failed to update markdown task", severity="error")
                        return
                else:
                    # Update database task
                    database.update_task(
                        self.task_id,
                        title=title.strip(),
                        description=description.strip() if description else None,
                        project_id=project_id,
                        repository_id=final_repo_id,
                        category=category,
                        type=task_type.strip(),
                        priority=priority,
                        status=status
                    )

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
        self.task_data = database.get_task_with_details(task_id)
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
            yield Container(
                Label(f"Start Task: {self.task_id}", id="modal-title"),
                Static("❌ No repository associated with this task", classes="detail-row"),
                Static("Cannot create worktree without a repository.", classes="detail-row"),
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

        yield Container(
            Label(f"Start Task: {self.task_id}", id="modal-title"),
            Static(f"Title: {self.task_data['title']}", classes="detail-row"),
            Static(f"Repository: {self.task_data['repository_name']}", classes="detail-row"),
            Static("", classes="detail-row"),  # Spacer
            Static("🌿 Git Worktree Configuration", classes="widget-title"),
            Static(f"Branch: {branch_name}", classes="detail-row"),
            Static(f"Worktree Path: {worktree_path}", classes="detail-row"),
            Static("", classes="detail-row"),  # Spacer
            Select(
                options=[
                    ("Yes - Create worktree and branch", True),
                    ("No - Just update status", False)
                ],
                prompt="Create Git Worktree?",
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
                # Check if this is a markdown task
                task_source = self.task_data.get('source', 'database')
                if task_source == 'markdown':
                    # Update markdown task status
                    from datetime import datetime as dt
                    updates = {
                        'status': 'running',
                        'started_at': dt.now().isoformat()
                    }
                    update_markdown_task(self.task_id, updates)
                else:
                    # Update database task status
                    database.update_task_status(
                        self.task_id,
                        "running",
                        started_at=int(datetime.now().timestamp())
                    )

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

                    # Update task with worktree and branch info
                    if task_source == 'markdown':
                        update_markdown_task(self.task_id, {
                            'git_branch': worktree_info['branch_name'],
                            'worktree_path': worktree_info['worktree_path']
                        })
                    else:
                        database.update_task(
                            self.task_id,
                            git_branch=worktree_info['branch_name'],
                            worktree_path=worktree_info['worktree_path']
                        )

                    self.app.notify(
                        f"Task started with worktree at {worktree_info['worktree_path']}",
                        severity="success",
                        timeout=5
                    )
                else:
                    self.app.notify(f"Task {self.task_id} started", severity="success")

                database.add_event(self.task_id, "started")
                self.dismiss(self.task_id)

            except Exception as e:
                self.app.notify(f"Error starting task: {e}", severity="error")


class ProjectDetailScreen(Screen):
    """Screen showing project details with repositories and tasks"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("r", "add_repo", "Add Repo"),
        ("e", "edit_repo", "Edit Repo"),
        ("t", "create_task", "Create Task"),
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
        ("q", "quit", "Quit"),
    ]

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

    def _sync_markdown_tasks(self) -> None:
        """Sync all markdown tasks from projects"""
        try:
            results = task_sync.sync_all_tasks()
            total_synced = sum(r.synced_count for r in results.values())
            if total_synced > 0:
                self.app.notify(f"Synced {total_synced} markdown tasks", severity="information")
        except Exception as e:
            self.app.notify(f"Sync error: {e}", severity="warning")

    def load_tasks(self) -> None:
        """Load and display all tasks"""
        tasks = database.list_all_tasks()

        table = self.query_one("#tasks-table", DataTable)
        table.clear()
        table.add_columns("Source", "Task ID", "Project", "Repository", "Title", "Status", "Priority")
        table.cursor_type = "row"

        for task in tasks:
            # Source indicator
            source = task.get('source', 'database')
            source_label = "[MD]" if source == 'markdown' else "[DB]"

            status_icon = {
                "queued": "⚪",
                "running": "🟢",
                "blocked": "🟡",
                "completed": "✅",
                "failed": "🔴"
            }.get(task.get('status', 'queued'), "⚪")

            priority_icon = {
                "high": "🔴",
                "medium": "🟡",
                "low": "🟢"
            }.get(task.get('priority', 'medium'), "⚪")

            table.add_row(
                source_label,
                task['task_id'],
                task.get('project_name', '-')[:20],
                task.get('repository_name', '-')[:15] if task.get('repository_name') else '-',
                task.get('title', '-')[:30],
                f"{status_icon} {task['status'].upper()}",
                f"{priority_icon} {task['priority'].upper()}"
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection - open task detail view"""
        if event.data_table.id == "tasks-table":
            row = event.data_table.get_row_at(event.cursor_row)
            task_id = str(row[1])  # Task ID is second column (after Source)
            self.app.push_screen(TaskDetailScreen(task_id))

    def action_go_back(self) -> None:
        """Go back to main dashboard"""
        self.app.pop_screen()

    def action_create_task(self) -> None:
        """Create a new task by opening template in nvim"""
        # Get list of projects
        projects = database.list_projects()

        if not projects:
            self.app.notify("No projects found. Create a project first.", severity="error")
            return

        # Find first project with tasks_path (prefer markdown)
        markdown_project = None
        for project in projects:
            if project.get('tasks_path'):
                markdown_project = project
                break

        if not markdown_project:
            # Fall back to modal for database tasks
            def check_result(result):
                if result:
                    self.load_tasks()
            self.app.push_screen(CreateTaskModal(), check_result)
            return

        # Create template for markdown task
        from pathlib import Path
        import tempfile

        project_id = markdown_project['id']
        tasks_path = Path(markdown_project['tasks_path'])

        # Generate next task ID for FEATURE category (most common)
        next_id = task_md.get_next_task_id(tasks_path, project_id, 'FEATURE')

        # Generate template
        template_data = task_md.generate_task_template(
            task_id=next_id,
            title="New task - edit this title",
            project_id=project_id,
            category='FEATURE',
            priority='medium'
        )

        # Create temporary file with template
        temp_file = tasks_path / f".{next_id}.md.tmp"
        task_md.write_task_file(temp_file, template_data, "# New Task\n\nEdit this description...")

        # Open in nvim
        import subprocess

        with self.app.suspend():
            result = subprocess.run(['nvim', str(temp_file)])

        # After nvim closes, validate and move to permanent location
        if temp_file.exists():
            task_data, body, errors = task_md.parse_task_file(temp_file)

            if errors:
                self.app.notify(f"Task validation failed: {'; '.join(errors)}", severity="error")
                temp_file.unlink()
            elif task_data and task_data.get('title') != "New task - edit this title":
                # Valid task that was edited - move to permanent location
                final_file = tasks_path / f"{next_id}.md"
                temp_file.rename(final_file)

                # Sync to database
                task_sync.sync_project_tasks(project_id)
                self.load_tasks()
                self.app.notify(f"Task {next_id} created!", severity="success")
            else:
                # User didn't edit or left default title - discard
                temp_file.unlink()
                self.app.notify("Task creation cancelled", severity="information")

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
                task = database.get_task(task_id)
                if task:
                    project = database.get_project(task['project_id'])
                    if project and project.get('tasks_path'):
                        from pathlib import Path
                        task_file = Path(project['tasks_path']) / f"{task_id}.md"

                        if task_file.exists():
                            # Define callback to sync and reload after nvim closes
                            def after_nvim():
                                # Sync the changes after editing
                                task_sync.sync_project_tasks(task['project_id'])
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
            # TODO: Add confirmation modal
            try:
                database.delete_task(task_id)
                self.load_tasks()
                self.app.notify(f"Task {task_id} deleted", severity="success")
            except Exception as e:
                self.app.notify(f"Error deleting task: {e}", severity="error")


class TaskDetailScreen(Screen):
    """Screen showing comprehensive task details and actions"""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("e", "edit_in_nvim", "Edit in nvim"),
        ("1", "cycle_status", "Cycle Status"),
        ("2", "cycle_priority", "Cycle Priority"),
        ("3", "cycle_category", "Cycle Category"),
        ("d", "delete_task", "Delete"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, task_id: str):
        super().__init__()
        self.task_id = task_id
        self.task_data = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Container(id="task-detail-content"),
            id="task-detail-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        self.load_task_details()

    def load_task_details(self) -> None:
        """Load and display comprehensive task information"""
        self.task_data = database.get_task_with_details(self.task_id)

        if not self.task_data:
            self.app.notify(f"Task {self.task_id} not found", severity="error")
            self.app.pop_screen()
            return

        container = self.query_one("#task-detail-content", Container)
        container.mount(
            Static(f"📋 {self.task_id}: {self.task_data['title']}", classes="screen-title"),

            # Task Information Section
            Container(
                Static("ℹ️  TASK INFORMATION", classes="widget-title"),
                Static(f"Title: {self.task_data['title']}", classes="detail-row"),
                Static(f"Description: {self.task_data.get('description') or 'No description'}", classes="detail-row"),
                Static(f"Category: {self.task_data['category']}", classes="detail-row"),
                Static(f"Type: {self.task_data['type']}", classes="detail-row"),
                Static(f"Priority: {self.task_data['priority'].upper()}", classes="detail-row"),
                id="info-section"
            ),

            # Project & Repository Section
            Container(
                Static("📦 PROJECT & REPOSITORY", classes="widget-title"),
                Static(f"Project: {self.task_data.get('project_name', 'Unknown')}", classes="detail-row"),
                Static(f"Repository: {self.task_data.get('repository_name', 'None')}", classes="detail-row"),
                Static(f"Repository Path: {self.task_data.get('repository_path', 'N/A')}", classes="detail-row"),
                id="project-section"
            ),

            # Status & Progress Section (with quick edit hints)
            Container(
                Static("📊 STATUS & PROGRESS", classes="widget-title"),
                Static(f"[1] Status: {self._format_status(self.task_data['status'])} (press 1 to cycle)", classes="detail-row"),
                Static(f"[2] Priority: {self.task_data['priority'].upper()} (press 2 to cycle)", classes="detail-row"),
                Static(f"[3] Category: {self.task_data['category']} (press 3 to cycle)", classes="detail-row"),
                Static(f"Phase: {self.task_data.get('phase') or 'Not started'}", classes="detail-row"),
                Static(f"Agent Type: {self.task_data.get('agent_type') or 'Not assigned'}", classes="detail-row"),
                Static(f"Commits: {self.task_data.get('commits', 0)}", classes="detail-row"),
                id="status-section"
            ),

            # Timestamps Section
            Container(
                Static("🕒 TIMESTAMPS", classes="widget-title"),
                Static(f"Created: {self._format_timestamp(self.task_data.get('created_at'))}", classes="detail-row"),
                Static(f"Started: {self._format_timestamp(self.task_data.get('started_at'))}", classes="detail-row"),
                Static(f"Completed: {self._format_timestamp(self.task_data.get('completed_at'))}", classes="detail-row"),
                id="timestamps-section"
            ),

            # Git & Session Section
            Container(
                Static("🔧 GIT & SESSION", classes="widget-title"),
                Static(f"Branch: {self.task_data.get('git_branch') or 'Not created'}", classes="detail-row"),
                Static(f"Worktree: {self.task_data.get('worktree_path') or 'Not created'}", classes="detail-row"),
                Static(f"tmux Session: {self.task_data.get('tmux_session') or 'Not running'}", classes="detail-row"),
                id="session-section"
            ),
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
        """Open nvim for markdown tasks, modal for database tasks"""
        # Check if this is a markdown task
        task_source = self.task_data.get('source', 'database')
        if task_source == 'markdown':
            # Get task file path
            project = database.get_project(self.task_data['project_id'])
            if project and project.get('tasks_path'):
                from pathlib import Path
                task_file = Path(project['tasks_path']) / f"{self.task_id}.md"

                if task_file.exists():
                    # Define callback to sync and reload after nvim closes
                    def after_nvim():
                        # Sync the changes after editing
                        task_sync.sync_project_tasks(self.task_data['project_id'])
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
        else:
            # Database task - use modal
            def check_result(result):
                if result:
                    self.load_task_details()

            self.app.push_screen(EditTaskModal(self.task_id), check_result)

    def action_start_task(self) -> None:
        """Open start modal to begin work on task"""
        if self.task_data['status'] in ['running', 'completed']:
            self.app.notify(f"Task is already {self.task_data['status']}", severity="warning")
            return

        def check_result(result):
            if result:
                self.load_task_details()

        self.app.push_screen(StartTaskModal(self.task_id), check_result)

    def action_complete_task(self) -> None:
        """Mark task as completed"""
        if self.task_data['status'] == 'completed':
            self.app.notify("Task is already completed", severity="information")
            return

        from datetime import datetime

        # Check if this is a markdown task
        task_source = self.task_data.get('source', 'database')
        if task_source == 'markdown':
            # Update markdown task
            updates = {
                'status': 'completed',
                'completed_at': datetime.now().isoformat()
            }
            success = update_markdown_task(self.task_id, updates)
            if not success:
                self.app.notify("Failed to update markdown task", severity="error")
                return
        else:
            # Update database task
            database.update_task_status(
                self.task_id,
                "completed",
                completed_at=int(datetime.now().timestamp())
            )

        database.add_event(self.task_id, "completed")
        self.app.notify(f"Task {self.task_id} marked as completed", severity="success")
        self.load_task_details()

    def action_delete_task(self) -> None:
        """Delete this task with confirmation"""
        # Check if this is a markdown task
        task_source = self.task_data.get('source', 'database')
        if task_source == 'markdown':
            # Delete markdown task
            success = delete_markdown_task(self.task_id)
            if not success:
                self.app.notify("Failed to delete markdown task", severity="error")
                return
        else:
            # Delete database task
            database.delete_task(self.task_id)

        database.add_event(self.task_id, "deleted")
        self.app.notify(f"Task {self.task_id} deleted", severity="warning")
        self.app.pop_screen()

    def action_cycle_status(self) -> None:
        """Cycle through status options"""
        statuses = ['queued', 'running', 'blocked', 'completed', 'failed']
        current = self.task_data['status']
        current_idx = statuses.index(current) if current in statuses else 0
        next_status = statuses[(current_idx + 1) % len(statuses)]

        self._update_field('status', next_status)

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
        task_source = self.task_data.get('source', 'database')

        if task_source == 'markdown':
            # Update markdown task
            success = update_markdown_task(self.task_id, {field: value})
            if not success:
                self.app.notify(f"Failed to update {field}", severity="error")
                return
            # Sync changes
            task_sync.sync_project_tasks(self.task_data['project_id'])
        else:
            # Update database task
            database.update_task(self.task_id, **{field: value})

        self.app.notify(f"{field.capitalize()} changed to: {value}", severity="success")
        self.load_task_details()


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
    #create-project-modal, #create-repo-modal, #edit-project-modal, #edit-repo-modal, #create-task-modal, #edit-task-modal, #start-task-modal {
        align: center middle;
        width: 60;
        height: auto;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }

    Select {
        margin: 1 0;
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

    #projects-container, #project-detail-container, #tasks-container {
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

    /* Task detail styles */
    #task-detail-container {
        height: 100%;
        overflow-y: auto;
    }

    #task-detail-content {
        height: auto;
    }

    #info-section, #project-section, #status-section, #timestamps-section, #session-section {
        border: solid $accent;
        margin: 1;
        padding: 1;
    }

    .detail-row {
        padding: 0 1;
        margin-top: 0;
    }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("q", "quit", "Quit"),
        ("s", "status", "Status"),
        ("p", "manage_projects", "Projects"),
        ("t", "manage_tasks", "Tasks"),
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

    def action_manage_tasks(self) -> None:
        """Open tasks management screen"""
        self.push_screen(TaskManagementScreen())


def run_dashboard():
    """Run the dashboard application"""
    app = AgentDashboard()
    app.run()
