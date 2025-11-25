# Markdown Task Storage Design

**Date:** 2025-01-23
**Status:** Approved

## Overview

Migrate from SQLite-only task storage to markdown files as the source of truth, with SQLite maintaining a lightweight index for fast querying. This enables easy editing of tasks in any text editor while preserving TUI functionality.

## Core Principles

- Markdown files are the single source of truth for task data
- SQLite database maintains a lightweight index for fast filtering
- Sync happens on-demand when task list is accessed or modified
- Clean separation: old database tasks remain read-only, new tasks use markdown

## Architecture

### Components

1. **Task Markdown Layer** (`src/agentctl/core/task_md.py`)
   - Parse/write markdown files with YAML frontmatter
   - Validate frontmatter against required schema
   - Handle file I/O with proper error handling
   - Auto-increment task IDs when creating through TUI

2. **Task Sync Layer** (`src/agentctl/core/task_sync.py`)
   - Scan project tasks_path for `.md` files matching pattern
   - Sync markdown → database index (id, agent_status, priority only)
   - Track sync errors for display in TUI
   - Provide validation command

3. **Database Changes:**
   - Add `tasks_path` field to projects table
   - Keep existing tasks table for legacy read-only tasks
   - Add `source` field to tasks: 'database' or 'markdown'
   - Add task_sync_errors table for validation issues

## Markdown File Format

### Structure

```markdown
---
id: RRA-API-0053
title: Implement user authentication
project_id: RRA
repository_id: RRA-API
category: FEATURE
type: feature
priority: medium
agent_status: queued
phase: null
created_at: "2025-01-22T10:30:00"
started_at: null
completed_at: null
git_branch: null
worktree_path: null
tmux_session: null
agent_type: null
commits: 0
---

# Task Description

Detailed task description goes here...
```

### Field Specifications

**Required Fields:**
- `id`: Task identifier matching pattern `PROJECT-CATEGORY-\d{4}`
- `title`: Task title
- `project_id`: Project identifier
- `category`: One of FEATURE, BUG, REFACTOR, DOCS, TEST, CHORE
- `agent_status`: One of queued, running, blocked, completed, failed
- `priority`: One of high, medium, low
- `created_at`: ISO 8601 timestamp

**Optional Fields:**
- `repository_id`: Repository identifier (can be null)
- `type`: Task type string
- `phase`: Current phase
- `started_at`: ISO 8601 timestamp or null
- `completed_at`: ISO 8601 timestamp or null
- `git_branch`: Git branch name or null
- `worktree_path`: Path to worktree or null
- `tmux_session`: tmux session name or null
- `agent_type`: Agent type string or null
- `commits`: Integer count, default 0

### Parsing Strategy

- Use `python-frontmatter` library for YAML frontmatter parsing
- Strict validation on required fields - skip file entirely if invalid
- Store validation errors in `task_sync_errors` table
- Preserve markdown body when updating frontmatter

## Database Schema Changes

### Projects Table

```sql
ALTER TABLE projects ADD COLUMN tasks_path TEXT;
```

- Stores absolute path where task markdown files are located
- Example: `/Users/you/Documents/RRA-Tasks/`
- Null allowed for projects not using markdown tasks

### Tasks Table

```sql
ALTER TABLE tasks ADD COLUMN source TEXT DEFAULT 'database';
```

- Values: 'database' (legacy) or 'markdown' (new system)
- Legacy database tasks remain read-only
- Markdown tasks always read from file, index synced on access

### New task_sync_errors Table

```sql
CREATE TABLE task_sync_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    error_message TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
```

- Tracks validation failures during sync
- Cleared on successful re-sync
- Displayed in TUI with option to view details

### Indexed Fields

Only sync these fields to database for fast filtering:
- id
- agent_status
- priority
- project_id
- repository_id
- category
- source

All other fields read directly from markdown when viewing task details.

## Sync Logic

### When Sync Occurs

- When task list is accessed in TUI
- After any task create/edit/delete operation
- Manual refresh via 'r' key in TUI
- Via CLI: `agentctl task sync`

### Sync Process

1. Get project's `tasks_path` from database
2. Glob for `*.md` files in that directory
3. Parse each file's frontmatter
4. For valid files: Upsert to tasks table (indexed fields + source='markdown')
5. For invalid files: Log error to task_sync_errors table
6. Remove from tasks table any markdown tasks whose files no longer exist
7. Show brief notification: "Synced 15 tasks from markdown"

## Task Operations

### Create Task (via TUI)

1. Get project's tasks_path
2. Scan existing files, find highest number for category
3. Generate next ID (e.g., RRA-API-0053)
4. Create markdown file with template frontmatter
5. Sync to database index
6. Return task to TUI

### Edit Task (via TUI)

1. Read current markdown file
2. Update specified frontmatter fields
3. Preserve markdown body
4. Write back to file
5. Sync changes to database index

### View Task Details

- Always read fresh from markdown file (not from database)
- Ensures TUI shows latest data even if edited externally

### Start/Complete/Delete

- Update markdown file frontmatter
- For worktree creation: update git_branch and worktree_path fields
- Sync to database index

### Manual Refresh (r key)

- Re-run full sync process
- Clear stale sync errors
- Update TUI display

## TUI Changes

### Project Management

**CreateProjectModal:**
- Add Input field for `tasks_path`
- Validate path exists or offer to create directory
- Optional field (can be added later)

**EditProjectModal:**
- Add Input field for `tasks_path` (editable)
- Show current value if set

**ProjectDetailScreen:**
- Display configured tasks path in project info
- Show count of markdown task files found

