"""Session log parser for agentctl

Parses captured tmux session output from Claude Code agents to extract
structured data about tool usage, file operations, and task progress.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class ToolCall:
    """Represents a single tool invocation"""
    tool_name: str
    timestamp: Optional[datetime] = None
    parameters: Dict = field(default_factory=dict)
    success: Optional[bool] = None
    duration_ms: Optional[int] = None


@dataclass
class FileOperation:
    """Represents a file read/write/edit operation"""
    operation: str  # read, write, edit, create, delete
    file_path: str
    timestamp: Optional[datetime] = None
    lines_affected: Optional[int] = None


@dataclass
class CommandExecution:
    """Represents a bash command execution"""
    command: str
    timestamp: Optional[datetime] = None
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None


@dataclass
class ErrorEvent:
    """Represents an error encountered during session"""
    error_type: str
    message: str
    timestamp: Optional[datetime] = None
    resolved: bool = False


@dataclass
class UserPrompt:
    """Represents a user prompt/input in the conversation"""
    prompt: str
    prompt_type: str  # 'message', 'command', 'file_reference', 'interrupt'
    timestamp: Optional[datetime] = None
    order: int = 0  # Order in the conversation


@dataclass
class SessionMetrics:
    """Aggregated metrics for a session"""
    session_id: str
    task_id: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    # Counts
    total_tool_calls: int = 0
    total_file_operations: int = 0
    total_commands: int = 0
    total_errors: int = 0

    # Tool breakdown
    tool_counts: Dict[str, int] = field(default_factory=dict)

    # File operations breakdown
    files_read: List[str] = field(default_factory=list)
    files_written: List[str] = field(default_factory=list)
    files_edited: List[str] = field(default_factory=list)

    # Commands
    commands: List[CommandExecution] = field(default_factory=list)

    # Errors
    errors: List[ErrorEvent] = field(default_factory=list)

    # Raw data
    tool_calls: List[ToolCall] = field(default_factory=list)
    file_operations: List[FileOperation] = field(default_factory=list)

    # User prompts
    user_prompts: List[UserPrompt] = field(default_factory=list)
    total_user_prompts: int = 0


# Patterns for parsing Claude Code output
PATTERNS = {
    # Tool invocation patterns (Claude Code TUI format)
    'tool_call': re.compile(
        r'(?:Using|Calling|Running)\s+(?:tool\s+)?["\']?(\w+)["\']?',
        re.IGNORECASE
    ),

    # Read tool
    'read_file': re.compile(
        r'(?:Read|Reading|read)\s+(?:file\s+)?["\']?([^\s"\']+)["\']?',
        re.IGNORECASE
    ),

    # Write tool
    'write_file': re.compile(
        r'(?:Write|Writing|Wrote|write)\s+(?:to\s+)?(?:file\s+)?["\']?([^\s"\']+)["\']?',
        re.IGNORECASE
    ),

    # Edit tool
    'edit_file': re.compile(
        r'(?:Edit|Editing|Edited|edit)\s+(?:file\s+)?["\']?([^\s"\']+)["\']?',
        re.IGNORECASE
    ),

    # Bash command
    'bash_command': re.compile(
        r'(?:\$|❯|>)\s*(.+)$|Running:\s*(.+)$|Command:\s*(.+)$',
        re.MULTILINE
    ),

    # Git operations
    'git_commit': re.compile(
        r'(?:commit|committed)\s+([a-f0-9]{7,40})',
        re.IGNORECASE
    ),

    # Errors
    'error': re.compile(
        r'(?:error|Error|ERROR|failed|Failed|FAILED|exception|Exception)[\s:]+(.+)',
        re.IGNORECASE
    ),

    # Success indicators
    'success': re.compile(
        r'(?:success|Success|SUCCESS|completed|Completed|done|Done|passed|Passed)',
        re.IGNORECASE
    ),

    # Todo operations
    'todo_created': re.compile(
        r'(?:Created|Adding|Added)\s+(?:todo|task)',
        re.IGNORECASE
    ),
    'todo_completed': re.compile(
        r'(?:Completed|Marking|Marked)\s+(?:todo|task)\s+(?:as\s+)?(?:completed|done)',
        re.IGNORECASE
    ),

    # Claude Code specific patterns
    'claude_tool_start': re.compile(
        r'⏺\s+(\w+)\s*$|●\s+(\w+)|╭.*?(\w+).*?╮',
        re.MULTILINE
    ),
    'claude_tool_result': re.compile(
        r'✓|✔|⚠|✗|✘',
    ),

    # File paths
    'file_path': re.compile(
        r'(/[^\s:]+\.[a-zA-Z]{1,10})|([a-zA-Z_][a-zA-Z0-9_/]*\.[a-zA-Z]{1,10})'
    ),

    # Grep/search patterns
    'grep_search': re.compile(
        r'(?:Grep|grep|Searching|searching|Search|search)\s+(?:for\s+)?["\']?([^"\']+)["\']?',
        re.IGNORECASE
    ),

    # User prompt patterns (lines starting with "> ")
    'user_prompt': re.compile(r'^>\s+(.+)$'),

    # Slash commands
    'slash_command': re.compile(r'^/[\w:-]+'),

    # File references (@file)
    'file_reference': re.compile(r'@[\w./\-]+'),

    # Skill loading messages (system, not user input)
    'skill_loading': re.compile(r'^The\s+"[\w-]+"\s+skill\s+is\s+loading'),

    # Running message (system, not user input)
    'command_running': re.compile(r'^/[\w:-]+\s+is\s+running'),

    # Interrupted message
    'interrupted': re.compile(r'Interrupted'),
}

# Known Claude Code tools
KNOWN_TOOLS = {
    'Read', 'Write', 'Edit', 'Bash', 'Grep', 'Glob', 'Task',
    'TodoWrite', 'WebFetch', 'WebSearch', 'AskUserQuestion',
    'NotebookEdit', 'mcp__'
}


def parse_session_log(content: str, task_id: str = "unknown") -> SessionMetrics:
    """Parse a session log and extract structured data.

    Args:
        content: Raw session log content
        task_id: Task ID for the session

    Returns:
        SessionMetrics with extracted data
    """
    metrics = SessionMetrics(
        session_id=f"{task_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        task_id=task_id
    )

    lines = content.split('\n')

    # Parse header for metadata
    for line in lines[:10]:
        if line.startswith('# Captured at:'):
            try:
                ts_str = line.replace('# Captured at:', '').strip()
                metrics.ended_at = datetime.fromisoformat(ts_str)
            except ValueError:
                pass

    # Parse content
    prompt_order = 0
    for i, line in enumerate(lines):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        # Check for user prompts first (they start with "> ")
        if _parse_user_prompts(line, metrics, prompt_order):
            prompt_order += 1
            continue  # User prompts don't need further parsing

        # Check for tool calls
        _parse_tool_calls(line, metrics)

        # Check for file operations
        _parse_file_operations(line, metrics)

        # Check for commands
        _parse_commands(line, metrics)

        # Check for errors
        _parse_errors(line, metrics)

    # Calculate totals
    metrics.total_tool_calls = len(metrics.tool_calls)
    metrics.total_file_operations = len(metrics.file_operations)
    metrics.total_commands = len(metrics.commands)
    metrics.total_errors = len(metrics.errors)
    metrics.total_user_prompts = len(metrics.user_prompts)

    # Deduplicate file lists
    metrics.files_read = list(set(metrics.files_read))
    metrics.files_written = list(set(metrics.files_written))
    metrics.files_edited = list(set(metrics.files_edited))

    return metrics


def _parse_tool_calls(line: str, metrics: SessionMetrics) -> None:
    """Extract tool calls from a line."""
    # Check for known tools
    for tool in KNOWN_TOOLS:
        if tool.lower() in line.lower():
            tool_call = ToolCall(tool_name=tool)
            metrics.tool_calls.append(tool_call)
            metrics.tool_counts[tool] = metrics.tool_counts.get(tool, 0) + 1
            break

    # Check Claude Code specific tool patterns
    match = PATTERNS['claude_tool_start'].search(line)
    if match:
        tool_name = match.group(1) or match.group(2) or match.group(3)
        if tool_name and tool_name not in ['if', 'for', 'while', 'def', 'class']:
            tool_call = ToolCall(tool_name=tool_name)
            metrics.tool_calls.append(tool_call)
            metrics.tool_counts[tool_name] = metrics.tool_counts.get(tool_name, 0) + 1


def _parse_file_operations(line: str, metrics: SessionMetrics) -> None:
    """Extract file operations from a line."""
    # Read operations
    match = PATTERNS['read_file'].search(line)
    if match:
        filepath = match.group(1)
        if _is_valid_filepath(filepath):
            op = FileOperation(operation='read', file_path=filepath)
            metrics.file_operations.append(op)
            metrics.files_read.append(filepath)

    # Write operations
    match = PATTERNS['write_file'].search(line)
    if match:
        filepath = match.group(1)
        if _is_valid_filepath(filepath):
            op = FileOperation(operation='write', file_path=filepath)
            metrics.file_operations.append(op)
            metrics.files_written.append(filepath)

    # Edit operations
    match = PATTERNS['edit_file'].search(line)
    if match:
        filepath = match.group(1)
        if _is_valid_filepath(filepath):
            op = FileOperation(operation='edit', file_path=filepath)
            metrics.file_operations.append(op)
            metrics.files_edited.append(filepath)


def _parse_commands(line: str, metrics: SessionMetrics) -> None:
    """Extract bash commands from a line."""
    match = PATTERNS['bash_command'].search(line)
    if match:
        cmd = match.group(1) or match.group(2) or match.group(3)
        if cmd and len(cmd) > 2 and not cmd.startswith('#'):
            # Filter out common false positives
            if not any(fp in cmd.lower() for fp in ['---', '===', '```', '"""']):
                execution = CommandExecution(command=cmd.strip())
                metrics.commands.append(execution)


