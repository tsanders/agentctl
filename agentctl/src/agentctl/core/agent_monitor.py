"""Agent monitoring for agentctl

Provides real-time monitoring of Claude Code agents running in tmux sessions.
"""

import re
import time
from datetime import datetime
from typing import Dict, List, Optional

import libtmux

from .database import list_all_tasks
from .tmux import get_server, session_exists

# Health state constants
HEALTH_ACTIVE = "active"
HEALTH_IDLE = "idle"
HEALTH_WAITING = "waiting"
HEALTH_EXITED = "exited"
HEALTH_ERROR = "error"

# Health icons
HEALTH_ICONS = {
    HEALTH_ACTIVE: "🟢",
    HEALTH_IDLE: "🟡",
    HEALTH_WAITING: "🟠",
    HEALTH_EXITED: "🔴",
    HEALTH_ERROR: "⚠️",
}

# Detection patterns
ACTIVE_PATTERN = "esc to interrupt"
IDLE_WARNING_SECONDS = 60

ERROR_PATTERNS = [
    r"error:",
    r"Error:",
    r"ERROR",
    r"failed",
    r"Failed",
    r"FAILED",
    r"exception",
    r"Exception",
    r"traceback",
    r"Traceback",
]

INPUT_PATTERNS = [
    r"\? ",
    r"\[Y/n\]",
    r"\[y/N\]",
    r"Press enter",
    r"Do you want",
    r"Would you like",
    r"Continue\?",
    r"Proceed\?",
]


def get_session_pane(session_name: str) -> Optional[libtmux.Pane]:
    """Get the active pane for a tmux session"""
    server = get_server()
    session = server.find_where({"session_name": session_name})
    if not session:
        return None

    # Get the first window's active pane
    windows = session.windows
    if not windows:
        return None

    return windows[0].active_pane


