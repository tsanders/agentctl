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
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            project TEXT NOT NULL,
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
            metadata TEXT
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
        CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
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
            id as task_id,
            project,
            status,
            phase,
            agent_type,
            commits,
            tmux_session,
            CAST((julianday('now') - julianday(started_at, 'unixepoch')) * 24 * 60 AS INTEGER) as elapsed_minutes
        FROM tasks
        WHERE status IN ('running', 'blocked')
        ORDER BY started_at DESC
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
        SELECT id, project, category, priority, title
        FROM tasks
        WHERE status = 'queued'
        ORDER BY
            CASE priority
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                WHEN 'low' THEN 3
            END,
            created_at ASC
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
        conditions.append("status = ?")
        params.append(status)
    if priority:
        conditions.append("priority = ?")
        params.append(priority)
    if project:
        conditions.append("project = ?")
        params.append(project)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    cursor.execute(f"""
        SELECT
            id as task_id,
            status,
            priority,
            phase,
            CAST((julianday('now') - julianday(started_at, 'unixepoch')) * 24 * 60 AS INTEGER) as waiting_minutes
        FROM tasks
        WHERE {where_clause}
        ORDER BY created_at DESC
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
    project: str,
    category: str,
    task_type: str,
    title: str,
    description: Optional[str] = None,
    priority: str = "medium"
) -> None:
    """Create a new task in the database"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO tasks (id, project, category, type, title, description, priority, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (task_id, project, category, task_type, title, description, priority, int(datetime.now().timestamp())))

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
