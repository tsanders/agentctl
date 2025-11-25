"""Task management for agentctl"""

from pathlib import Path
from typing import Optional, Dict
from datetime import datetime

import shutil

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


def copy_task_file_to_workdir(task_id: str, work_dir: Path) -> Optional[Path]:
    """
    Copy source task markdown to TASK.md in working directory.

    Args:
        task_id: Task ID
        work_dir: Target working directory

    Returns:
        Path to the created TASK.md, or None if source not found
    """
    task_data = database.get_task(task_id)
    if not task_data:
        return None

    dest_path = work_dir / "TASK.md"

    if task_data.get('source') == 'markdown':
        # Copy from markdown source file
        project = database.get_project(task_data['project_id'])
        if not project or not project.get('tasks_path'):
            return None

        source_path = Path(project['tasks_path']) / f"{task_id}.md"
        if not source_path.exists():
            return None

        shutil.copy2(source_path, dest_path)
    else:
        # Generate markdown from database fields
        content = _generate_task_markdown(task_data)
        dest_path.write_text(content, encoding='utf-8')

    return dest_path


def _generate_task_markdown(task_data: Dict) -> str:
    """Generate markdown content from database task data."""
    import frontmatter

    # Build frontmatter data
    fm_data = {
        'id': task_data.get('id'),
        'title': task_data.get('title'),
        'project_id': task_data.get('project_id'),
        'repository_id': task_data.get('repository_id'),
        'category': task_data.get('category'),
        'type': task_data.get('type'),
        'priority': task_data.get('priority'),
        'status': task_data.get('status'),
        'phase': task_data.get('phase'),
        'created_at': task_data.get('created_at'),
        'started_at': task_data.get('started_at'),
        'completed_at': task_data.get('completed_at'),
        'git_branch': task_data.get('git_branch'),
        'tmux_session': task_data.get('tmux_session'),
        'agent_type': task_data.get('agent_type'),
        'commits': task_data.get('commits', 0),
    }

    # Build body
    title = task_data.get('title', 'Untitled Task')
    description = task_data.get('description', '')
    body = f"# {title}\n\n{description}"

    post = frontmatter.Post(body, **fm_data)
    return frontmatter.dumps(post)


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

    # Update task status (check if markdown or database)
    task_data = database.get_task(task_id)
    if task_data and task_data.get('source') == 'markdown':
        # Update markdown task
        updates = {
            'status': 'running',
            'phase': 'planning',
            'started_at': datetime.now().isoformat(),
            'git_branch': branch,
            'tmux_session': session,
            'agent_type': agent_type or 'claude-code'
        }
        update_markdown_task(task_id, updates)
    else:
        # Update database task
        database.update_task_status(
            task_id=task_id,
            status='running',
            phase='planning',
            started_at=int(datetime.now().timestamp()),
            git_branch=branch,
            tmux_session=session,
            agent_type=agent_type or 'claude-code'
        )

    # Copy task file to working directory
    copy_task_file_to_workdir(task_id, work_dir)

    # Log event
    database.add_event(task_id, 'task_started', {'branch': branch, 'session': session})

    return task


def pause_task(task_id: str):
    """Pause a running task"""
    task_data = database.get_task(task_id)
    if task_data and task_data.get('source') == 'markdown':
        update_markdown_task(task_id, {'status': 'paused'})
    else:
        database.update_task_status(task_id, 'paused')
    database.add_event(task_id, 'task_paused')


def resume_task(task_id: str):
    """Resume a paused task"""
    task_data = database.get_task(task_id)
    if task_data and task_data.get('source') == 'markdown':
        update_markdown_task(task_id, {'status': 'running'})
    else:
        database.update_task_status(task_id, 'running')
    database.add_event(task_id, 'task_resumed')


def complete_task(task_id: str):
    """Mark a task as complete"""
    task_data = database.get_task(task_id)
    if task_data and task_data.get('source') == 'markdown':
        updates = {
            'status': 'completed',
            'completed_at': datetime.now().isoformat()
        }
        update_markdown_task(task_id, updates)
    else:
        database.update_task_status(
            task_id,
            'completed',
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
