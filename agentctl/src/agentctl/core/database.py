"""Database operations for agentctl"""

import sqlite3
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import json

DB_PATH = Path.home() / ".agentctl" / "agentctl.db"


def init_db():
    """Initialize database schema"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            default_repository_id TEXT,
            tasks_path TEXT,
            created_at INTEGER NOT NULL,
            metadata TEXT
        );

        CREATE TABLE IF NOT EXISTS repositories (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            default_branch TEXT DEFAULT 'main',
            created_at INTEGER NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            repository_id TEXT,
            category TEXT NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            agent_status TEXT NOT NULL DEFAULT 'queued',
            priority TEXT NOT NULL DEFAULT 'medium',
            phase TEXT,
            created_at INTEGER NOT NULL,
            started_at INTEGER,
            completed_at INTEGER,
            tmux_session TEXT,
            git_branch TEXT,
            worktree_path TEXT,
            agent_type TEXT,
            commits INTEGER DEFAULT 0,
            source TEXT DEFAULT 'database',
            metadata TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (repository_id) REFERENCES repositories(id)
        );

        CREATE TABLE IF NOT EXISTS task_sync_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            error_message TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            data TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        );

        CREATE TABLE IF NOT EXISTS checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            state TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        );

        CREATE INDEX IF NOT EXISTS idx_tasks_agent_status ON tasks(agent_status);
        CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
        CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_source ON tasks(source);
        CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_repositories_project ON repositories(project_id);
        CREATE INDEX IF NOT EXISTS idx_sync_errors_project ON task_sync_errors(project_id);

        -- Session analytics tables
        CREATE TABLE IF NOT EXISTS session_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            session_name TEXT NOT NULL,
            log_file TEXT NOT NULL,
            captured_at INTEGER NOT NULL,
            parsed_at INTEGER,
            total_tool_calls INTEGER DEFAULT 0,
            total_file_operations INTEGER DEFAULT 0,
            total_commands INTEGER DEFAULT 0,
            total_errors INTEGER DEFAULT 0,
            tool_counts TEXT,  -- JSON object
            files_read TEXT,   -- JSON array
            files_written TEXT,  -- JSON array
            files_edited TEXT,  -- JSON array
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        );

        CREATE TABLE IF NOT EXISTS tool_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_log_id INTEGER NOT NULL,
            task_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            call_count INTEGER DEFAULT 1,
            success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            FOREIGN KEY (session_log_id) REFERENCES session_logs(id),
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        );

        CREATE TABLE IF NOT EXISTS file_operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_log_id INTEGER NOT NULL,
            task_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            operation TEXT NOT NULL,  -- read, write, edit, create, delete
            timestamp INTEGER,
            lines_affected INTEGER,
            FOREIGN KEY (session_log_id) REFERENCES session_logs(id),
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        );

        CREATE TABLE IF NOT EXISTS command_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_log_id INTEGER NOT NULL,
            task_id TEXT NOT NULL,
            command TEXT NOT NULL,
            exit_code INTEGER,
            duration_ms INTEGER,
            timestamp INTEGER,
            FOREIGN KEY (session_log_id) REFERENCES session_logs(id),
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        );

        CREATE TABLE IF NOT EXISTS session_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_log_id INTEGER NOT NULL,
            task_id TEXT NOT NULL,
            error_type TEXT NOT NULL,
            error_message TEXT NOT NULL,
            timestamp INTEGER,
            resolved INTEGER DEFAULT 0,
            FOREIGN KEY (session_log_id) REFERENCES session_logs(id),
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        );

        CREATE TABLE IF NOT EXISTS user_prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_log_id INTEGER NOT NULL,
            task_id TEXT NOT NULL,
            prompt TEXT NOT NULL,
            prompt_type TEXT NOT NULL,  -- message, command, file_reference, interrupt
            prompt_order INTEGER DEFAULT 0,
            timestamp INTEGER,
            FOREIGN KEY (session_log_id) REFERENCES session_logs(id),
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        );

        CREATE INDEX IF NOT EXISTS idx_session_logs_task ON session_logs(task_id);
        CREATE INDEX IF NOT EXISTS idx_tool_usage_task ON tool_usage(task_id);
        CREATE INDEX IF NOT EXISTS idx_tool_usage_tool ON tool_usage(tool_name);
        CREATE INDEX IF NOT EXISTS idx_file_operations_task ON file_operations(task_id);
        CREATE INDEX IF NOT EXISTS idx_file_operations_path ON file_operations(file_path);
        CREATE INDEX IF NOT EXISTS idx_command_executions_task ON command_executions(task_id);
        CREATE INDEX IF NOT EXISTS idx_session_errors_task ON session_errors(task_id);
        CREATE INDEX IF NOT EXISTS idx_user_prompts_task ON user_prompts(task_id);
        CREATE INDEX IF NOT EXISTS idx_user_prompts_session ON user_prompts(session_log_id);
    """)

    conn.commit()
    conn.close()