### Task List

**Source Indicators:**
- Legacy tasks: `[DB] RRA-API-0001` (dimmed color)
- Markdown tasks: `[MD] RRA-API-0053` (normal color)

**Sync Error Banner:**
- If task_sync_errors has entries: "⚠️  3 task files have errors - Press 'v' to validate"
- 'v' key opens validation error detail screen

**Auto-sync Notifications:**
- Brief notification after sync: "Synced 15 tasks"
- Only show if changes detected

### Legacy Task Handling

- Legacy database tasks are read-only in TUI
- Edit/Start/Delete actions disabled with message:
  "Legacy database task - create markdown version to modify"
- Optional: Add convert action to create markdown from database task

## CLI Commands

### Task Validation

```bash
# Validate all task files across all projects
agentctl task validate

# Validate tasks for specific project
agentctl task validate RRA
```

**Output:**
- Lists each invalid file with error details
- Shows: file path, error message, missing/invalid fields
- Exit code 0 if all valid, 1 if errors found

### Manual Sync

```bash
# Force sync all projects
agentctl task sync

# Sync specific project
agentctl task sync RRA
```

**Output:**
- Shows summary: "Synced 15 tasks, 3 errors"
- Lists projects synced
- Exit code 0 on success

### Project Creation (Updated)

```bash
agentctl project create RRA \
  --name "My Project" \
  --tasks-path "/Users/you/Documents/RRA-Tasks"
```

- Add `--tasks-path` parameter (optional)
- Validate path exists or offer to create
- Can be added later via edit command

## Validation Rules

### Field Validation

**Required fields must be present:**
- id, title, project_id, category, agent_status, priority, created_at

**Valid enum values:**
- agent_status: queued, running, blocked, completed, failed
- priority: high, medium, low
- category: FEATURE, BUG, REFACTOR, DOCS, TEST, CHORE

**Format checks:**
- id matches pattern: `^[A-Z]+-[A-Z]+-\d{4}$`
- created_at is valid ISO 8601 timestamp
- started_at, completed_at are valid ISO 8601 or null
- commits is integer ≥ 0

### Error Handling

**File not found:** Log error, skip task, continue sync
**Invalid YAML:** Log to task_sync_errors, show in TUI
**Missing required fields:** Log to task_sync_errors
**Permission errors:** Show error notification, don't crash
**Corrupted files:** Skip, log error with file path
**ID conflicts:** If same task ID exists in DB and markdown, markdown wins

## Implementation Plan

### Phase 1: Database Migration

**File:** `src/agentctl/core/database.py`

- Add `tasks_path` column to projects table
- Add `source` column to tasks table
- Create `task_sync_errors` table
- Update `create_project()` to accept tasks_path
- Update `update_project()` to accept tasks_path
- Migration function to add new columns

### Phase 2: Markdown Layer

**File:** `src/agentctl/core/task_md.py`

Functions to implement:
- `parse_task_file(file_path: Path) -> Dict`
- `write_task_file(file_path: Path, task_data: Dict, body: str)`
- `validate_task_data(data: Dict) -> List[str]` (returns errors)
- `generate_task_template(task_id: str, **fields) -> str`
- `get_next_task_id(tasks_path: Path, project_id: str, category: str) -> str`

Dependencies:
- `python-frontmatter` for parsing
- `pyyaml` for YAML serialization

### Phase 3: Sync Layer

**File:** `src/agentctl/core/task_sync.py`

Functions to implement:
- `sync_project_tasks(project_id: str) -> SyncResult`
- `sync_all_tasks() -> Dict[str, SyncResult]`
- `clear_sync_errors(project_id: str)`
- `get_sync_errors(project_id: Optional[str]) -> List[Dict]`

SyncResult dataclass:
- synced_count: int
- error_count: int
- errors: List[str]

### Phase 4: Update Task Operations

**File:** `src/agentctl/core/task.py`

Modify existing functions to:
- Check task source (database vs markdown)
- Route to appropriate handler
- For markdown tasks: use task_md functions
- For database tasks: use existing database functions

### Phase 5: CLI Updates

**File:** `src/agentctl/cli.py`

- Add `--tasks-path` to `project create` command
- Add `--tasks-path` to `project edit` command (if exists)
- Add `task validate` command
- Add `task sync` command
- Update `task create` to use markdown if project has tasks_path

### Phase 6: TUI Updates

**File:** `src/agentctl/tui.py`

- Update `CreateProjectModal` - add tasks_path Input
- Update `EditProjectModal` - add tasks_path Input
- Update `ProjectDetailScreen` - show tasks_path info
- Update `TaskManagementScreen`:
  - Add source indicator column
  - Add sync error banner
  - Trigger sync on mount
  - Add 'v' key binding for validation view
- Update `TaskDetailScreen`:
  - Disable edit/start/delete for legacy tasks
  - Show source indicator
- Update all task operations to trigger sync after changes

### Phase 7: Testing

- Test task creation via TUI
- Test external file creation/editing
- Test sync with invalid files
- Test validation command
- Test legacy task read-only behavior
- Test migration scenarios

## Rollback Safety

- Database changes are additive (no data deletion)
- Old database tasks remain untouched and functional
- New markdown system is opt-in per project (via tasks_path)
- Can revert by not setting tasks_path on projects
- No breaking changes to existing workflows

## Future Enhancements

- Background file watcher for automatic sync
- Bulk convert database tasks to markdown
- Task templates for common task types
- Markdown body rich editor in TUI
- Git integration for task file versioning
