"""Configuration management for agentctl."""

from pathlib import Path
from typing import Dict, List, Optional

import yaml


def get_config_dir() -> Path:
    """Get the agentctl config directory."""
    return Path.home() / ".agentctl"


def get_global_config() -> Dict:
    """Load global configuration from ~/.agentctl/config.yaml."""
    config_file = get_config_dir() / "config.yaml"

    if not config_file.exists():
        return {}

    try:
        with open(config_file) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def get_window_config(task_id: Optional[str] = None) -> List[Dict]:
    """Get window configuration with fallbacks.

    Priority:
    1. Task-specific override (future)
    2. Global config
    3. Empty list (auto-discovery)

    Args:
        task_id: Optional task ID for task-specific overrides

    Returns:
        List of window config dicts with keys: index, name, role (optional)
    """
    # TODO: Add task-specific override lookup

    global_config = get_global_config()
    windows = global_config.get("windows", [])

    # Ensure each window has required fields
    result = []
    for w in windows:
        if isinstance(w, dict) and "index" in w:
            result.append({
                "index": w["index"],
                "name": w.get("name", f"Window {w['index']}"),
                "role": w.get("role"),
            })

    return result


def get_window_name(task_id: Optional[str], window_index: int) -> str:
    """Get display name for a window.

    Args:
        task_id: Optional task ID for task-specific config
        window_index: The window index

    Returns:
        Window name (e.g., "Claude") or fallback ("Window 0")
    """
    windows = get_window_config(task_id)

    for w in windows:
        if w["index"] == window_index:
            return w["name"]

    return f"Window {window_index}"


def get_window_role(task_id: Optional[str], window_index: int) -> Optional[str]:
    """Get role for a window (e.g., 'implementer', 'reviewer').

    Args:
        task_id: Optional task ID for task-specific config
        window_index: The window index

    Returns:
        Role string or None if not configured
    """
    windows = get_window_config(task_id)

    for w in windows:
        if w["index"] == window_index:
            return w.get("role")

    return None