def get_connection():
    """Get database connection"""
    if not DB_PATH.exists():
        init_db()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_active_agents() -> List[Dict]:
    """Get all active agents"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            t.id as task_id,
            p.name as project,
            t.agent_status,
            t.phase,
            t.agent_type,
            t.commits,
            t.tmux_session,
            CAST((julianday('now') - julianday(t.started_at, 'unixepoch')) * 24 * 60 AS INTEGER) as elapsed_minutes
        FROM tasks t
        LEFT JOIN projects p ON t.project_id = p.id
        WHERE t.agent_status IN ('running', 'blocked')
        ORDER BY t.started_at DESC
    """)

    agents = []
    for row in cursor.fetchall():
        elapsed_minutes = row['elapsed_minutes'] or 0
        elapsed = f"{elapsed_minutes // 60}h {elapsed_minutes % 60}m"
        agents.append({
            'task_id': row['task_id'],
            'project': row['project'],
            'agent_status': row['agent_status'],
            'phase': row['phase'] or 'unknown',
            'agent_type': row['agent_type'] or 'unknown',
            'commits': row['commits'] or 0,
            'tmux_session': row['tmux_session'],
            'elapsed': elapsed
        })

    conn.close()
    return agents


def get_queued_tasks() -> List[Dict]:
    """Get queued tasks ordered by priority"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT t.id, p.name as project, t.category, t.priority, t.title
        FROM tasks t
        LEFT JOIN projects p ON t.project_id = p.id
        WHERE t.agent_status = 'queued'
        ORDER BY
            CASE t.priority
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                WHEN 'low' THEN 3
            END,
            t.created_at ASC
    """)

    tasks = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return tasks


def query_tasks(
    agent_status: Optional[str] = None,
    priority: Optional[str] = None,
    project: Optional[str] = None
) -> List[Dict]:
    """Query tasks with filters"""
    conn = get_connection()
    cursor = conn.cursor()

    conditions = []
    params = []

    if agent_status:
        conditions.append("t.agent_status = ?")
        params.append(agent_status)
    if priority:
        conditions.append("t.priority = ?")
        params.append(priority)
    if project:
        conditions.append("t.project_id = ?")
        params.append(project)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    cursor.execute(f"""
        SELECT
            t.id as task_id,
            t.title,
            t.agent_status,
            t.priority,
            t.phase,
            CAST((julianday('now') - julianday(t.started_at, 'unixepoch')) * 24 * 60 AS INTEGER) as waiting_minutes
        FROM tasks t
        WHERE {where_clause}
        ORDER BY t.created_at DESC
    """, params)

    tasks = []
    for row in cursor.fetchall():
        task = dict(row)
        if task['waiting_minutes']:
            task['waiting_time'] = f"{task['waiting_minutes'] // 60}h {task['waiting_minutes'] % 60}m"
        else:
            task['waiting_time'] = None
        tasks.append(task)

    conn.close()
    return tasks


