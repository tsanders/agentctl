"""Prompt library storage for agentctl

This module provides CRUD operations for the prompt library,
including saved prompts, history, and workflow suggestions.
"""

import uuid
from typing import Dict, List, Optional
from datetime import datetime

from agentctl.core.database import get_connection


# Prompt CRUD operations

def create_prompt(
    text: str,
    title: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[str] = None,
    phase: Optional[str] = None,
    is_bookmarked: bool = False,
) -> str:
    """Create a new prompt in the library.

    Args:
        text: The prompt content
        title: Optional short name
        category: Optional category (e.g., "debugging", "testing")
        tags: Optional comma-separated tags
        phase: Optional associated workflow phase
        is_bookmarked: Whether to bookmark this prompt

    Returns:
        The prompt ID
    """
    conn = get_connection()
    cursor = conn.cursor()

    prompt_id = str(uuid.uuid4())
    now = int(datetime.now().timestamp())

    cursor.execute("""
        INSERT INTO prompts (id, text, title, category, tags, phase, is_bookmarked, use_count, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
    """, (prompt_id, text, title, category, tags, phase, 1 if is_bookmarked else 0, now, now))

    conn.commit()
    conn.close()

    return prompt_id


def get_prompt(prompt_id: str) -> Optional[Dict]:
    """Get a prompt by ID.

    Args:
        prompt_id: The prompt ID

    Returns:
        Prompt dictionary or None if not found
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM prompts WHERE id = ?", (prompt_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return _row_to_prompt(row)
    return None


def update_prompt(
    prompt_id: str,
    text: Optional[str] = None,
    title: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[str] = None,
    phase: Optional[str] = None,
    is_bookmarked: Optional[bool] = None,
) -> bool:
    """Update a prompt's fields.

    Args:
        prompt_id: The prompt ID
        text: Optional new text
        title: Optional new title
        category: Optional new category
        tags: Optional new tags
        phase: Optional new phase
        is_bookmarked: Optional new bookmark status

    Returns:
        True if updated, False if prompt not found
    """
    conn = get_connection()
    cursor = conn.cursor()

    updates = ["updated_at = ?"]
    params = [int(datetime.now().timestamp())]

    if text is not None:
        updates.append("text = ?")
        params.append(text)
    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if category is not None:
        updates.append("category = ?")
        params.append(category)
    if tags is not None:
        updates.append("tags = ?")
        params.append(tags)
    if phase is not None:
        updates.append("phase = ?")
        params.append(phase)
    if is_bookmarked is not None:
        updates.append("is_bookmarked = ?")
        params.append(1 if is_bookmarked else 0)

    params.append(prompt_id)

    cursor.execute(f"UPDATE prompts SET {', '.join(updates)} WHERE id = ?", params)

    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()

    return updated


def delete_prompt(prompt_id: str) -> bool:
    """Delete a prompt.

    Args:
        prompt_id: The prompt ID

    Returns:
        True if deleted, False if not found
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))

    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()

    return deleted


