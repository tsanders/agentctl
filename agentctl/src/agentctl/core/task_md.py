"""Markdown task file operations for agentctl

Markdown files are the single source of truth for task data.
All frontmatter fields are preserved - only minimal fields are required.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import frontmatter
import re


# Minimal required fields - just enough to identify and display a task
REQUIRED_FIELDS = ['id', 'title', 'project_id']

# Valid enum values for agentctl-specific fields
VALID_AGENT_STATUS = ['queued', 'running', 'blocked', 'completed', 'failed', 'paused']
VALID_PRIORITY = ['high', 'medium', 'low']
VALID_CATEGORY = ['FEATURE', 'BUG', 'REFACTOR', 'DOCS', 'TEST', 'CHORE']
VALID_PHASE = [
    'preparation',      # Task writeup in progress
    'registered',       # Task added to agentctl
    'agent_created',    # Worktree/branch/tmux session ready
    'initialization',   # Agent session starting up
    'implementation',   # Active development with TDD
    'agent_review',     # Automated code review agent running
    'human_review',     # Awaiting human review/PR
    'integration_merge', # Merging changes to main branch
    'adhoc_testing',    # Manual/exploratory testing
    'completed'         # Merged and done
]


def parse_task_file(file_path: Path, strict: bool = False) -> Tuple[Optional[Dict], Optional[str], List[str]]:
    """
    Parse a task markdown file, preserving ALL frontmatter fields.

    Args:
        file_path: Path to the markdown file
        strict: If True, validate agentctl-specific fields. If False, only check required fields.

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
        validation_errors = validate_task_data(task_data, strict=strict)
        if validation_errors:
            return None, None, validation_errors

        # Normalize: ensure agent_status exists (derive from other fields if needed)
        if 'agent_status' not in task_data:
            task_data['agent_status'] = _derive_agent_status(task_data)

        return task_data, body, []

    except FileNotFoundError:
        return None, None, [f"File not found: {file_path}"]
    except Exception as e:
        return None, None, [f"Error parsing file: {str(e)}"]


def _derive_agent_status(data: Dict) -> str:
    """
    Derive agent_status from other fields if not present.

    Looks at 'status' field or other indicators to determine agent state.
    """
    # Check for explicit status field (Obsidian compatibility)
    status = data.get('status', '').lower()
    if status:
        # Map common status values to agent_status
        status_map = {
            'in-progress': 'running',
            'in progress': 'running',
            'active': 'running',
            'working': 'running',
            'done': 'completed',
            'complete': 'completed',
            'finished': 'completed',
            'todo': 'queued',
            'pending': 'queued',
            'waiting': 'blocked',
            'blocked': 'blocked',
            'on-hold': 'blocked',
            'failed': 'failed',
            'error': 'failed',
        }
        if status in status_map:
            return status_map[status]

    # Check if task has been started
    if data.get('started_at') and not data.get('completed_at'):
        return 'running'
    if data.get('completed_at'):
        return 'completed'

    return 'queued'


def validate_task_data(data: Dict, strict: bool = False) -> List[str]:
    """
    Validate task frontmatter data.

    Only validates minimal required fields by default.
    All other fields are preserved as-is.

    Args:
        data: Task data dictionary
        strict: If True, also validate agentctl-specific fields

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    # Check required fields only
    for field in REQUIRED_FIELDS:
        if field not in data or data[field] is None:
            errors.append(f"Missing required field: {field}")

    if errors:
        return errors

    # Validate id format (flexible - allow various patterns)
    task_id = str(data['id'])
    if not re.match(r'^[A-Z]+-[A-Z0-9]+-\d+$', task_id):
        # Try looser pattern
        if not re.match(r'^[\w-]+$', task_id):
            errors.append(f"Invalid id format: {data['id']}")

    if strict:
        # Strict mode: validate agentctl-specific fields
        if 'agent_status' in data and data['agent_status'] not in VALID_AGENT_STATUS:
            errors.append(f"Invalid agent_status: {data['agent_status']}")

        if 'priority' in data and data['priority'] not in VALID_PRIORITY:
            errors.append(f"Invalid priority: {data['priority']}")

        if 'category' in data and data['category'] not in VALID_CATEGORY:
            errors.append(f"Invalid category: {data['category']}")

        if 'phase' in data and data['phase'] is not None and data['phase'] not in VALID_PHASE:
            errors.append(f"Invalid phase: {data['phase']}")

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
        'agent_status': 'queued',
        'phase': 'preparation',
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


def get_phase_display_name(phase: Optional[str]) -> str:
    """Get human-readable display name for a phase"""
    if not phase:
        return "Not Set"

    phase_names = {
        'preparation': 'Preparation',
        'registered': 'Registered',
        'agent_created': 'Agent Created',
        'initialization': 'Initialization',
        'implementation': 'Implementation',
        'agent_review': 'Agent Review',
        'human_review': 'Human Review',
        'integration_merge': 'Integration Merge',
        'adhoc_testing': 'Ad-Hoc Testing',
        'completed': 'Completed'
    }
    return phase_names.get(phase, phase.title())


def get_next_phase(current_phase: Optional[str]) -> Optional[str]:
    """Get the next phase in the workflow"""
    if not current_phase or current_phase not in VALID_PHASE:
        return VALID_PHASE[0]  # Start at preparation

    current_index = VALID_PHASE.index(current_phase)
    if current_index < len(VALID_PHASE) - 1:
        return VALID_PHASE[current_index + 1]

    return None  # Already at final phase


def get_previous_phase(current_phase: Optional[str]) -> Optional[str]:
    """Get the previous phase in the workflow"""
    if not current_phase or current_phase not in VALID_PHASE:
        return None

    current_index = VALID_PHASE.index(current_phase)
    if current_index > 0:
        return VALID_PHASE[current_index - 1]

    return None  # Already at first phase