def add_event(task_id: str, event_type: str, data: Optional[Dict] = None):
    """Add an event to the log"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO events (task_id, event_type, timestamp, data)
        VALUES (?, ?, ?, ?)
    """, (task_id, event_type, int(datetime.now().timestamp()), json.dumps(data or {})))

    conn.commit()
    conn.close()


def get_recent_events(limit: int = 10) -> List[Dict]:
    """Get recent events"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT task_id, event_type, timestamp, data
        FROM events
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,))

    events = []
    for row in cursor.fetchall():
        events.append({
            'task_id': row['task_id'],
            'type': row['event_type'],
            'timestamp': datetime.fromtimestamp(row['timestamp']),
            'data': json.loads(row['data'])
        })

    conn.close()
    return events


def create_task(
    task_id: str,
    project_id: str,
    category: str,
    task_type: str,
    title: str,
    description: Optional[str] = None,
    priority: str = "medium",
    repository_id: Optional[str] = None
) -> None:
    """Create a new task in the database"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO tasks (id, project_id, repository_id, category, type, title, description, priority, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (task_id, project_id, repository_id, category, task_type, title, description, priority, int(datetime.now().timestamp())))

    conn.commit()
    conn.close()


def get_task(task_id: str) -> Optional[Dict]:
    """Get a task by ID"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def update_task_status(task_id: str, agent_status: str, **kwargs):
    """Update task agent_status and optional fields"""
    conn = get_connection()
    cursor = conn.cursor()

    set_clauses = ["agent_status = ?"]
    params = [agent_status]

    for key, value in kwargs.items():
        set_clauses.append(f"{key} = ?")
        params.append(value)

    params.append(task_id)

    query = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ?"
    cursor.execute(query, params)

    conn.commit()
    conn.close()


def update_task(task_id: str, **fields) -> None:
    """Update task fields (any provided fields are updated)"""
    conn = get_connection()
    cursor = conn.cursor()

    if not fields:
        conn.close()
        return

    set_clauses = []
    params = []

    for key, value in fields.items():
        set_clauses.append(f"{key} = ?")
        params.append(value)

    params.append(task_id)

    query = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ?"
    cursor.execute(query, params)

    conn.commit()
    conn.close()


def delete_task(task_id: str) -> None:
    """Delete a task"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    conn.commit()
    conn.close()


def list_all_tasks(agent_status: Optional[str] = None, priority: Optional[str] = None) -> List[Dict]:
    """List all tasks with optional filters, joined with project and repository info"""
    conn = get_connection()
    cursor = conn.cursor()

    conditions = []
    params = []

    if agent_status:
        conditions.append("t.agent_status = ?")
        params.append(agent_status)
    if priority:
        conditions.append("t.priority = ?")
        params.append(priority)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    cursor.execute(f"""
        SELECT
            t.id as task_id,
            t.title,
            t.description,
            t.agent_status,
            t.priority,
            t.category,
            t.type,
            t.phase,
            t.created_at,
            t.started_at,
            t.completed_at,
            t.tmux_session,
            t.git_branch,
            t.worktree_path,
            t.agent_type,
            t.commits,
            t.source,
            p.id as project_id,
            p.name as project_name,
            r.id as repository_id,
            r.name as repository_name,
            r.path as repository_path
        FROM tasks t
        LEFT JOIN projects p ON t.project_id = p.id
        LEFT JOIN repositories r ON t.repository_id = r.id
        WHERE {where_clause}
        ORDER BY t.created_at DESC
    """, params)

    tasks = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return tasks


def get_task_with_details(task_id: str) -> Optional[Dict]:
    """Get a task with full project and repository details"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            t.*,
            p.name as project_name,
            r.name as repository_name,
            r.path as repository_path,
            r.default_branch as repository_default_branch
        FROM tasks t
        LEFT JOIN projects p ON t.project_id = p.id
        LEFT JOIN repositories r ON t.repository_id = r.id
        WHERE t.id = ?
    """, (task_id,))

    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


# Project management functions

