"""Git integration for agentctl"""

import git
from pathlib import Path
from typing import Optional


def get_repo(path: Optional[Path] = None) -> git.Repo:
    """Get git repository"""
    if path is None:
        path = Path.cwd()
    return git.Repo(path, search_parent_directories=True)


def create_branch(branch_name: str, base: str = "main", repo_path: Optional[Path] = None) -> str:
    """Create a new git branch"""
    repo = get_repo(repo_path)

    # Check if branch exists
    if branch_name in repo.heads:
        return branch_name

    # Create new branch from base
    try:
        base_branch = repo.heads[base]
    except (IndexError, AttributeError):
        # Try 'master' if 'main' doesn't exist
        base_branch = repo.heads.get("master", repo.head)

    new_branch = repo.create_head(branch_name, base_branch)
    new_branch.checkout()

    return branch_name


def checkout_branch(branch_name: str):
    """Checkout an existing branch"""
    repo = get_repo()
    repo.heads[branch_name].checkout()


def get_current_branch() -> str:
    """Get the current branch name"""
    repo = get_repo()
    return repo.active_branch.name


def merge_branch(branch_name: str, target: str = "main"):
    """Merge a branch into target"""
    repo = get_repo()

    # Checkout target branch
    repo.heads[target].checkout()

    # Merge the branch
    repo.git.merge(branch_name)

    return target


def delete_branch(branch_name: str, force: bool = False):
    """Delete a branch"""
    repo = get_repo()

    if force:
        repo.git.branch("-D", branch_name)
    else:
        repo.git.branch("-d", branch_name)


def get_branch_commits(branch_name: str) -> int:
    """Get number of commits on a branch"""
    repo = get_repo()
    return len(list(repo.iter_commits(branch_name)))


def has_uncommitted_changes() -> bool:
    """Check if there are uncommitted changes"""
    repo = get_repo()
    return repo.is_dirty() or len(repo.untracked_files) > 0