def _parse_errors(line: str, metrics: SessionMetrics) -> None:
    """Extract errors from a line."""
    match = PATTERNS['error'].search(line)
    if match:
        error_msg = match.group(1).strip()
        if len(error_msg) > 5:  # Filter short matches
            # Determine error type
            error_type = "unknown"
            if "permission" in line.lower():
                error_type = "permission"
            elif "not found" in line.lower():
                error_type = "not_found"
            elif "syntax" in line.lower():
                error_type = "syntax"
            elif "timeout" in line.lower():
                error_type = "timeout"
            elif "connection" in line.lower():
                error_type = "connection"

            error = ErrorEvent(
                error_type=error_type,
                message=error_msg[:200]  # Truncate long messages
            )
            metrics.errors.append(error)


def _parse_user_prompts(line: str, metrics: SessionMetrics, prompt_order: int) -> bool:
    """Extract user prompts from a line.

    Returns True if a user prompt was found.
    """
    match = PATTERNS['user_prompt'].match(line)
    if not match:
        return False

    prompt_text = match.group(1).strip()
    if not prompt_text:
        return False

    # Skip system messages that look like user prompts
    if PATTERNS['skill_loading'].match(prompt_text):
        return False
    if PATTERNS['command_running'].match(prompt_text):
        return False

    # Determine prompt type
    prompt_type = 'message'

    if PATTERNS['slash_command'].match(prompt_text):
        prompt_type = 'command'
    elif PATTERNS['file_reference'].search(prompt_text):
        prompt_type = 'file_reference'
    elif PATTERNS['interrupted'].search(line):
        prompt_type = 'interrupt'

    # Create prompt object
    user_prompt = UserPrompt(
        prompt=prompt_text[:500],  # Truncate very long prompts
        prompt_type=prompt_type,
        order=prompt_order
    )
    metrics.user_prompts.append(user_prompt)
    return True