def create_project(
    project_id: str,
    name: str,
    description: Optional[str] = None,
    tasks_path: Optional[str] = None
) -> None:
    """Create a new project"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO projects (id, name, description, tasks_path, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (project_id, name, description, tasks_path, int(datetime.now().timestamp())))

    conn.commit()
    conn.close()


def get_project(project_id: str) -> Optional[Dict]:
    """Get a project by ID"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def list_projects() -> List[Dict]:
    """List all projects"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM projects ORDER BY created_at DESC")
    projects = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return projects


def update_project(
    project_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    default_repository_id: Optional[str] = None,
    tasks_path: Optional[str] = None
) -> None:
    """Update project fields (only provided fields are updated)"""
    conn = get_connection()
    cursor = conn.cursor()

    updates = []
    params = []

    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if default_repository_id is not None:
        updates.append("default_repository_id = ?")
        params.append(default_repository_id)
    if tasks_path is not None:
        updates.append("tasks_path = ?")
        params.append(tasks_path)

    if not updates:
        conn.close()
        return

    params.append(project_id)
    query = f"UPDATE projects SET {', '.join(updates)} WHERE id = ?"
    cursor.execute(query, params)

    conn.commit()
    conn.close()


# Repository management functions

def create_repository(
    repository_id: str,
    project_id: str,
    name: str,
    path: str,
    default_branch: str = "main"
) -> None:
    """Create a new repository"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO repositories (id, project_id, name, path, default_branch, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (repository_id, project_id, name, path, default_branch, int(datetime.now().timestamp())))

    conn.commit()
    conn.close()