def capture_pane_output(pane: libtmux.Pane, lines: int = 100) -> List[str]:
    """Capture recent output from a tmux pane using subprocess for better compatibility

    Args:
        pane: The tmux pane to capture from (used for pane_id)
        lines: Number of lines to capture (default 100)

    Returns:
        List of output lines
    """
    import subprocess

    try:
        # Use tmux capture-pane directly with -p flag to print to stdout
        # This captures the alternate screen buffer (used by TUI apps like Claude)
        result = subprocess.run(
            ['tmux', 'capture-pane', '-t', pane.id, '-p', '-S', f'-{lines}'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.split('\n')
        return []
    except Exception:
        return []


def capture_session_output(session_name: str, lines: int = 100) -> List[str]:
    """Capture recent output from a tmux session by name

    Args:
        session_name: The tmux session name
        lines: Number of lines to capture (default 100)

    Returns:
        List of output lines, or empty list if session not found
    """
    import subprocess

    try:
        # Use tmux capture-pane directly with session target
        # -p prints to stdout, -S sets start line (negative = from end)
        result = subprocess.run(
            ['tmux', 'capture-pane', '-t', session_name, '-p', '-S', f'-{lines}'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.split('\n')
        return []
    except Exception:
        return []


def tail_session_output(session_name: str, lines: int = 100, interval: float = 0.5):
    """Generator that yields new output lines from a tmux session

    Args:
        session_name: The tmux session name
        lines: Initial number of lines to capture
        interval: Polling interval in seconds

    Yields:
        New output lines as they appear
    """
    # Get initial output
    last_output = capture_session_output(session_name, lines)
    if not last_output:
        return

    last_hash = hash(tuple(last_output))

    # Yield initial output
    for line in last_output:
        yield line

    # Poll for changes
    while True:
        time.sleep(interval)

        current_output = capture_session_output(session_name, lines)
        if not current_output:
            return  # Session closed

        current_hash = hash(tuple(current_output))

        if current_hash != last_hash:
            # Find new lines by comparing from the end
            # This is a simple approach - just yield lines that weren't in last output
            last_set = set(last_output[-50:])  # Compare last 50 lines
            for line in current_output:
                if line not in last_set:
                    yield line

            last_output = current_output
            last_hash = current_hash


def get_session_status(session_name: str) -> Dict:
    """Get status information for a tmux session.

    Returns:
        dict with keys:
            - exists: bool - whether session exists
            - pane: libtmux.Pane or None
            - recent_output: list of recent output lines
            - last_output_time: timestamp of last detected output (estimated)
    """
    pane = get_session_pane(session_name)

    if not pane:
        return {
            "exists": False,
            "pane": None,
            "recent_output": [],
            "last_output_time": None,
        }

    recent_output = capture_pane_output(pane)

    # Filter out empty lines for better signal
    non_empty_lines = [line for line in recent_output if line.strip()]

    return {
        "exists": True,
        "pane": pane,
        "recent_output": recent_output,
        "non_empty_output": non_empty_lines,
        "last_output_time": time.time(),  # We can't know exact time, use current
    }


def detect_health_state(session_info: Dict) -> Dict:
    """Analyze session info to determine health state.

    Args:
        session_info: Dict from get_session_status()

    Returns:
        dict with keys:
            - health: one of active/idle/waiting/exited/error
            - icon: emoji icon for the state
            - warnings: list of warning messages
            - last_meaningful_line: most recent non-empty output
    """
    if not session_info.get("exists"):
        return {
            "health": HEALTH_EXITED,
            "icon": HEALTH_ICONS[HEALTH_EXITED],
            "warnings": ["Session not found"],
            "last_meaningful_line": None,
        }

    recent_output = session_info.get("recent_output", [])
    non_empty = session_info.get("non_empty_output", [])

    warnings = []
    last_meaningful = non_empty[-1] if non_empty else None

    # Check recent output for patterns
    recent_text = "\n".join(recent_output[-20:])  # Check last 20 lines

    # Check for active pattern (Claude is working)
    if ACTIVE_PATTERN in recent_text.lower():
        return {
            "health": HEALTH_ACTIVE,
            "icon": HEALTH_ICONS[HEALTH_ACTIVE],
            "warnings": [],
            "last_meaningful_line": last_meaningful,
        }

    # Check for input prompts (waiting for user)
    for pattern in INPUT_PATTERNS:
        if re.search(pattern, recent_text, re.IGNORECASE):
            warnings.append("Detected input prompt")
            return {
                "health": HEALTH_WAITING,
                "icon": HEALTH_ICONS[HEALTH_WAITING],
                "warnings": warnings,
                "last_meaningful_line": last_meaningful,
            }

    # Check for error patterns
    for pattern in ERROR_PATTERNS:
        if re.search(pattern, recent_text):
            warnings.append("Error detected in output")
            return {
                "health": HEALTH_ERROR,
                "icon": HEALTH_ICONS[HEALTH_ERROR],
                "warnings": warnings,
                "last_meaningful_line": last_meaningful,
            }

    # Default to idle if no activity patterns found
    return {
        "health": HEALTH_IDLE,
        "icon": HEALTH_ICONS[HEALTH_IDLE],
        "warnings": [],
        "last_meaningful_line": last_meaningful,
    }


def get_agent_status(task_id: str, tmux_session: str) -> Dict:
    """Get full agent status for a single task.

    Args:
        task_id: The task identifier
        tmux_session: The tmux session name

    Returns:
        dict with full agent status information
    """
    session_info = get_session_status(tmux_session)
    health_info = detect_health_state(session_info)

    # Get a preview of recent output (last non-empty line, truncated)
    last_line = health_info.get("last_meaningful_line", "")
    if last_line and len(last_line) > 60:
        last_line = last_line[:57] + "..."

    return {
        "task_id": task_id,
        "tmux_session": tmux_session,
        "health": health_info["health"],
        "icon": health_info["icon"],
        "process_running": session_info.get("exists", False),
        "recent_output": session_info.get("recent_output", []),
        "last_output_preview": last_line,
        "warnings": health_info.get("warnings", []),
    }


def get_all_agent_statuses() -> List[Dict]:
    """Get status for all tasks with tmux sessions.

    Returns:
        List of agent status dicts, sorted by health priority
        (errors/waiting first, then idle, then active)
    """
    # Get all tasks that have tmux sessions
    tasks = list_all_tasks()

    agents = []
    for task in tasks:
        tmux_session = task.get("tmux_session")
        if not tmux_session:
            continue

        status = get_agent_status(task["task_id"], tmux_session)
        status["task_title"] = task.get("title", "")
        status["task_status"] = task.get("status", "")
        agents.append(status)

    # Sort by health priority: error > waiting > idle > active > exited
    health_priority = {
        HEALTH_ERROR: 0,
        HEALTH_WAITING: 1,
        HEALTH_IDLE: 2,
        HEALTH_ACTIVE: 3,
        HEALTH_EXITED: 4,
    }

    agents.sort(key=lambda a: health_priority.get(a["health"], 5))

    return agents


def format_idle_time(seconds: int) -> str:
    """Format seconds into human-readable idle time"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        if secs > 0:
            return f"{minutes}m {secs}s"
        return f"{minutes}m"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"


def get_health_display(health: str, include_label: bool = True) -> str:
    """Get display string for health state"""
    icon = HEALTH_ICONS.get(health, "?")
    if include_label:
        return f"{icon} {health.upper()}"
    return icon
