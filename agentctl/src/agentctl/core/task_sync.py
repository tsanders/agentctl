"""Task synchronization between markdown files and database for agentctl"""

from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

from agentctl.core import database, task_md


@dataclass
class SyncResult:
    """Result of a sync operation"""
    synced_count: int
    error_count: int
    errors: List[str]
    files_removed: int = 0


def sync_project_tasks(project_id: str) -> SyncResult:
    """
    Sync markdown task files for a project to database

    Args:
        project_id: Project ID to sync

    Returns:
        SyncResult with sync statistics
    """
    synced_count = 0
    error_count = 0
    errors = []
    files_removed = 0

    # Get project info
    project = database.get_project(project_id)
    if not project:
        return SyncResult(0, 1, [f"Project {project_id} not found"], 0)

    tasks_path_str = project.get('tasks_path')
    if not tasks_path_str:
        # Project doesn't have tasks_path configured - not an error, just skip
        return SyncResult(0, 0, [], 0)

    tasks_path = Path(tasks_path_str)
    if not tasks_path.exists():
        error_msg = f"Tasks path does not exist: {tasks_path}"
        database.add_sync_error(project_id, str(tasks_path), error_msg)
        return SyncResult(0, 1, [error_msg], 0)

    # Clear old sync errors for this project
    database.clear_sync_errors(project_id)

    # Get all .md files in tasks_path
    md_files = list(tasks_path.glob("*.md"))

    # Track which task IDs we've seen from markdown files
    seen_task_ids = set()

    for md_file in md_files:
        task_data, body, parse_errors = task_md.parse_task_file(md_file)

        if parse_errors:
            # Log error and continue
            error_msg = f"{md_file.name}: {'; '.join(parse_errors)}"
            database.add_sync_error(project_id, str(md_file), error_msg)
            errors.append(error_msg)
            error_count += 1
            continue

        # Validate this task belongs to the project
        if task_data['project_id'] != project_id:
            error_msg = f"{md_file.name}: project_id '{task_data['project_id']}' doesn't match project '{project_id}'"
            database.add_sync_error(project_id, str(md_file), error_msg)
            errors.append(error_msg)
            error_count += 1
            continue

        # Convert ISO timestamps to Unix timestamps for database
        task_data_for_db = _convert_timestamps_to_unix(task_data)

        # Upsert to database (only indexed fields)
        try:
            _upsert_task_to_database(task_data_for_db)
            seen_task_ids.add(task_data['id'])
            synced_count += 1
        except Exception as e:
            error_msg = f"{md_file.name}: Database error: {str(e)}"
            database.add_sync_error(project_id, str(md_file), error_msg)
            errors.append(error_msg)
            error_count += 1

    # Remove markdown tasks from database that no longer have files
    files_removed = _remove_orphaned_tasks(project_id, seen_task_ids)

    return SyncResult(synced_count, error_count, errors, files_removed)


def sync_all_tasks() -> Dict[str, SyncResult]:
    """
    Sync all projects with configured tasks_path

    Returns:
        Dictionary mapping project_id to SyncResult
    """
    results = {}

    projects = database.list_projects()

    for project in projects:
        project_id = project['id']
        if project.get('tasks_path'):
            results[project_id] = sync_project_tasks(project_id)

    return results


def _convert_timestamps_to_unix(task_data: Dict) -> Dict:
    """
    Convert ISO 8601 timestamps to Unix timestamps for database storage

    Args:
        task_data: Task data with ISO timestamps

    Returns:
        Task data with Unix timestamps
    """
    result = task_data.copy()

    timestamp_fields = ['created_at', 'started_at', 'completed_at']

    for field in timestamp_fields:
        if field in result and result[field] is not None:
            try:
                dt = datetime.fromisoformat(str(result[field]))
                result[field] = int(dt.timestamp())
            except (ValueError, TypeError):
                result[field] = None

    return result


def _convert_timestamps_to_iso(task_data: Dict) -> Dict:
    """
    Convert Unix timestamps to ISO 8601 format for markdown files

    Args:
        task_data: Task data with Unix timestamps

    Returns:
        Task data with ISO timestamps
    """
    result = task_data.copy()

    timestamp_fields = ['created_at', 'started_at', 'completed_at']

    for field in timestamp_fields:
        if field in result and result[field] is not None:
            try:
                dt = datetime.fromtimestamp(int(result[field]))
                result[field] = dt.isoformat()
            except (ValueError, TypeError):
                result[field] = None

    return result


def _upsert_task_to_database(task_data: Dict) -> None:
    """
    Insert or update task in database (indexed fields only)

    Args:
        task_data: Task data dictionary
    """
    conn = database.get_connection()
    cursor = conn.cursor()

    # Only store indexed fields in database
    cursor.execute("""
        INSERT OR REPLACE INTO tasks (
            id, project_id, repository_id, category, status, priority, source,
            title, type, description, phase, created_at, started_at, completed_at,
            git_branch, worktree_path, tmux_session, agent_type, commits
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        task_data['id'],
        task_data['project_id'],
        task_data.get('repository_id'),
        task_data['category'],
        task_data['status'],
        task_data['priority'],
        'markdown',  # source
        task_data['title'],
        task_data.get('type'),
        task_data.get('description'),
        task_data.get('phase'),
        task_data.get('created_at'),
        task_data.get('started_at'),
        task_data.get('completed_at'),
        task_data.get('git_branch'),
        task_data.get('worktree_path'),
        task_data.get('tmux_session'),
        task_data.get('agent_type'),
        task_data.get('commits', 0)
    ))

    conn.commit()
    conn.close()


def _remove_orphaned_tasks(project_id: str, seen_task_ids: set) -> int:
    """
    Remove markdown tasks from database that no longer have files

    Args:
        project_id: Project ID
        seen_task_ids: Set of task IDs found in markdown files

    Returns:
        Number of tasks removed
    """
    conn = database.get_connection()
    cursor = conn.cursor()

    # Get all markdown tasks for this project
    cursor.execute("""
        SELECT id FROM tasks
        WHERE project_id = ? AND source = 'markdown'
    """, (project_id,))

    db_task_ids = {row['id'] for row in cursor.fetchall()}

    # Find tasks in DB but not in files
    orphaned = db_task_ids - seen_task_ids

    if orphaned:
        placeholders = ','.join('?' * len(orphaned))
        cursor.execute(f"""
            DELETE FROM tasks
            WHERE id IN ({placeholders}) AND source = 'markdown'
        """, list(orphaned))

        conn.commit()

    removed_count = len(orphaned)
    conn.close()

    return removed_count


def get_task_from_markdown(task_id: str) -> Optional[Dict]:
    """
    Get full task data from markdown file

    Args:
        task_id: Task ID

    Returns:
        Task data dictionary or None if not found
    """
    # First get task from database to find project and verify it's a markdown task
    task = database.get_task(task_id)

    if not task or task.get('source') != 'markdown':
        return None

    # Get project to find tasks_path
    project = database.get_project(task['project_id'])
    if not project or not project.get('tasks_path'):
        return None

    tasks_path = Path(project['tasks_path'])
    task_file = tasks_path / f"{task_id}.md"

    if not task_file.exists():
        return None

    # Parse markdown file
    task_data, body, errors = task_md.parse_task_file(task_file)

    if errors:
        return None

    # Add the markdown body to task data
    task_data['markdown_body'] = body

    return task_data