def _is_valid_filepath(path: str) -> bool:
    """Check if a string looks like a valid file path."""
    if not path or len(path) < 3:
        return False

    # Must have an extension or be an absolute path
    if '.' not in path and not path.startswith('/'):
        return False

    # Filter common false positives
    false_positives = ['...', 'e.g.', 'i.e.', 'etc.', 'vs.']
    if any(fp in path.lower() for fp in false_positives):
        return False

    return True


def parse_session_file(filepath: Path) -> Optional[SessionMetrics]:
    """Parse a session log file.

    Args:
        filepath: Path to the log file

    Returns:
        SessionMetrics or None if parsing fails
    """
    try:
        # Extract task_id from filename
        name = filepath.stem
        parts = name.rsplit('_', 2)
        task_id = parts[0] if parts else "unknown"

        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        return parse_session_log(content, task_id)
    except Exception:
        return None


def get_aggregate_metrics(metrics_list: List[SessionMetrics]) -> Dict:
    """Aggregate metrics across multiple sessions.

    Args:
        metrics_list: List of SessionMetrics

    Returns:
        Dict with aggregated statistics
    """
    if not metrics_list:
        return {}

    total_tools = sum(m.total_tool_calls for m in metrics_list)
    total_files = sum(m.total_file_operations for m in metrics_list)
    total_commands = sum(m.total_commands for m in metrics_list)
    total_errors = sum(m.total_errors for m in metrics_list)

    # Aggregate tool counts
    tool_totals: Dict[str, int] = {}
    for m in metrics_list:
        for tool, count in m.tool_counts.items():
            tool_totals[tool] = tool_totals.get(tool, 0) + count

    # Get unique files
    all_files_read = set()
    all_files_written = set()
    all_files_edited = set()
    for m in metrics_list:
        all_files_read.update(m.files_read)
        all_files_written.update(m.files_written)
        all_files_edited.update(m.files_edited)

    return {
        'session_count': len(metrics_list),
        'total_tool_calls': total_tools,
        'total_file_operations': total_files,
        'total_commands': total_commands,
        'total_errors': total_errors,
        'tool_breakdown': tool_totals,
        'unique_files_read': len(all_files_read),
        'unique_files_written': len(all_files_written),
        'unique_files_edited': len(all_files_edited),
        'error_rate': total_errors / max(total_tools, 1),
    }