def get_repository(repository_id: str) -> Optional[Dict]:
    """Get a repository by ID"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM repositories WHERE id = ?", (repository_id,))
    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def list_repositories(project_id: Optional[str] = None) -> List[Dict]:
    """List repositories, optionally filtered by project"""
    conn = get_connection()
    cursor = conn.cursor()

    if project_id:
        cursor.execute("""
            SELECT * FROM repositories
            WHERE project_id = ?
            ORDER BY created_at DESC
        """, (project_id,))
    else:
        cursor.execute("SELECT * FROM repositories ORDER BY created_at DESC")

    repositories = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return repositories


def update_repository(
    repository_id: str,
    name: Optional[str] = None,
    path: Optional[str] = None,
    default_branch: Optional[str] = None
) -> None:
    """Update repository fields (only provided fields are updated)"""
    conn = get_connection()
    cursor = conn.cursor()

    updates = []
    params = []

    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if path is not None:
        updates.append("path = ?")
        params.append(path)
    if default_branch is not None:
        updates.append("default_branch = ?")
        params.append(default_branch)

    if not updates:
        conn.close()
        return

    params.append(repository_id)
    query = f"UPDATE repositories SET {', '.join(updates)} WHERE id = ?"
    cursor.execute(query, params)

    conn.commit()
    conn.close()


# Task sync error management functions

def add_sync_error(project_id: str, file_path: str, error_message: str) -> None:
    """Add a task sync error"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO task_sync_errors (project_id, file_path, error_message, timestamp)
        VALUES (?, ?, ?, ?)
    """, (project_id, file_path, error_message, int(datetime.now().timestamp())))

    conn.commit()
    conn.close()


def get_sync_errors(project_id: Optional[str] = None) -> List[Dict]:
    """Get sync errors, optionally filtered by project"""
    conn = get_connection()
    cursor = conn.cursor()

    if project_id:
        cursor.execute("""
            SELECT * FROM task_sync_errors
            WHERE project_id = ?
            ORDER BY timestamp DESC
        """, (project_id,))
    else:
        cursor.execute("SELECT * FROM task_sync_errors ORDER BY timestamp DESC")

    errors = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return errors


def clear_sync_errors(project_id: Optional[str] = None) -> None:
    """Clear sync errors, optionally for a specific project"""
    conn = get_connection()
    cursor = conn.cursor()

    if project_id:
        cursor.execute("DELETE FROM task_sync_errors WHERE project_id = ?", (project_id,))
    else:
        cursor.execute("DELETE FROM task_sync_errors")

    conn.commit()
    conn.close()


# Session analytics functions

def save_session_analytics(
    task_id: str,
    session_name: str,
    log_file: str,
    metrics: 'SessionMetrics'
) -> int:
    """Save parsed session analytics to database.

    Args:
        task_id: Task ID
        session_name: tmux session name
        log_file: Path to the log file
        metrics: Parsed SessionMetrics object

    Returns:
        session_log_id for the inserted record
    """
    conn = get_connection()
    cursor = conn.cursor()

    now = int(datetime.now().timestamp())

    # Insert session log
    cursor.execute("""
        INSERT INTO session_logs (
            task_id, session_name, log_file, captured_at, parsed_at,
            total_tool_calls, total_file_operations, total_commands, total_errors,
            tool_counts, files_read, files_written, files_edited
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        task_id, session_name, log_file, now, now,
        metrics.total_tool_calls, metrics.total_file_operations,
        metrics.total_commands, metrics.total_errors,
        json.dumps(metrics.tool_counts),
        json.dumps(metrics.files_read),
        json.dumps(metrics.files_written),
        json.dumps(metrics.files_edited)
    ))

    session_log_id = cursor.lastrowid

    # Insert tool usage
    for tool_name, count in metrics.tool_counts.items():
        cursor.execute("""
            INSERT INTO tool_usage (session_log_id, task_id, tool_name, call_count)
            VALUES (?, ?, ?, ?)
        """, (session_log_id, task_id, tool_name, count))

    # Insert file operations
    for op in metrics.file_operations:
        cursor.execute("""
            INSERT INTO file_operations (session_log_id, task_id, file_path, operation, lines_affected)
            VALUES (?, ?, ?, ?, ?)
        """, (session_log_id, task_id, op.file_path, op.operation, op.lines_affected))

    # Insert commands
    for cmd in metrics.commands:
        cursor.execute("""
            INSERT INTO command_executions (session_log_id, task_id, command, exit_code, duration_ms)
            VALUES (?, ?, ?, ?, ?)
        """, (session_log_id, task_id, cmd.command, cmd.exit_code, cmd.duration_ms))

    # Insert errors
    for err in metrics.errors:
        cursor.execute("""
            INSERT INTO session_errors (session_log_id, task_id, error_type, error_message, resolved)
            VALUES (?, ?, ?, ?, ?)
        """, (session_log_id, task_id, err.error_type, err.message, 1 if err.resolved else 0))

    # Insert user prompts
    for prompt in metrics.user_prompts:
        cursor.execute("""
            INSERT INTO user_prompts (session_log_id, task_id, prompt, prompt_type, prompt_order)
            VALUES (?, ?, ?, ?, ?)
        """, (session_log_id, task_id, prompt.prompt, prompt.prompt_type, prompt.order))

    conn.commit()
    conn.close()

    return session_log_id


def get_session_logs_for_task(task_id: str) -> List[Dict]:
    """Get all session logs for a task."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM session_logs
        WHERE task_id = ?
        ORDER BY captured_at DESC
    """, (task_id,))

    logs = []
    for row in cursor.fetchall():
        log = dict(row)
        # Parse JSON fields
        if log.get('tool_counts'):
            log['tool_counts'] = json.loads(log['tool_counts'])
        if log.get('files_read'):
            log['files_read'] = json.loads(log['files_read'])
        if log.get('files_written'):
            log['files_written'] = json.loads(log['files_written'])
        if log.get('files_edited'):
            log['files_edited'] = json.loads(log['files_edited'])
        logs.append(log)

    conn.close()
    return logs


