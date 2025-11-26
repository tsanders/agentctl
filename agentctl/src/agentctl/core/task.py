"""Task management for agentctl

Tasks are stored as markdown files - no SQLite database for task data.
"""

from pathlib import Path
from typing import Optional, Dict
from datetime import datetime

import shutil

from agentctl.core import database, task_md
from agentctl.core import task_store
from agentctl.core.tmux import create_session, session_exists
from agentctl.core.git import create_branch, get_current_branch


class Task:
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.load_from_markdown()

    def load_from_markdown(self):
        """Load task details from markdown file"""
        task_data = task_store.get_task(self.task_id)

        if not task_data:
            raise ValueError(f"Task {self.task_id} not found")

        self.project_id = task_data['project_id']
        self.repository_id = task_data.get('repository_id')
        self.category = task_data.get('category', 'FEATURE')
        self.title = task_data['title']
        self.agent_status = task_data.get('agent_status', 'queued')
        self.priority = task_data.get('priority', 'medium')
        self.phase = task_data.get('phase')

        # Project and repository info from task_store
        self.project_name = task_data.get('project_name', self.project_id)

        if self.repository_id:
            self.repository_path = Path(task_data['repository_path']) if task_data.get('repository_path') else None
            self.repository_name = task_data.get('repository_name')
            self.default_branch = task_data.get('default_branch', 'main')
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


def copy_task_file_to_workdir(task_id: str, work_dir: Path) -> Optional[Path]:
    """
    Copy source task markdown to TASK.md in working directory.

    Args:
        task_id: Task ID
        work_dir: Target working directory

    Returns:
        Path to the created TASK.md, or None if source not found
    """
    file_path = task_store.get_task_file_path(task_id)
    if not file_path or not file_path.exists():
        return None

    dest_path = work_dir / "TASK.md"
    shutil.copy2(file_path, dest_path)
    return dest_path


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

    # Update task in markdown file
    updates = {
        'agent_status': 'running',
        'phase': 'planning',
        'started_at': datetime.now().isoformat(),
        'git_branch': branch,
        'tmux_session': session,
        'agent_type': agent_type or 'claude-code'
    }
    task_store.update_task(task_id, updates)

    # Copy task file to working directory
    copy_task_file_to_workdir(task_id, work_dir)

    # Log event
    database.add_event(task_id, 'task_started', {'branch': branch, 'session': session})

    return task


def pause_task(task_id: str):
    """Pause a running task"""
    task_store.update_task(task_id, {'agent_status': 'paused'})
    database.add_event(task_id, 'task_paused')


def resume_task(task_id: str):
    """Resume a paused task"""
    task_store.update_task(task_id, {'agent_status': 'running'})
    database.add_event(task_id, 'task_resumed')


def complete_task(task_id: str):
    """Mark a task as complete"""
    updates = {
        'agent_status': 'completed',
        'completed_at': datetime.now().isoformat()
    }
    task_store.update_task(task_id, updates)
    database.add_event(task_id, 'task_completed')


def get_next_review() -> Optional[Dict]:
    """Get next task needing review"""
    tasks = task_store.query_tasks(agent_status='blocked')

    if not tasks:
        return None

    return tasks[0]


# Task operations (all use markdown files)

def create_task(
    project_id: str,
    category: str,
    title: str,
    description: Optional[str] = None,
    repository_id: Optional[str] = None,
    task_type: str = "feature",
    priority: str = "medium"
) -> Optional[str]:
    """
    Create a new task as a markdown file.

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

    return task_id


# Aliases for backwards compatibility
create_markdown_task = create_task


def update_task(task_id: str, updates: Dict) -> bool:
    """
    Update a task's markdown file.

    Args:
        task_id: Task ID
        updates: Dictionary of fields to update

    Returns:
        True if successful, False otherwise
    """
    return task_store.update_task(task_id, updates)


# Alias for backwards compatibility
update_markdown_task = update_task


def delete_task(task_id: str) -> bool:
    """
    Delete a task's markdown file.

    Args:
        task_id: Task ID

    Returns:
        True if successful, False otherwise
    """
    return task_store.delete_task(task_id)


# Alias for backwards compatibility
delete_markdown_task = delete_task