def toggle_bookmark(prompt_id: str) -> Optional[bool]:
    """Toggle a prompt's bookmark status.

    Args:
        prompt_id: The prompt ID

    Returns:
        New bookmark status, or None if not found
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT is_bookmarked FROM prompts WHERE id = ?", (prompt_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return None

    new_status = 0 if row['is_bookmarked'] else 1

    cursor.execute("""
        UPDATE prompts SET is_bookmarked = ?, updated_at = ? WHERE id = ?
    """, (new_status, int(datetime.now().timestamp()), prompt_id))

    conn.commit()
    conn.close()

    return bool(new_status)


def increment_use_count(prompt_id: str) -> None:
    """Increment a prompt's use count.

    Args:
        prompt_id: The prompt ID
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE prompts SET use_count = use_count + 1, updated_at = ? WHERE id = ?
    """, (int(datetime.now().timestamp()), prompt_id))

    conn.commit()
    conn.close()


# Prompt query operations

def list_prompts(
    category: Optional[str] = None,
    phase: Optional[str] = None,
    is_bookmarked: Optional[bool] = None,
    search: Optional[str] = None,
    order_by: str = "updated_at",
    order_desc: bool = True,
    limit: int = 100,
) -> List[Dict]:
    """List prompts with optional filters.

    Args:
        category: Filter by category
        phase: Filter by phase
        is_bookmarked: Filter by bookmark status
        search: Search in text and title
        order_by: Column to order by (updated_at, use_count, title)
        order_desc: Whether to order descending
        limit: Maximum number of results

    Returns:
        List of prompt dictionaries
    """
    conn = get_connection()
    cursor = conn.cursor()

    conditions = []
    params = []

    if category:
        conditions.append("category = ?")
        params.append(category)
    if phase:
        conditions.append("phase = ?")
        params.append(phase)
    if is_bookmarked is not None:
        conditions.append("is_bookmarked = ?")
        params.append(1 if is_bookmarked else 0)
    if search:
        conditions.append("(text LIKE ? OR title LIKE ?)")
        search_param = f"%{search}%"
        params.extend([search_param, search_param])

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Validate order_by to prevent SQL injection
    valid_order_columns = ["updated_at", "use_count", "title", "created_at"]
    if order_by not in valid_order_columns:
        order_by = "updated_at"

    order_dir = "DESC" if order_desc else "ASC"
    params.append(limit)

    cursor.execute(f"""
        SELECT * FROM prompts
        WHERE {where_clause}
        ORDER BY {order_by} {order_dir}
        LIMIT ?
    """, params)

    prompts = [_row_to_prompt(row) for row in cursor.fetchall()]
    conn.close()

    return prompts


def get_bookmarked_prompts(limit: int = 20) -> List[Dict]:
    """Get bookmarked prompts ordered by use count.

    Args:
        limit: Maximum number of results

    Returns:
        List of bookmarked prompt dictionaries
    """
    return list_prompts(is_bookmarked=True, order_by="use_count", limit=limit)


def get_prompts_by_phase(phase: str, limit: int = 20) -> List[Dict]:
    """Get prompts associated with a workflow phase.

    Args:
        phase: The workflow phase
        limit: Maximum number of results

    Returns:
        List of prompt dictionaries
    """
    return list_prompts(phase=phase, order_by="use_count", limit=limit)


def get_categories() -> List[str]:
    """Get all unique categories.

    Returns:
        List of category names
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT category FROM prompts
        WHERE category IS NOT NULL
        ORDER BY category
    """)

    categories = [row['category'] for row in cursor.fetchall()]
    conn.close()

    return categories


# Prompt history operations

def add_to_history(
    prompt_text: str,
    task_id: Optional[str] = None,
    phase: Optional[str] = None,
    prompt_id: Optional[str] = None,
) -> str:
    """Add a prompt to history.

    Args:
        prompt_text: The prompt text that was sent
        task_id: Optional task ID that received the prompt
        phase: Optional phase when sent
        prompt_id: Optional reference to prompts table if from library

    Returns:
        The history entry ID
    """
    conn = get_connection()
    cursor = conn.cursor()

    history_id = str(uuid.uuid4())
    now = int(datetime.now().timestamp())

    cursor.execute("""
        INSERT INTO prompt_history (id, prompt_id, prompt_text, task_id, phase, sent_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (history_id, prompt_id, prompt_text, task_id, phase, now))

    # If from library, increment use count
    if prompt_id:
        increment_use_count(prompt_id)

    conn.commit()
    conn.close()

    return history_id


def get_history(
    task_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict]:
    """Get prompt history.

    Args:
        task_id: Optional filter by task ID
        limit: Maximum number of results

    Returns:
        List of history entry dictionaries
    """
    conn = get_connection()
    cursor = conn.cursor()

    if task_id:
        cursor.execute("""
            SELECT h.*, p.title as prompt_title, p.category as prompt_category
            FROM prompt_history h
            LEFT JOIN prompts p ON h.prompt_id = p.id
            WHERE h.task_id = ?
            ORDER BY h.sent_at DESC
            LIMIT ?
        """, (task_id, limit))
    else:
        cursor.execute("""
            SELECT h.*, p.title as prompt_title, p.category as prompt_category
            FROM prompt_history h
            LEFT JOIN prompts p ON h.prompt_id = p.id
            ORDER BY h.sent_at DESC
            LIMIT ?
        """, (limit,))

    history = [_row_to_history(row) for row in cursor.fetchall()]
    conn.close()

    return history


