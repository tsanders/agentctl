"""Markdown-only task storage for agentctl

This module provides task queries by reading markdown files directly.
No SQLite database is used for task data - markdown is the single source of truth.
"""

from pathlib import Path
from typing import Dict, List, Optional, Callable
from datetime import datetime

from agentctl.core import database
from agentctl.core.task_md import parse_task_file


def _calculate_elapsed(task_data: Dict) -> None:
    """Calculate and add elapsed time fields to task data in place."""
    started_at = task_data.get('started_at')
    if started_at:
        try:
            if isinstance(started_at, str):
                start_dt = datetime.fromisoformat(started_at)
            else:
                start_dt = datetime.fromtimestamp(started_at)
            elapsed = datetime.now() - start_dt
            hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
            minutes = remainder // 60
            task_data['elapsed'] = f"{hours}h {minutes}m"
            task_data['elapsed_minutes'] = int(elapsed.total_seconds() / 60)
        except (ValueError, TypeError):
            task_data['elapsed'] = '-'
            task_data['elapsed_minutes'] = 0
    else:
        task_data['elapsed'] = '-'
        task_data['elapsed_minutes'] = 0


def get_all_tasks(
    project_id: Optional[str] = None,
    agent_status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
) -> List[Dict]:
    """
    Get all tasks from markdown files with optional filtering.

    Args:
        project_id: Filter by project ID
        agent_status: Filter by agent_status (queued, running, blocked, completed, failed)
        priority: Filter by priority (high, medium, low)
        category: Filter by category (FEATURE, BUG, etc.)

    Returns:
        List of task dictionaries with all frontmatter fields preserved
    """
    tasks = []

    # Get all projects with tasks_path configured
    projects = database.list_projects()

    for project in projects:
        # Skip if filtering by project and this isn't it
        if project_id and project['id'] != project_id:
            continue

        tasks_path = project.get('tasks_path')
        if not tasks_path:
            continue

        tasks_dir = Path(tasks_path)
        if not tasks_dir.exists():
            continue

        # Read all markdown files in the tasks directory
        for md_file in tasks_dir.glob('*.md'):
            task_data, body, errors = parse_task_file(md_file)

            if errors or not task_data:
                continue

            # Apply filters
            if agent_status and task_data.get('agent_status') != agent_status:
                continue
            if priority and task_data.get('priority') != priority:
                continue
            if category and task_data.get('category') != category:
                continue

            # Add file path for reference
            task_data['_file_path'] = str(md_file)
            task_data['_markdown_body'] = body

            # Normalize field names for backwards compatibility
            task_data['task_id'] = task_data['id']

            # Add project info
            task_data['project_name'] = project.get('name', project['id'])
            task_data['project'] = task_data['project_name']

            # Add repository info if available
            if task_data.get('repository_id'):
                repo = database.get_repository(task_data['repository_id'])
                if repo:
                    task_data['repository_name'] = repo.get('name')
                    task_data['repository_path'] = repo.get('path')

            # Calculate elapsed time
            _calculate_elapsed(task_data)

            tasks.append(task_data)

    return tasks


def get_task(task_id: str) -> Optional[Dict]:
    """
    Get a single task by ID.

    Args:
        task_id: Task ID to find

    Returns:
        Task dictionary or None if not found
    """
    # Search all projects for this task
    projects = database.list_projects()

    for project in projects:
        tasks_path = project.get('tasks_path')
        if not tasks_path:
            continue

        task_file = Path(tasks_path) / f"{task_id}.md"
        if task_file.exists():
            task_data, body, errors = parse_task_file(task_file)
            if task_data and not errors:
                task_data['_file_path'] = str(task_file)
                task_data['_markdown_body'] = body

                # Normalize field names for backwards compatibility
                task_data['task_id'] = task_data['id']

                task_data['project_name'] = project.get('name', project['id'])
                task_data['project'] = task_data['project_name']

                # Add repository info
                if task_data.get('repository_id'):
                    repo = database.get_repository(task_data['repository_id'])
                    if repo:
                        task_data['repository_name'] = repo.get('name')
                        task_data['repository_path'] = repo.get('path')
                        task_data['default_branch'] = repo.get('default_branch', 'main')

                # Calculate elapsed time
                _calculate_elapsed(task_data)

                return task_data

    return None


