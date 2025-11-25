# Task File Copy to Working Directory

**Date:** 2025-01-25
**Status:** Approved

## Overview

When starting a task, copy the source task markdown file to `TASK.md` in the working directory. This gives the agent direct access to task context without needing to know where task files live.

## Key Behaviors

- Exact copy of source markdown (frontmatter + body)
- Overwrites any existing `TASK.md` silently
- Works with both worktree and branch-based workflows
- Source file is authoritative; local changes to `TASK.md` are not synced back
- One-time copy at task start; manual refresh available via CLI

## Entry Points

1. **TUI** - Start task action (primary)
2. **CLI** - `agentctl task start <task-id>`

Both use the same `start_task()` function which handles the copy.

## Implementation

### Core Function

New function in `core/task.py`:

```python
def copy_task_file_to_workdir(task_id: str, work_dir: Path) -> Path:
    """
    Copy source task markdown to TASK.md in working directory.

    Args:
        task_id: Task ID
        work_dir: Target working directory

    Returns:
        Path to the created TASK.md
    """
```

**Logic:**
1. Look up task in database to get `project_id` and `source`
2. If `source == 'markdown'`: copy original file from `{project.tasks_path}/{task_id}.md`
3. If `source == 'database'`: generate markdown from database fields
4. Write to `{work_dir}/TASK.md`

### Integration

- `start_task()` calls `copy_task_file_to_workdir()` after creating tmux session
- TUI's start task action uses the same `start_task()` function (no changes needed)

### Manual Refresh

New CLI command: `agentctl task refresh <task-id>`

Re-copies the source task file to the working directory. Useful if you update the source while a task is running.

## Files to Modify

1. **`core/task.py`** - Add `copy_task_file_to_workdir()`, call from `start_task()`
2. **`cli.py`** - Add `task refresh` command

## Future Enhancements

- Automatic file watching (if needed, keep lightweight)
- Two-way sync for agent-written status updates
