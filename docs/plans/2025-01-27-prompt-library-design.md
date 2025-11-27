# Prompt Library Design

A system for storing, organizing, and reusing prompts sent to agent tmux sessions.

## Goals

- **Quick recall**: Find and resend prompts from history
- **Templates**: Save standard prompts for common situations
- **Workflows**: Suggest prompts based on task phase
- **Reusability**: All prompts global, available across all tasks/agents

## Data Model

Three tables in the existing SQLite database.

### `prompts` - The prompt library

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| text | TEXT NOT NULL | The prompt content |
| title | TEXT | Optional short name (e.g., "Fix failing tests") |
| category | TEXT | Category (e.g., "debugging", "code-review", "testing") |
| tags | TEXT | Comma-separated tags |
| phase | TEXT | Associated workflow phase (nullable) |
| is_bookmarked | BOOLEAN | Default FALSE |
| use_count | INTEGER | Default 0, incremented on each use |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

### `prompt_history` - Log of sent prompts

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| prompt_id | TEXT FK | Reference to prompts table (nullable for ad-hoc) |
| prompt_text | TEXT NOT NULL | Snapshot of what was sent |
| task_id | TEXT | Which task received it |
| phase | TEXT | Phase when sent |
| sent_at | TIMESTAMP | |

### `prompt_workflows` - Phase-based suggestions (future)

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| phase | TEXT NOT NULL | Workflow phase |
| prompt_id | TEXT FK | Reference to prompts table |
| order_index | INTEGER | Sequence order within phase |

## User Interface

### Prompt Library Screen

Access via `u` from dashboard.

**Display:**
- DataTable with columns: Title, Category, Phase, Tags, Use Count, Last Used
- Filter modes: All, Bookmarked, By Category, By Phase

**Key bindings:**
- `n` - New prompt
- `e` - Edit selected prompt
- `d` - Delete prompt
- `b` - Toggle bookmark
- `Enter` - Quick-send to last active task
- `/` - Search/filter
- `f` - Cycle filter modes
- `Escape` - Back to dashboard

### Enhanced Prompt Bar

When pressing `p` in TaskDetailScreen or TaskManagementScreen:

- `↑`/`↓` - Browse recent history inline
- `Ctrl+r` - Open searchable history picker
- `Tab` - Autocomplete from bookmarked prompts
- Typing filters suggestions

### Phase Suggestions Panel (future)

In TaskDetailScreen, shows "Suggested for [phase]:" with quick-send keys (`1`, `2`, `3`).

## Workflows

### Sending a Prompt

1. Press `p` to open inline prompt bar
2. Type new prompt OR `↑` for history OR `Ctrl+r` to search
3. Enter sends, Escape cancels
4. On send:
   - Save to `prompt_history`
   - Increment `use_count` if from library
   - Show success notification

### Saving to Library

- After sending: notification offers "[s] Save to library"
- From library screen: press `n` to create new
- Auto-suggest saving for prompts used 3+ times

### Bookmarking

- Press `b` in library screen to toggle
- Bookmarked prompts appear first in autocomplete
- Visual indicator in prompt bar when browsing

### History Recall

- `↑`/`↓` cycles recent (last 20)
- `Ctrl+r` opens full searchable list
- Shows: prompt preview, task sent to, timestamp

## Implementation Phases

### Phase 1: Foundation

- Add database tables (`prompts`, `prompt_history`)
- Create `prompt_store.py` module with CRUD operations
- Auto-log every sent prompt to history
- Basic Prompt Library Screen with list view

### Phase 2: Quick Access

- Add `↑`/`↓` history navigation in prompt bar
- Add `Ctrl+r` searchable history picker
- Add "Save to library" action after sending

### Phase 3: Organization

- Add categories, tags, bookmarking
- Filter modes in library screen
- Bookmarked prompts in autocomplete

### Phase 4: Phase Suggestions

- Add `prompt_workflows` table
- Suggested prompts panel in TaskDetailScreen
- Configure prompt-to-phase mappings

## Technical Notes

- Storage: Existing SQLite database (`agentctl.db`)
- Prompts are global (not project-scoped)
- `prompt_store.py` follows same pattern as `task_store.py`
- History captures context: task_id, phase at send time
