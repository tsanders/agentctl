"""Task management for agentctl"""

from pathlib import Path
from typing import Optional, Dict
from datetime import datetime

from agentctl.core import database
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