def get_recent_prompts(limit: int = 20) -> List[Dict]:
    """Get recent unique prompts from history (for quick recall).

    Args:
        limit: Maximum number of results

    Returns:
        List of recent prompt dictionaries (deduplicated by text)
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Get recent unique prompts
    cursor.execute("""
        SELECT prompt_text, MAX(sent_at) as last_sent, COUNT(*) as send_count
        FROM prompt_history
        GROUP BY prompt_text
        ORDER BY last_sent DESC
        LIMIT ?
    """, (limit,))

    prompts = []
    for row in cursor.fetchall():
        prompts.append({
            'text': row['prompt_text'],
            'last_sent': datetime.fromtimestamp(row['last_sent']),
            'send_count': row['send_count'],
        })

    conn.close()
    return prompts


def search_history(
    search: str,
    task_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict]:
    """Search prompt history.

    Args:
        search: Search term
        task_id: Optional filter by task ID
        limit: Maximum number of results

    Returns:
        List of matching history entries
    """
    conn = get_connection()
    cursor = conn.cursor()

    search_param = f"%{search}%"

    if task_id:
        cursor.execute("""
            SELECT h.*, p.title as prompt_title, p.category as prompt_category
            FROM prompt_history h
            LEFT JOIN prompts p ON h.prompt_id = p.id
            WHERE h.task_id = ? AND h.prompt_text LIKE ?
            ORDER BY h.sent_at DESC
            LIMIT ?
        """, (task_id, search_param, limit))
    else:
        cursor.execute("""
            SELECT h.*, p.title as prompt_title, p.category as prompt_category
            FROM prompt_history h
            LEFT JOIN prompts p ON h.prompt_id = p.id
            WHERE h.prompt_text LIKE ?
            ORDER BY h.sent_at DESC
            LIMIT ?
        """, (search_param, limit))

    history = [_row_to_history(row) for row in cursor.fetchall()]
    conn.close()

    return history


# Helper functions

def _row_to_prompt(row) -> Dict:
    """Convert a database row to a prompt dictionary."""
    return {
        'id': row['id'],
        'text': row['text'],
        'title': row['title'],
        'category': row['category'],
        'tags': row['tags'],
        'phase': row['phase'],
        'is_bookmarked': bool(row['is_bookmarked']),
        'use_count': row['use_count'],
        'created_at': datetime.fromtimestamp(row['created_at']),
        'updated_at': datetime.fromtimestamp(row['updated_at']),
    }


def _row_to_history(row) -> Dict:
    """Convert a database row to a history dictionary."""
    return {
        'id': row['id'],
        'prompt_id': row['prompt_id'],
        'prompt_text': row['prompt_text'],
        'task_id': row['task_id'],
        'phase': row['phase'],
        'sent_at': datetime.fromtimestamp(row['sent_at']),
        'prompt_title': row.get('prompt_title'),
        'prompt_category': row.get('prompt_category'),
    }


# Workflow operations

def get_workflow_prompts(phase: str) -> List[Dict]:
    """Get prompts configured for a specific workflow phase.

    Args:
        phase: The workflow phase (e.g., "planning", "implementing", "testing")

    Returns:
        List of prompt dictionaries ordered by order_index
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT p.*, pw.order_index
        FROM prompt_workflows pw
        JOIN prompts p ON pw.prompt_id = p.id
        WHERE pw.phase = ?
        ORDER BY pw.order_index
    """, (phase,))

    prompts = [_row_to_prompt(row) for row in cursor.fetchall()]
    conn.close()

    return prompts


def add_prompt_to_workflow(prompt_id: str, phase: str, order_index: Optional[int] = None) -> str:
    """Add a prompt to a workflow phase.

    Args:
        prompt_id: The prompt ID
        phase: The workflow phase
        order_index: Optional order index (defaults to next available)

    Returns:
        The workflow entry ID
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Get next order_index if not specified
    if order_index is None:
        cursor.execute("""
            SELECT COALESCE(MAX(order_index), -1) + 1 FROM prompt_workflows WHERE phase = ?
        """, (phase,))
        order_index = cursor.fetchone()[0]

    workflow_id = str(uuid.uuid4())

    cursor.execute("""
        INSERT INTO prompt_workflows (id, phase, prompt_id, order_index)
        VALUES (?, ?, ?, ?)
    """, (workflow_id, phase, prompt_id, order_index))

    conn.commit()
    conn.close()

    return workflow_id


def remove_prompt_from_workflow(prompt_id: str, phase: str) -> bool:
    """Remove a prompt from a workflow phase.

    Args:
        prompt_id: The prompt ID
        phase: The workflow phase

    Returns:
        True if removed, False if not found
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM prompt_workflows WHERE prompt_id = ? AND phase = ?
    """, (prompt_id, phase))

    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()

    return deleted


def get_workflow_phases() -> List[str]:
    """Get all phases that have workflow prompts configured.

    Returns:
        List of phase names
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT phase FROM prompt_workflows ORDER BY phase
    """)

    phases = [row['phase'] for row in cursor.fetchall()]
    conn.close()

    return phases


def is_prompt_in_workflow(prompt_id: str, phase: str) -> bool:
    """Check if a prompt is in a workflow phase.

    Args:
        prompt_id: The prompt ID
        phase: The workflow phase

    Returns:
        True if prompt is in the workflow phase
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 1 FROM prompt_workflows WHERE prompt_id = ? AND phase = ?
    """, (prompt_id, phase))

    exists = cursor.fetchone() is not None
    conn.close()

    return exists
