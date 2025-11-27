"""Agent monitoring for agentctl

Provides real-time monitoring of Claude Code agents running in tmux sessions.
"""

import re
import time
from datetime import datetime
from typing import Dict, List, Optional

import libtmux

from .task_store import list_all_tasks
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


def capture_full_session(session_name: str) -> str:
    """Capture the entire scrollback buffer from a tmux session.

    Args:
        session_name: The tmux session name

    Returns:
        Full session output as a string, or empty string if not found
    """
    import subprocess

    try:
        # Use -S - to capture from the start of history
        # -E captures to the end
        result = subprocess.run(
            ['tmux', 'capture-pane', '-t', session_name, '-p', '-S', '-', '-E', '-'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return result.stdout
        return ""
    except Exception:
        return ""


def get_session_logs_dir() -> 'Path':
    """Get the directory for storing session logs.

    Returns:
        Path to ~/.agentctl/sessions directory (created if needed)
    """
    from pathlib import Path

    logs_dir = Path.home() / ".agentctl" / "sessions"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def save_session_log(task_id: str, session_name: str, append_timestamp: bool = True, parse_analytics: bool = True) -> Optional[str]:
    """Capture and save a tmux session to a log file.

    Args:
        task_id: Task ID for the filename
        session_name: tmux session name to capture
        append_timestamp: If True, append timestamp to filename
        parse_analytics: If True, parse log and save analytics to database

    Returns:
        Path to the saved file, or None if capture failed
    """
    from pathlib import Path

    content = capture_full_session(session_name)
    if not content:
        return None

    logs_dir = get_session_logs_dir()

    if append_timestamp:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{task_id}_{timestamp}.log"
    else:
        filename = f"{task_id}.log"

    filepath = logs_dir / filename

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# Session log for {task_id}\n")
            f.write(f"# tmux session: {session_name}\n")
            f.write(f"# Captured at: {datetime.now().isoformat()}\n")
            f.write("#" + "=" * 60 + "\n\n")
            f.write(content)

        # Parse and save analytics
        if parse_analytics:
            try:
                from .session_parser import parse_session_log
                from . import database

                metrics = parse_session_log(content, task_id)
                database.save_session_analytics(task_id, session_name, str(filepath), metrics)
            except Exception:
                pass  # Analytics are optional, don't fail if parsing fails

        return str(filepath)
    except Exception:
        return None


def get_session_logs(task_id: Optional[str] = None) -> List[Dict]:
    """List saved session logs.

    Args:
        task_id: Optional task ID to filter by

    Returns:
        List of log file info dicts with 'path', 'task_id', 'timestamp', 'size'
    """
    from pathlib import Path

    logs_dir = get_session_logs_dir()
    logs = []

    pattern = f"{task_id}_*.log" if task_id else "*.log"

    for logfile in logs_dir.glob(pattern):
        # Parse filename: TASK-ID_YYYYMMDD_HHMMSS.log
        name = logfile.stem
        parts = name.rsplit('_', 2)

        if len(parts) >= 3:
            tid = parts[0]
            try:
                timestamp = datetime.strptime(f"{parts[1]}_{parts[2]}", "%Y%m%d_%H%M%S")
            except ValueError:
                timestamp = None
        else:
            tid = name
            timestamp = None

        logs.append({
            'path': str(logfile),
            'filename': logfile.name,
            'task_id': tid,
            'timestamp': timestamp,
            'size': logfile.stat().st_size,
        })

    # Sort by timestamp descending (newest first)
    logs.sort(key=lambda x: x.get('timestamp') or datetime.min, reverse=True)

    return logs


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
    from agentctl.core.phase_detector import check_and_update_phase

    # Get all tasks that have tmux sessions
    tasks = list_all_tasks()

    agents = []
    for task in tasks:
        tmux_session = task.get("tmux_session")
        if not tmux_session:
            continue

        # Auto-detect and update phase if needed
        task_id = task["task_id"]
        updated_phase = check_and_update_phase(task_id)
        if updated_phase:
            # Refresh task data to get updated phase
            from agentctl.core.task_store import get_task
            task = get_task(task_id) or task

        status = get_agent_status(task_id, tmux_session)
        status["task_title"] = task.get("title", "")
        status["task_agent_status"] = task.get("agent_status", "")
        status["project"] = task.get("project_name", task.get("project", ""))
        status["elapsed"] = task.get("elapsed", "-")
        status["notes"] = task.get("notes", "")
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


# State tracking for notifications
_previous_agent_states: Dict[str, str] = {}


def send_desktop_notification(title: str, message: str, sound: bool = True) -> bool:
    """Send a desktop notification using osascript on macOS.

    Args:
        title: Notification title
        message: Notification body
        sound: Whether to play a sound

    Returns:
        True if notification was sent successfully
    """
    import subprocess
    import platform

    if platform.system() != "Darwin":
        # TODO: Add Linux notification support (notify-send)
        return False

    try:
        sound_param = 'with sound name "Funk"' if sound else ""
        script = f'display notification "{message}" with title "{title}" {sound_param}'
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5
        )
        return True
    except Exception:
        return False


def check_and_notify_state_changes(agents: List[Dict]) -> List[Dict]:
    """Check for agent state changes and send notifications.

    Args:
        agents: List of agent status dicts from get_all_agent_statuses()

    Returns:
        List of state changes that triggered notifications
    """
    global _previous_agent_states

    notifications = []

    for agent in agents:
        task_id = agent["task_id"]
        current_health = agent["health"]
        previous_health = _previous_agent_states.get(task_id)

        # Skip if no previous state (first check)
        if previous_health is None:
            _previous_agent_states[task_id] = current_health
            continue

        # Check for state changes that need notification
        if previous_health != current_health:
            notification = None

            if current_health == HEALTH_WAITING:
                notification = {
                    "task_id": task_id,
                    "title": f"🟠 Agent Waiting: {task_id}",
                    "message": "Agent is waiting for input",
                    "health": current_health,
                    "previous": previous_health,
                }
            elif current_health == HEALTH_ERROR:
                notification = {
                    "task_id": task_id,
                    "title": f"⚠️ Agent Error: {task_id}",
                    "message": "Agent encountered an error",
                    "health": current_health,
                    "previous": previous_health,
                }
            elif current_health == HEALTH_EXITED:
                notification = {
                    "task_id": task_id,
                    "title": f"🔴 Agent Exited: {task_id}",
                    "message": "Agent session has exited",
                    "health": current_health,
                    "previous": previous_health,
                }
            elif current_health == HEALTH_ACTIVE and previous_health in (HEALTH_IDLE, HEALTH_WAITING):
                # Agent resumed working - lower priority notification
                notification = {
                    "task_id": task_id,
                    "title": f"🟢 Agent Active: {task_id}",
                    "message": "Agent resumed working",
                    "health": current_health,
                    "previous": previous_health,
                    "sound": False,  # No sound for resume
                }

            if notification:
                sound = notification.pop("sound", True)
                send_desktop_notification(
                    notification["title"],
                    notification["message"],
                    sound=sound
                )
                notifications.append(notification)

            # Update state
            _previous_agent_states[task_id] = current_health

    # Clean up old entries for agents that no longer exist
    current_task_ids = {a["task_id"] for a in agents}
    for task_id in list(_previous_agent_states.keys()):
        if task_id not in current_task_ids:
            del _previous_agent_states[task_id]

    return notifications


def reset_notification_state():
    """Reset the notification state tracking. Useful for testing."""
    global _previous_agent_states
    _previous_agent_states = {}