def get_tool_usage_stats(task_id: Optional[str] = None) -> List[Dict]:
    """Get aggregated tool usage statistics.

    Args:
        task_id: Optional task ID to filter by

    Returns:
        List of dicts with tool_name and total usage counts
    """
    conn = get_connection()
    cursor = conn.cursor()

    if task_id:
        cursor.execute("""
            SELECT tool_name, SUM(call_count) as total_calls
            FROM tool_usage
            WHERE task_id = ?
            GROUP BY tool_name
            ORDER BY total_calls DESC
        """, (task_id,))
    else:
        cursor.execute("""
            SELECT tool_name, SUM(call_count) as total_calls
            FROM tool_usage
            GROUP BY tool_name
            ORDER BY total_calls DESC
        """)

    stats = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return stats


def get_file_activity_stats(task_id: Optional[str] = None, limit: int = 20) -> List[Dict]:
    """Get most frequently accessed files.

    Args:
        task_id: Optional task ID to filter by
        limit: Maximum number of files to return

    Returns:
        List of dicts with file_path, operation counts
    """
    conn = get_connection()
    cursor = conn.cursor()

    if task_id:
        cursor.execute("""
            SELECT file_path,
                   COUNT(*) as total_operations,
                   SUM(CASE WHEN operation = 'read' THEN 1 ELSE 0 END) as reads,
                   SUM(CASE WHEN operation = 'write' THEN 1 ELSE 0 END) as writes,
                   SUM(CASE WHEN operation = 'edit' THEN 1 ELSE 0 END) as edits
            FROM file_operations
            WHERE task_id = ?
            GROUP BY file_path
            ORDER BY total_operations DESC
            LIMIT ?
        """, (task_id, limit))
    else:
        cursor.execute("""
            SELECT file_path,
                   COUNT(*) as total_operations,
                   SUM(CASE WHEN operation = 'read' THEN 1 ELSE 0 END) as reads,
                   SUM(CASE WHEN operation = 'write' THEN 1 ELSE 0 END) as writes,
                   SUM(CASE WHEN operation = 'edit' THEN 1 ELSE 0 END) as edits
            FROM file_operations
            GROUP BY file_path
            ORDER BY total_operations DESC
            LIMIT ?
        """, (limit,))

    stats = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return stats


def get_error_stats(task_id: Optional[str] = None) -> List[Dict]:
    """Get error statistics by type.

    Args:
        task_id: Optional task ID to filter by

    Returns:
        List of dicts with error_type and count
    """
    conn = get_connection()
    cursor = conn.cursor()

    if task_id:
        cursor.execute("""
            SELECT error_type, COUNT(*) as count
            FROM session_errors
            WHERE task_id = ?
            GROUP BY error_type
            ORDER BY count DESC
        """, (task_id,))
    else:
        cursor.execute("""
            SELECT error_type, COUNT(*) as count
            FROM session_errors
            GROUP BY error_type
            ORDER BY count DESC
        """)

    stats = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return stats


