# Multi-Agent Watch Screen Design

## Overview

A dedicated TUI screen for monitoring many Claude Code agents simultaneously with quick approval capabilities. Scales to dozens of agents with compact 3-4 line output cards and keyboard-driven approval workflows.

## Entry Points

- `agentctl watch` - New CLI command that launches directly into watch mode
- `w` key from main dashboard - Opens watch screen (return with `Escape`)

## Core Capabilities

- Display 3-4 lines of live output per agent in compact card format
- Auto-discover all `agent-*` tmux sessions
- Auto-sort agents needing attention to the top
- Quick approval via keyboard (per-agent, navigated, or global)
- Scale to dozens of agents with scrolling

## Agent Card Anatomy

```
┌─ RRA-API-0082 ──────────────────── 🟠 WAITING ─┐
│ Do you want to create test_auth.py?            │
│ ❯ 1. Yes                                       │
│   2. Yes, allow all edits...                   │
└────────────────────────────────────────────────┘
```

Each card shows: task ID, health icon, and last 3-4 lines of parsed output. Waiting agents get highlighted borders.

## Output Parsing & Cleanup

Raw tmux output includes blank lines, ANSI escape codes, spinner frames, and noise. Processing pipeline:

1. **Capture** - Grab last ~50 lines from tmux pane
2. **Strip ANSI** - Remove color codes, cursor movements, escape sequences
3. **Collapse whitespace** - Multiple blank lines → single line; trim trailing spaces
4. **Filter noise** - Remove spinner frames, progress bar updates, repeated status lines
5. **Extract meaningful content** - Detect and prioritize:
   - Prompt blocks (the "Do you want to..." sections)
   - Error messages
   - Completion summaries
   - Last meaningful output line

### Smart Prompt Extraction

When a "waiting for input" state is detected, parse the prompt structure:

```python
{
    "question": "Do you want to create test_auth.py?",
    "options": ["Yes", "Yes, allow all edits...", "Type here..."],
    "selected": 0,  # Currently highlighted option
}
```

**Fallback:** If parsing fails, show last N non-empty lines with basic cleanup.

## View Modes

Three switchable view modes, toggled with keyboard shortcuts:

### Grid View (`g` key)

```
┌─ RRA-API-0082 ─── 🟠 ─┐  ┌─ RRA-WEB-0103 ─── 🟢 ─┐  ┌─ RRA-BUG-0044 ─── 🟢 ─┐
│ Create test_auth.py?  │  │ Working...            │  │ Running tests...     │
│ ❯ 1. Yes              │  │ Implementing auth     │  │ pytest src/tests/    │
│   2. Yes, allow all   │  │ middleware for...     │  │ ====== 12 passed     │
└───────────────────────┘  └───────────────────────┘  └───────────────────────┘
```

- 2-3 columns depending on terminal width
- Scrollable when agents exceed viewport
- Waiting agents highlighted with distinct border color

### Priority Stack View (`s` key)

```
🟠 NEEDS ATTENTION (2)
┌─ RRA-API-0082 ────────────────────────────────────────────────────────────┐
│ Do you want to create test_auth.py?                                       │
│ ❯ 1. Yes  2. Yes, allow all  3. Type here...                   [1] Approve│
└───────────────────────────────────────────────────────────────────────────┘
┌─ RRA-DB-0055 ─────────────────────────────────────────────────────────────┐
│ Run migrations? [Y/n]                                          [2] Approve│
└───────────────────────────────────────────────────────────────────────────┘

🟢 ACTIVE (8)
  RRA-WEB-0103  Working... Implementing auth middleware
  RRA-BUG-0044  Running tests... 12 passed
  (6 more)
```

- Waiting agents expanded at top with full prompt details
- Active/idle agents collapsed to single-line summaries

### Filtered Tabs View (`f` key)

```
 [Attention: 2]  [Active: 8]  [Idle: 3]  [All: 13]
                     ▲ current tab
```

