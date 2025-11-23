"""Markdown task file operations for agentctl"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import frontmatter
import re


# Required fields for task frontmatter
REQUIRED_FIELDS = [
    'id', 'title', 'project_id', 'category', 'status', 'priority', 'created_at'
]

# Valid enum values
VALID_STATUS = ['queued', 'running', 'blocked', 'completed', 'failed']
VALID_PRIORITY = ['high', 'medium', 'low']
VALID_CATEGORY = ['FEATURE', 'BUG', 'REFACTOR', 'DOCS', 'TEST', 'CHORE']


def parse_task_file(file_path: Path) -> Tuple[Optional[Dict], Optional[str], List[str]]:
    """
    Parse a task markdown file

    Args:
        file_path: Path to the markdown file

    Returns:
        Tuple of (task_data dict, markdown body, list of errors)
        If parsing fails, task_data will be None
    """
    errors = []

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)

        task_data = dict(post.metadata)
        body = post.content

        # Validate task data
        validation_errors = validate_task_data(task_data)
        if validation_errors:
            return None, None, validation_errors

        return task_data, body, []

    except FileNotFoundError:
        return None, None, [f"File not found: {file_path}"]
    except Exception as e:
        return None, None, [f"Error parsing file: {str(e)}"]


def validate_task_data(data: Dict) -> List[str]:
    """
    Validate task frontmatter data

    Args:
        data: Task data dictionary

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    # Check required fields
    for field in REQUIRED_FIELDS:
        if field not in data or data[field] is None:
            errors.append(f"Missing required field: {field}")

    if errors:  # Don't validate further if required fields are missing
        return errors

    # Validate id format
    if not re.match(r'^[A-Z]+-[A-Z]+-\d{4}$', str(data['id'])):
        errors.append(f"Invalid id format: {data['id']} (expected PROJECT-CATEGORY-NNNN)")

    # Validate status
    if data['status'] not in VALID_STATUS:
        errors.append(f"Invalid status: {data['status']} (must be one of: {', '.join(VALID_STATUS)})")

    # Validate priority
    if data['priority'] not in VALID_PRIORITY:
        errors.append(f"Invalid priority: {data['priority']} (must be one of: {', '.join(VALID_PRIORITY)})")

    # Validate category
    if data['category'] not in VALID_CATEGORY:
        errors.append(f"Invalid category: {data['category']} (must be one of: {', '.join(VALID_CATEGORY)})")

    # Validate created_at is a valid ISO 8601 timestamp
    try:
        datetime.fromisoformat(str(data['created_at']))
    except (ValueError, TypeError):
        errors.append(f"Invalid created_at timestamp: {data['created_at']} (must be ISO 8601 format)")

    # Validate optional timestamp fields
    for field in ['started_at', 'completed_at']:
        if field in data and data[field] is not None:
            try:
                datetime.fromisoformat(str(data[field]))
            except (ValueError, TypeError):
                errors.append(f"Invalid {field} timestamp: {data[field]} (must be ISO 8601 format)")

    # Validate commits is a non-negative integer
    if 'commits' in data:
        try:
            commits = int(data['commits'])
            if commits < 0:
                errors.append(f"commits must be >= 0, got: {commits}")
        except (ValueError, TypeError):
            errors.append(f"commits must be an integer, got: {data['commits']}")

    return errors


def write_task_file(file_path: Path, task_data: Dict, body: str = "") -> None:
    """
    Write a task to a markdown file

    Args:
        file_path: Path to write the file
        task_data: Task metadata dictionary
        body: Markdown content body
    """
    # Ensure parent directory exists
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Create frontmatter post
    post = frontmatter.Post(body, **task_data)

    # Write to file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(frontmatter.dumps(post))


def generate_task_template(
    task_id: str,
    title: str,
    project_id: str,
    repository_id: Optional[str] = None,
    category: str = "FEATURE",
    task_type: str = "feature",
    priority: str = "medium",
    description: str = ""
) -> Dict:
    """
    Generate task data template with defaults

    Args:
        task_id: Task ID (e.g., RRA-API-0053)
        title: Task title
        project_id: Project ID
        repository_id: Optional repository ID
        category: Task category
        task_type: Task type
        priority: Task priority
        description: Optional description

    Returns:
        Task data dictionary ready to write
    """
    return {
        'id': task_id,
        'title': title,
        'project_id': project_id,
        'repository_id': repository_id,
        'category': category,
        'type': task_type,
        'priority': priority,
        'status': 'queued',
        'phase': None,
        'created_at': datetime.now().isoformat(),
        'started_at': None,
        'completed_at': None,
        'git_branch': None,
        'worktree_path': None,
        'tmux_session': None,
        'agent_type': None,
        'commits': 0
    }


def get_next_task_id(tasks_path: Path, project_id: str, category: str) -> str:
    """
    Get the next available task ID for a project/category

    Args:
        tasks_path: Path to task files directory
        project_id: Project ID (e.g., RRA)
        category: Category (e.g., API, WEB, BUG)

    Returns:
        Next task ID (e.g., RRA-API-0053)
    """
    if not tasks_path.exists():
        return f"{project_id}-{category}-0001"

    # Pattern to match task files for this project and category
    pattern = f"{project_id}-{category}-*.md"

    # Find all matching files
    matching_files = list(tasks_path.glob(pattern))

    if not matching_files:
        return f"{project_id}-{category}-0001"

    # Extract numbers from filenames
    numbers = []
    for file in matching_files:
        # Extract the number from filename like "RRA-API-0053.md"
        match = re.match(rf'{project_id}-{category}-(\d{{4}})\.md', file.name)
        if match:
            numbers.append(int(match.group(1)))

    if not numbers:
        return f"{project_id}-{category}-0001"

    # Get next number
    next_num = max(numbers) + 1

    return f"{project_id}-{category}-{next_num:04d}"


def update_task_file(file_path: Path, updates: Dict) -> bool:
    """
    Update specific fields in a task file while preserving the body

    Args:
        file_path: Path to the task file
        updates: Dictionary of fields to update

    Returns:
        True if successful, False otherwise
    """
    try:
        # Read current file
        task_data, body, errors = parse_task_file(file_path)

        if errors:
            return False

        # Update fields
        task_data.update(updates)

        # Write back
        write_task_file(file_path, task_data, body or "")

        return True

    except Exception:
        return False