def get_task_with_details(task_id: str) -> Optional[Dict]:
    """
    Get a task with full details including project and repository info.
    Alias for get_task() for API compatibility.
    """
    return get_task(task_id)


def get_active_agents() -> List[Dict]:
    """
    Get all tasks with agent_status 'running' or 'blocked'.

    Returns:
        List of active task dictionaries
    """
    tasks = get_all_tasks()
    active = []

    for task in tasks:
        status = task.get('agent_status', 'queued')
        if status in ('running', 'blocked'):
            # Ensure required fields have defaults
            task.setdefault('phase', 'unknown')
            task.setdefault('agent_type', 'unknown')
            task.setdefault('commits', 0)
            task.setdefault('tmux_session', None)

            active.append(task)

    # Sort by started_at (most recent first)
    active.sort(key=lambda t: t.get('started_at') or '', reverse=True)

    return active


def get_queued_tasks() -> List[Dict]:
    """
    Get all tasks with agent_status 'queued', sorted by priority.

    Returns:
        List of queued task dictionaries
    """
    tasks = get_all_tasks(agent_status='queued')

    # Sort by priority (high > medium > low) then by created_at
    priority_order = {'high': 0, 'medium': 1, 'low': 2}
    tasks.sort(key=lambda t: (
        priority_order.get(t.get('priority', 'medium'), 1),
        t.get('created_at', '')
    ))

    return tasks


def query_tasks(
    agent_status: Optional[str] = None,
    priority: Optional[str] = None,
    project: Optional[str] = None,
) -> List[Dict]:
    """
    Query tasks with filters. API compatible with old database.query_tasks().

    Args:
        agent_status: Filter by agent_status
        priority: Filter by priority
        project: Filter by project_id

    Returns:
        List of matching task dictionaries
    """
    return get_all_tasks(
        project_id=project,
        agent_status=agent_status,
        priority=priority
    )


def list_all_tasks(
    agent_status: Optional[str] = None,
    priority: Optional[str] = None,
) -> List[Dict]:
    """
    List all tasks with optional filters. API compatible with old database.list_all_tasks().
    """
    return get_all_tasks(agent_status=agent_status, priority=priority)


def update_task(task_id: str, updates: Dict) -> bool:
    """
    Update a task's frontmatter fields.

    Args:
        task_id: Task ID
        updates: Dictionary of fields to update

    Returns:
        True if successful, False otherwise
    """
    from agentctl.core.task_md import update_task_file

    task = get_task(task_id)
    if not task:
        return False

    file_path = Path(task['_file_path'])
    return update_task_file(file_path, updates)


def delete_task(task_id: str) -> bool:
    """
    Delete a task's markdown file.

    Args:
        task_id: Task ID

    Returns:
        True if successful, False otherwise
    """
    task = get_task(task_id)
    if not task:
        return False

    try:
        file_path = Path(task['_file_path'])
        file_path.unlink()
        return True
    except Exception:
        return False


def get_task_file_path(task_id: str) -> Optional[Path]:
    """
    Get the file path for a task.

    Args:
        task_id: Task ID

    Returns:
        Path to the task file, or None if not found
    """
    task = get_task(task_id)
    if task and '_file_path' in task:
        return Path(task['_file_path'])
    return None


def get_tasks_for_project(project_id: str) -> List[Dict]:
    """
    Get all tasks for a specific project.

    Args:
        project_id: Project ID

    Returns:
        List of task dictionaries
    """
    return get_all_tasks(project_id=project_id)