def get_user_prompts(task_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
    """Get user prompts, optionally filtered by task.

    Args:
        task_id: Optional task ID to filter by
        limit: Maximum number of prompts to return

    Returns:
        List of dicts with prompt info
    """
    conn = get_connection()
    cursor = conn.cursor()

    if task_id:
        cursor.execute("""
            SELECT up.*, sl.session_name
            FROM user_prompts up
            JOIN session_logs sl ON up.session_log_id = sl.id
            WHERE up.task_id = ?
            ORDER BY sl.captured_at DESC, up.prompt_order ASC
            LIMIT ?
        """, (task_id, limit))
    else:
        cursor.execute("""
            SELECT up.*, sl.session_name
            FROM user_prompts up
            JOIN session_logs sl ON up.session_log_id = sl.id
            ORDER BY sl.captured_at DESC, up.prompt_order ASC
            LIMIT ?
        """, (limit,))

    prompts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return prompts


def get_user_prompt_stats(task_id: Optional[str] = None) -> Dict:
    """Get statistics about user prompts.

    Args:
        task_id: Optional task ID to filter by

    Returns:
        Dict with prompt statistics
    """
    conn = get_connection()
    cursor = conn.cursor()

    if task_id:
        cursor.execute("""
            SELECT
                COUNT(*) as total_prompts,
                SUM(CASE WHEN prompt_type = 'message' THEN 1 ELSE 0 END) as messages,
                SUM(CASE WHEN prompt_type = 'command' THEN 1 ELSE 0 END) as commands,
                SUM(CASE WHEN prompt_type = 'file_reference' THEN 1 ELSE 0 END) as file_refs,
                SUM(CASE WHEN prompt_type = 'interrupt' THEN 1 ELSE 0 END) as interrupts
            FROM user_prompts
            WHERE task_id = ?
        """, (task_id,))
    else:
        cursor.execute("""
            SELECT
                COUNT(*) as total_prompts,
                SUM(CASE WHEN prompt_type = 'message' THEN 1 ELSE 0 END) as messages,
                SUM(CASE WHEN prompt_type = 'command' THEN 1 ELSE 0 END) as commands,
                SUM(CASE WHEN prompt_type = 'file_reference' THEN 1 ELSE 0 END) as file_refs,
                SUM(CASE WHEN prompt_type = 'interrupt' THEN 1 ELSE 0 END) as interrupts
            FROM user_prompts
        """)

    row = cursor.fetchone()
    conn.close()

    return {
        'total_prompts': row['total_prompts'] or 0,
        'messages': row['messages'] or 0,
        'commands': row['commands'] or 0,
        'file_references': row['file_refs'] or 0,
        'interrupts': row['interrupts'] or 0,
    }


def get_analytics_summary() -> Dict:
    """Get overall analytics summary across all sessions."""
    conn = get_connection()
    cursor = conn.cursor()

    # Total sessions
    cursor.execute("SELECT COUNT(*) as count FROM session_logs")
    total_sessions = cursor.fetchone()['count']

    # Total metrics
    cursor.execute("""
        SELECT
            SUM(total_tool_calls) as total_tools,
            SUM(total_file_operations) as total_files,
            SUM(total_commands) as total_commands,
            SUM(total_errors) as total_errors
        FROM session_logs
    """)
    row = cursor.fetchone()

    # Top tools
    cursor.execute("""
        SELECT tool_name, SUM(call_count) as total
        FROM tool_usage
        GROUP BY tool_name
        ORDER BY total DESC
        LIMIT 5
    """)
    top_tools = [dict(r) for r in cursor.fetchall()]

    # Recent errors
    cursor.execute("""
        SELECT task_id, error_type, error_message
        FROM session_errors
        ORDER BY id DESC
        LIMIT 5
    """)
    recent_errors = [dict(r) for r in cursor.fetchall()]

    # User prompt stats
    cursor.execute("""
        SELECT
            COUNT(*) as total_prompts,
            SUM(CASE WHEN prompt_type = 'message' THEN 1 ELSE 0 END) as messages,
            SUM(CASE WHEN prompt_type = 'command' THEN 1 ELSE 0 END) as commands,
            SUM(CASE WHEN prompt_type = 'file_reference' THEN 1 ELSE 0 END) as file_refs
        FROM user_prompts
    """)
    prompt_row = cursor.fetchone()

    # Recent user prompts
    cursor.execute("""
        SELECT task_id, prompt, prompt_type
        FROM user_prompts
        WHERE prompt_type = 'message'
        ORDER BY id DESC
        LIMIT 10
    """)
    recent_prompts = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return {
        'total_sessions': total_sessions,
        'total_tool_calls': row['total_tools'] or 0,
        'total_file_operations': row['total_files'] or 0,
        'total_commands': row['total_commands'] or 0,
        'total_errors': row['total_errors'] or 0,
        'top_tools': top_tools,
        'recent_errors': recent_errors,
        'total_user_prompts': prompt_row['total_prompts'] or 0,
        'prompt_messages': prompt_row['messages'] or 0,
        'prompt_commands': prompt_row['commands'] or 0,
        'prompt_file_refs': prompt_row['file_refs'] or 0,
        'recent_prompts': recent_prompts,
    }
