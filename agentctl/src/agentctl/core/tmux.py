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
