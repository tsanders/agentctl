"""tmux integration for agentctl"""

import libtmux
from pathlib import Path
from typing import Optional


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


def capture_pane(session_name: str, lines: int = 100) -> Optional[str]:
    """Capture content from tmux pane.

    Args:
        session_name: Name of the tmux session
        lines: Number of lines to capture from pane history

    Returns:
        Captured pane content as string, or None if session not found
    """
    server = get_server()
    session = server.find_where({"session_name": session_name})

    if not session:
        return None

    # Get the active pane from the first window
    if not session.windows:
        return None

    window = session.windows[0]
    if not window.panes:
        return None

    pane = window.panes[0]

    # Capture pane content
    try:
        # Use cmd to capture pane content with history
        captured = pane.cmd('capture-pane', '-p', '-S', f'-{lines}')
        # stdout is a list of lines - join them back together
        return '\n'.join(captured.stdout) if captured.stdout else None
    except Exception:
        return None


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
