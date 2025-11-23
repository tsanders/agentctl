"""Task management for agentctl"""

from pathlib import Path
from typing import Optional, Dict
from datetime import datetime

from agentctl.core import database, task_md, task_sync
from agentctl.core.tmux import create_session, session_exists
from agentctl.core.git import create_branch, get_current_branch


class Task:
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.load_from_db()

    def load_from_db(self):
        """Load task details from database"""
        task_data = database.get_task(self.task_id)

        if not task_data:
            raise ValueError(f"Task {self.task_id} not found")

        self.project_id = task_data['project_id']
        self.repository_id = task_data.get('repository_id')
        self.category = task_data['category']
        self.title = task_data['title']
        self.status = task_data['status']
        self.priority = task_data['priority']
        self.phase = task_data.get('phase')

        # Load project and repository details
        project_data = database.get_project(self.project_id)
        self.project_name = project_data['name'] if project_data else self.project_id

        if self.repository_id:
            repo_data = database.get_repository(self.repository_id)
            if repo_data:
                self.repository_path = Path(repo_data['path'])
                self.repository_name = repo_data['name']
                self.default_branch = repo_data.get('default_branch', 'main')
            else:
                self.repository_path = None
                self.repository_name = None
                self.default_branch = 'main'
        else:
            self.repository_path = None
            self.repository_name = None
            self.default_branch = 'main'

    @property
    def branch(self) -> str:
        """Git branch name for this task"""
        prefix = {
            'FEATURE': 'feature',
            'BUG': 'bugfix',
            'REFACTOR': 'refactor'
        }.get(self.category, 'task')

        return f"{prefix}/{self.task_id}"

    @property
    def tmux_session(self) -> str:
        """tmux session name for this task"""
        return f"agent-{self.task_id}"

    @property
    def workspace_dir(self) -> Path:
        """Workspace directory for this task"""
        if self.repository_path:
            return self.repository_path
        return Path.cwd()  # Fallback to current directory

    @property
    def preferred_agent(self) -> Optional[str]:
        """Determine preferred agent based on task type"""
        return None


def start_task(task_id: str, agent_type: Optional[str] = None, working_dir: Optional[Path] = None) -> Task:
    """Initialize and start a new task"""
    task = Task(task_id)

    # Use provided working dir or task's workspace
    work_dir = working_dir or task.workspace_dir
    work_dir = Path(work_dir).resolve()

    # Create git branch (only if repository is configured)
    if task.repository_path:
        try:
            branch = create_branch(task.branch, base=task.default_branch, repo_path=task.repository_path)
        except Exception as e:
            raise RuntimeError(f"Failed to create git branch in {task.repository_path}: {e}")
    else:
        branch = None

    # Create tmux session
    try:
        session = create_session(task.tmux_session, work_dir)
    except Exception as e:
        raise RuntimeError(f"Failed to create tmux session: {e}")

    # Update database
    database.update_task_status(
        task_id=task_id,
        status='running',
        phase='planning',
        started_at=int(datetime.now().timestamp()),
        git_branch=branch,
        tmux_session=session,
        agent_type=agent_type or 'claude-code'
    )

    # Log event
    database.add_event(task_id, 'task_started', {'branch': branch, 'session': session})

    return task


def pause_task(task_id: str):
    """Pause a running task"""
    database.update_task_status(task_id, 'paused')
    database.add_event(task_id, 'task_paused')


def resume_task(task_id: str):
    """Resume a paused task"""
    database.update_task_status(task_id, 'running')
    database.add_event(task_id, 'task_resumed')


def complete_task(task_id: str):
    """Mark a task as complete"""
    database.update_task_status(
        task_id,
        'complete',
        completed_at=int(datetime.now().timestamp())
    )
    database.add_event(task_id, 'task_completed')


def get_next_review() -> Optional[Dict]:
    """Get next task needing review"""
    tasks = database.query_tasks(status='blocked')

    if not tasks:
        return None

    return tasks[0]


# Markdown task operations

def create_markdown_task(
    project_id: str,
    category: str,
    title: str,
    description: Optional[str] = None,
    repository_id: Optional[str] = None,
    task_type: str = "feature",
    priority: str = "medium"
) -> Optional[str]:
    """
    Create a new markdown task file

    Args:
        project_id: Project ID
        category: Task category (FEATURE, BUG, etc.)
        title: Task title
        description: Optional description
        repository_id: Optional repository ID
        task_type: Task type
        priority: Task priority

    Returns:
        Task ID if successful, None otherwise
    """
    # Get project
    project = database.get_project(project_id)
    if not project or not project.get('tasks_path'):
        return None

    tasks_path = Path(project['tasks_path'])

    # Generate next task ID
    task_id = task_md.get_next_task_id(tasks_path, project_id, category)

    # Generate task data
    task_data = task_md.generate_task_template(
        task_id=task_id,
        title=title,
        project_id=project_id,
        repository_id=repository_id,
        category=category,
        task_type=task_type,
        priority=priority,
        description=description or ""
    )

    # Write markdown file
    task_file = tasks_path / f"{task_id}.md"
    body = f"# {title}\n\n{description or ''}"
    task_md.write_task_file(task_file, task_data, body)

    # Sync to database
    task_sync.sync_project_tasks(project_id)

    return task_id


def update_markdown_task(task_id: str, updates: Dict) -> bool:
    """
    Update a markdown task file

    Args:
        task_id: Task ID
        updates: Dictionary of fields to update

    Returns:
        True if successful, False otherwise
    """
    # Get task from database to verify it exists and is markdown
    task = database.get_task(task_id)
    if not task or task.get('source') != 'markdown':
        return False

    # Get project to find tasks_path
    project = database.get_project(task['project_id'])
    if not project or not project.get('tasks_path'):
        return False

    tasks_path = Path(project['tasks_path'])
    task_file = tasks_path / f"{task_id}.md"

    if not task_file.exists():
        return False

    # Update file
    success = task_md.update_task_file(task_file, updates)

    if success:
        # Sync to database
        task_sync.sync_project_tasks(task['project_id'])

    return success


def delete_markdown_task(task_id: str) -> bool:
    """
    Delete a markdown task file

    Args:
        task_id: Task ID

    Returns:
        True if successful, False otherwise
    """
    # Get task from database
    task = database.get_task(task_id)
    if not task or task.get('source') != 'markdown':
        return False

    # Get project to find tasks_path
    project = database.get_project(task['project_id'])
    if not project or not project.get('tasks_path'):
        return False

    tasks_path = Path(project['tasks_path'])
    task_file = tasks_path / f"{task_id}.md"

    try:
        if task_file.exists():
            task_file.unlink()

        # Remove from database
        database.delete_task(task_id)

        return True
    except Exception:
        return False
