"""tmux integration for agentctl"""

import libtmux
from pathlib import Path
from typing import Dict, List, Optional


def get_server():
    """Get tmux server instance"""
    return libtmux.Server()


def create_session(session_name: str, working_dir: Path) -> str:
    """Create a new tmux session for a task"""
    server = get_server()

    # Check if session already exists
    existing = server.find_where({"session_name": session_name})
    if existing:
        return session_name

    # Create new session
    session = server.new_session(
        session_name=session_name,
        start_directory=str(working_dir),
        attach=False
    )

    return session.name


def attach_session(session_name: str, split: bool = False):
    """Attach to a tmux session"""
    server = get_server()

    session = server.find_where({"session_name": session_name})
    if not session:
        raise ValueError(f"Session {session_name} not found")

    # For split, we'd need to handle this differently
    # For now, just provide the attach command
    return session_name


def kill_session(session_name: str):
    """Kill a tmux session"""
    server = get_server()

    session = server.find_where({"session_name": session_name})
    if session:
        session.kill_session()


def session_exists(session_name: str) -> bool:
    """Check if a tmux session exists"""
    server = get_server()
    return server.find_where({"session_name": session_name}) is not None


def list_sessions():
    """List all tmux sessions"""
    server = get_server()
    return [s.name for s in server.sessions]


def list_windows(session_name: str) -> List[Dict]:
    """Get all windows in a tmux session.

    Args:
        session_name: Name of the tmux session

    Returns:
        List of window info dicts with keys: index, name, pane_count
        Empty list if session not found
    """
    server = get_server()
    session = server.find_where({"session_name": session_name})

    if not session:
        return []

    windows = []
    for window in session.windows:
        windows.append({
            "index": window.index,
            "name": window.name,
            "pane_count": len(window.panes),
        })

    return windows


def capture_window_pane(
    session_name: str,
    window: int = 0,
    pane: int = 0,
    lines: int = 100
) -> Optional[str]:
    """Capture content from a specific window/pane.

    Args:
        session_name: Name of the tmux session
        window: Window index (default 0)
        pane: Pane index within window (default 0)
        lines: Number of lines to capture

    Returns:
        Captured pane content as string, or None if not found
    """
    server = get_server()
    session = server.find_where({"session_name": session_name})

    if not session:
        return None

    # Ensure window and pane are integers
    window = int(window)
    pane = int(pane)

    if window >= len(session.windows):
        return None

    target_window = session.windows[window]

    if pane >= len(target_window.panes):
        return None

    target_pane = target_window.panes[pane]

    try:
        captured = target_pane.cmd('capture-pane', '-p', '-S', f'-{lines}')
        return '\n'.join(captured.stdout) if captured.stdout else None
    except Exception:
        return None


def capture_pane(session_name: str, lines: int = 100) -> Optional[str]:
    """Capture content from tmux pane (window 0, pane 0).

    This is a convenience wrapper around capture_window_pane for backwards
    compatibility.

    Args:
        session_name: Name of the tmux session
        lines: Number of lines to capture from pane history

    Returns:
        Captured pane content as string, or None if session not found
    """
    return capture_window_pane(session_name, window=0, pane=0, lines=lines)


def send_keys(session_name: str, keys: str, enter: bool = True, window: int = 0, pane: int = 0) -> bool:
    """Send keys to a tmux session.

    Args:
        session_name: Name of the tmux session
        keys: The keys/text to send
        enter: Whether to press Enter after sending keys (default True)
        window: Window index (default 0)
        pane: Pane index (default 0)

    Returns:
        True if successful, False otherwise
    """
    server = get_server()
    session = server.find_where({"session_name": session_name})

    if not session:
        return False

    # Ensure window and pane are integers
    window = int(window)
    pane = int(pane)

    # Get the target window
    if window >= len(session.windows):
        return False

    target_window = session.windows[window]

    # Get the target pane
    if pane >= len(target_window.panes):
        return False

    target_pane = target_window.panes[pane]

    try:
        target_pane.send_keys(keys, enter=enter)
        return True
    except Exception:
        return False
