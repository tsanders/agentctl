"""Automatic phase detection for task workflow

Monitors task state and automatically advances workflow phases based on:
- agent_created: Detects tmux session + git branch + worktree
- initialization: Detects Claude/agent process running in tmux
- agent_review: Detects code review agent process
"""

from pathlib import Path
from typing import Optional, Dict
import subprocess

from agentctl.core import task_md
from agentctl.core.task_store import get_task, update_task
from agentctl.core.tmux import session_exists, capture_pane


def check_and_update_phase(task_id: str) -> Optional[str]:
    """Check if task phase should be auto-updated based on current state.

    Args:
        task_id: Task ID to check

    Returns:
        New phase if updated, None if no change
    """
    task = get_task(task_id)
    if not task:
        return None

    current_phase = task.get('phase')
    if not current_phase:
        return None

    # Don't auto-update if already past initialization
    phases_to_check = ['preparation', 'registered', 'agent_created', 'initialization']
    if current_phase not in phases_to_check:
        return None

    # Check for agent_created phase
    if current_phase in ['preparation', 'registered']:
        if _detect_agent_created(task):
            new_phase = 'agent_created'
            if update_task(task_id, {'phase': new_phase}):
                return new_phase

    # Check for initialization phase
    if current_phase == 'agent_created':
        if _detect_initialization(task):
            new_phase = 'initialization'
            if update_task(task_id, {'phase': new_phase}):
                return new_phase

    # Check for agent_review phase
    if current_phase in ['initialization', 'implementation']:
        if _detect_agent_review(task):
            new_phase = 'agent_review'
            if update_task(task_id, {'phase': new_phase}):
                return new_phase

    return None


def _detect_agent_created(task: Dict) -> bool:
    """Detect if agent has been fully created.

    Checks for:
    - tmux session exists
    - git branch exists
    - worktree path exists
    """
    # Check tmux session
    tmux_session = task.get('tmux_session')
    if not tmux_session or not session_exists(tmux_session):
        return False

    # Check git branch
    git_branch = task.get('git_branch')
    if not git_branch:
        return False

    # Check worktree path
    worktree_path = task.get('worktree_path')
    if not worktree_path:
        return False

    worktree = Path(worktree_path)
    if not worktree.exists() or not worktree.is_dir():
        return False

    return True


def _detect_initialization(task: Dict) -> bool:
    """Detect if agent is initializing (Claude/agent process running).

    Checks for:
    - Claude process running in tmux session
    - Or other agent processes (codex, aider, etc.)
    """
    tmux_session = task.get('tmux_session')
    if not tmux_session or not session_exists(tmux_session):
        return False

    # Capture recent output from tmux session
    try:
        output = capture_pane(tmux_session, lines=100)
        if not output:
            return False

        # Look for agent process indicators
        agent_indicators = [
            'claude',           # Claude Code
            'anthropic',        # Anthropic CLI
            'codex',           # OpenAI Codex
            'aider',           # Aider
            'cursor',          # Cursor
            'Model:',          # Common prompt header
            'Assistant:',      # Common chat format
            'Using tool',      # Tool usage
            'Running:',        # Command execution
        ]

        output_lower = output.lower()
        return any(indicator.lower() in output_lower for indicator in agent_indicators)

    except Exception:
        return False


def _detect_agent_review(task: Dict) -> bool:
    """Detect if code review agent is running.

    Checks for:
    - Second tmux window/pane in agent session
    - Code review agent process indicators
    """
    tmux_session = task.get('tmux_session')
    if not tmux_session or not session_exists(tmux_session):
        return False

    try:
        # Check if there are multiple panes/windows (indicating review agent)
        result = subprocess.run(
            ['tmux', 'list-panes', '-t', tmux_session, '-F', '#{pane_index}'],
            capture_output=True,
            text=True,
            timeout=2
        )

        if result.returncode == 0:
            pane_count = len(result.stdout.strip().split('\n'))
            if pane_count < 2:
                return False  # Need at least 2 panes for review

        # Capture output from all panes to look for review indicators
        output = capture_pane(tmux_session, lines=50)
        if not output:
            return False

        # Look for code review indicators
        review_indicators = [
            'code-reviewer',
            'review',
            'reviewing',
            'superpowers:code-reviewer',
            'code review',
            'reviewing code',
            'analysis complete',
            'review complete',
        ]

        output_lower = output.lower()
        return any(indicator.lower() in output_lower for indicator in review_indicators)

    except Exception:
        return False
