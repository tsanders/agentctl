"""Git worktree management for agentctl"""

from pathlib import Path
from typing import Optional, Dict, List
import subprocess


def get_worktree_path(repository_path: Path, task_id: str) -> Path:
    """
    Calculate worktree path as sibling to main repository

    Example:
        repository_path: /path/to/my-repo
        task_id: RRA-API-0042
        returns: /path/to/my-repo-RRA-API-0042
    """
    parent = repository_path.parent
    repo_name = repository_path.name
    worktree_name = f"{repo_name}-{task_id}"
    return parent / worktree_name


def get_branch_name(category: str, task_id: str) -> str:
    """
    Generate branch name based on task category

    Args:
        category: Task category (FEATURE, BUG, REFACTOR, etc.)
        task_id: Task ID (e.g., RRA-API-0042)

    Returns:
        Branch name (e.g., feature/RRA-API-0042)
    """
    category_map = {
        "FEATURE": "feature",
        "BUG": "bugfix",
        "REFACTOR": "refactor",
        "DOCS": "docs",
        "TEST": "test",
        "CHORE": "chore"
    }

    prefix = category_map.get(category.upper(), "feature")
    return f"{prefix}/{task_id}"


def create_worktree(
    repository_path: Path,
    task_id: str,
    category: str,
    base_branch: str = "main"
) -> Dict[str, str]:
    """
    Create a git worktree for a task

    Args:
        repository_path: Path to main repository
        task_id: Task ID
        category: Task category (for branch naming)
        base_branch: Base branch to branch from (default: main)

    Returns:
        Dict with 'worktree_path' and 'branch_name'

    Raises:
        RuntimeError: If git worktree creation fails
    """
    worktree_path = get_worktree_path(repository_path, task_id)
    branch_name = get_branch_name(category, task_id)

    # Check if worktree already exists
    if worktree_path.exists():
        raise RuntimeError(f"Worktree already exists: {worktree_path}")

    try:
        # Create worktree with new branch
        subprocess.run(
            ["git", "worktree", "add", "-b", branch_name, str(worktree_path), base_branch],
            cwd=str(repository_path),
            check=True,
            capture_output=True,
            text=True
        )

        return {
            "worktree_path": str(worktree_path),
            "branch_name": branch_name
        }

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to create worktree: {e.stderr}")


def remove_worktree(repository_path: Path, worktree_path: Path, force: bool = False) -> None:
    """
    Remove a git worktree

    Args:
        repository_path: Path to main repository
        worktree_path: Path to worktree to remove
        force: Force removal even if worktree has uncommitted changes

    Raises:
        RuntimeError: If git worktree removal fails
    """
    if not worktree_path.exists():
        return  # Already removed

    try:
        cmd = ["git", "worktree", "remove"]
        if force:
            cmd.append("--force")
        cmd.append(str(worktree_path))

        subprocess.run(
            cmd,
            cwd=str(repository_path),
            check=True,
            capture_output=True,
            text=True
        )

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to remove worktree: {e.stderr}")


def list_worktrees(repository_path: Path) -> List[Dict[str, str]]:
    """
    List all worktrees for a repository

    Args:
        repository_path: Path to main repository

    Returns:
        List of dicts with 'path', 'branch', 'commit' for each worktree
    """
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(repository_path),
            check=True,
            capture_output=True,
            text=True
        )

        worktrees = []
        current_worktree = {}

        for line in result.stdout.strip().split('\n'):
            if line.startswith('worktree '):
                if current_worktree:
                    worktrees.append(current_worktree)
                current_worktree = {'path': line.split(' ', 1)[1]}
            elif line.startswith('branch '):
                current_worktree['branch'] = line.split(' ', 1)[1]
            elif line.startswith('HEAD '):
                current_worktree['commit'] = line.split(' ', 1)[1]

        if current_worktree:
            worktrees.append(current_worktree)

        return worktrees

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to list worktrees: {e.stderr}")


def worktree_exists(repository_path: Path, task_id: str) -> bool:
    """Check if a worktree exists for a task"""
    worktree_path = get_worktree_path(repository_path, task_id)
    return worktree_path.exists()
