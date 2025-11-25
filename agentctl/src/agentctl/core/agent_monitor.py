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


def capture_pane_output(pane: libtmux.Pane, lines: int = 50) -> List[str]:
    """Capture recent output from a tmux pane"""
    try:
        output = pane.capture_pane(start=-lines, end=-1)
        if isinstance(output, str):
            return output.split('\n')
        return output if output else []
    except Exception:
        return []


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
