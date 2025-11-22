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
            status TEXT NOT NULL DEFAULT 'queued',
            priority TEXT NOT NULL DEFAULT 'medium',
            phase TEXT,
            created_at INTEGER NOT NULL,
            started_at INTEGER,
            completed_at INTEGER,
            tmux_session TEXT,
            git_branch TEXT,
            agent_type TEXT,
            commits INTEGER DEFAULT 0,
            metadata TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (repository_id) REFERENCES repositories(id)
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

        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
        CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
        CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_repositories_project ON repositories(project_id);
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
            t.status,
            t.phase,
            t.agent_type,
            t.commits,
            t.tmux_session,
            CAST((julianday('now') - julianday(t.started_at, 'unixepoch')) * 24 * 60 AS INTEGER) as elapsed_minutes
        FROM tasks t
        LEFT JOIN projects p ON t.project_id = p.id
        WHERE t.status IN ('running', 'blocked')
        ORDER BY t.started_at DESC
    """)

    agents = []
    for row in cursor.fetchall():
        elapsed_minutes = row['elapsed_minutes'] or 0
        elapsed = f"{elapsed_minutes // 60}h {elapsed_minutes % 60}m"
        agents.append({
            'task_id': row['task_id'],
            'project': row['project'],
            'status': row['status'],
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
        WHERE t.status = 'queued'
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
    status: Optional[str] = None,
    priority: Optional[str] = None,
    project: Optional[str] = None
) -> List[Dict]:
    """Query tasks with filters"""
    conn = get_connection()
    cursor = conn.cursor()

    conditions = []
    params = []

    if status:
        conditions.append("t.status = ?")
        params.append(status)
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
            t.status,
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


def update_task_status(task_id: str, status: str, **kwargs):
    """Update task status and optional fields"""
    conn = get_connection()
    cursor = conn.cursor()

    set_clauses = ["status = ?"]
    params = [status]

    for key, value in kwargs.items():
        set_clauses.append(f"{key} = ?")
        params.append(value)

    params.append(task_id)

    query = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ?"
    cursor.execute(query, params)

    conn.commit()
    conn.close()


# Project management functions

def create_project(
    project_id: str,
    name: str,
    description: Optional[str] = None
) -> None:
    """Create a new project"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO projects (id, name, description, created_at)
        VALUES (?, ?, ?, ?)
    """, (project_id, name, description, int(datetime.now().timestamp())))

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