- Tab bar at top, switch with `Tab` or `1-4`
- Shows only agents matching current filter
- Uses grid layout within each tab

## Keyboard Interaction

### Navigation

| Key | Action |
|-----|--------|
| `↑/↓/←/→` or `hjkl` | Navigate between agent cards |
| `Tab` | Cycle through agents needing attention |
| `Enter` | Expand focused card (show more output lines) |
| `Escape` | Return to dashboard / collapse expanded card |

### Per-Agent Approval (focused card)

| Key | Action |
|-----|--------|
| `y` or `1` | Send "1" (Yes/first option) to focused agent |
| `n` or `2` | Send "2" (No/second option) |
| `3`, `4` | Send corresponding menu option |
| `t` | Open text input modal → type custom response → Enter to send |

### Global Actions

| Key | Action |
|-----|--------|
| `a` | **Approve all** - Send "1" to ALL agents currently waiting |
| `A` | Approve all with confirmation prompt first |
| `r` | Refresh all agent outputs immediately |

### View Switching

| Key | Action |
|-----|--------|
| `g` | Grid view |
| `s` | Stack (priority) view |
| `f` | Filtered tabs view |
| `?` | Show help overlay with all keybindings |

### Safety

The `a` (approve all) sends option 1 only. If an agent's prompt is destructive (detected keywords like "delete", "remove", "overwrite"), it gets skipped with a warning indicator.

## Technical Implementation

### New Files

- `src/agentctl/tui/watch_screen.py` - The main WatchScreen class
- `src/agentctl/core/output_parser.py` - Output cleaning and prompt extraction

### Modifications

- `src/agentctl/cli.py` - Add `agentctl watch` command
- `src/agentctl/tui.py` - Add `w` keybinding to open WatchScreen from dashboard

### Key Classes

```python
# watch_screen.py
class AgentCard(Static):
    """Compact widget showing one agent's output"""
    task_id: str
    health: str
    parsed_output: ParsedOutput

class WatchScreen(Screen):
    """Multi-agent monitoring screen"""
    view_mode: Literal["grid", "stack", "filtered"]
    agents: List[AgentCard]
    focused_index: int

# output_parser.py
class ParsedOutput:
    """Cleaned output with extracted prompt info"""
    raw_lines: List[str]
    clean_lines: List[str]  # Max 4 lines
    prompt: Optional[PromptInfo]  # Extracted question/options

class PromptInfo:
    question: str
    options: List[str]
    selected_index: int
```

### Refresh Strategy

- Poll tmux every 1-2 seconds (configurable)
- Only re-parse output if content hash changed
- Batch updates to avoid UI flicker

### Tmux Interaction

- Use existing `capture_window_pane()` for output
- Use existing `send_keys()` for approvals

## Implementation Plan

### Phase 1: Output Parser
- Create `output_parser.py` with ANSI stripping, whitespace cleanup
- Add prompt detection and extraction logic
- Add unit tests for parsing various Claude Code output patterns

### Phase 2: Agent Card Widget
- Create `AgentCard` widget with compact 3-4 line display
- Integrate with output parser
- Add health state styling (border colors, icons)

### Phase 3: Watch Screen Foundation
- Create `WatchScreen` with basic grid layout
- Add auto-discovery of `agent-*` tmux sessions
- Add refresh polling loop
- Wire up `agentctl watch` CLI command

### Phase 4: View Modes
- Implement grid view with responsive columns
- Implement priority stack view with collapsible sections
- Implement filtered tabs view
- Add `g`/`s`/`f` keybindings to switch

### Phase 5: Navigation & Approval
- Add arrow/hjkl navigation between cards
- Add per-agent approval keys (`y`, `n`, `1-4`)
- Add text input modal for custom responses
- Add global approve-all (`a`) with safety checks

### Phase 6: Polish
- Add `w` keybinding from main dashboard
- Add `?` help overlay
- Add configurable refresh interval
- Performance tuning for dozens of agents
