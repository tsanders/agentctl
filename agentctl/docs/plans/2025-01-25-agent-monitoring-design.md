# Agent Monitoring Design

**Date:** 2025-01-25
**Status:** Approved

## Overview

Add comprehensive agent process monitoring to agentctl, enabling visibility into Claude Code agents running in tmux sessions, activity tracking, and health checks.

## Goals

1. **Visibility** - Know which agents are running, idle, or crashed across all tmux sessions
2. **Activity tracking** - See what agents are currently doing (recent output, commits made)
3. **Health checks** - Detect when an agent is stuck or needs attention

## Health States

| State | Icon | Meaning |
|-------|------|---------|
| Active | 🟢 | "esc to interrupt" visible, recent output |
| Idle | 🟡 | No output for 1+ min, but process running |
| Waiting | 🟠 | Detected input prompt patterns |
| Exited | 🔴 | Process no longer running in session |
| Error | ⚠️ | Error patterns detected in recent output |

## Detection Logic

**Identification:** Match agents to tasks via tmux session name (already tracked per task).

**Health signals:**
- `ACTIVE_PATTERN = "esc to interrupt"` - Claude is working
- `IDLE_WARNING_SECONDS = 60` - 1 minute threshold
- `ERROR_PATTERNS = ["error", "failed", "exception", "traceback"]`
- `INPUT_PATTERNS = ["? ", "[Y/n]", "[y/N]", "Press enter", "Do you want"]`

## Core Module

**New file:** `src/agentctl/core/agent_monitor.py`

### Functions

```python
def get_session_status(session_name: str) -> dict:
    """Returns process state, last output time, recent output lines"""

def detect_health_state(session_info: dict) -> str:
    """Analyzes output to determine health (active/idle/waiting/exited/error)"""

def get_all_agent_statuses() -> list[dict]:
    """Scans all task tmux sessions and returns unified status"""
```

### Data Structure

```python
{
    'task_id': 'TEST-FEATURE-0001',
    'tmux_session': 'agent-TEST-FEATURE-0001',
    'health': 'active',  # active|idle|waiting|exited|error
    'process_running': True,
    'last_output_ago': 5,  # seconds
    'recent_output': ['line1', 'line2', ...],
    'git_commits_today': 3,
    'warnings': []  # ['error detected', 'waiting for input']
}
```

## TUI Integration

### Task List

Add "A" (Agent) column showing health indicator:

```
| ID                | Title                    | S  | P  | T | A  |
| TEST-FEATURE-0001 | Implement new feature... | 🟢 | 🔴 | ✓ | 🟢 |
| TEST-BUG-0002     | Fix login bug            | 🟢 | 🟡 | ✓ | 🟡 |
| TEST-FEATURE-0003 | Add dark mode            | ⚪ | 🟢 | - | -  |
```

- Refresh every 5 seconds when visible

### Task Detail View

Add agent status line:

```
Agent: 🟢 ACTIVE (working for 2m, 3 commits today)
```

Or with warnings:
```
Agent: 🟠 WAITING - detected input prompt (idle 45s)
Output: "? Do you want to proceed [Y/n]"
```

- Refresh every 2 seconds

### New AgentsScreen

Dedicated view for monitoring all agents. Access via `a` key from main dashboard.

```
🤖 ACTIVE AGENTS
┌────────────────────┬──────────┬─────────┬──────────────────────────────┐
│ Task               │ Health   │ Idle    │ Recent Output                │
├────────────────────┼──────────┼─────────┼──────────────────────────────┤
│ TEST-FEATURE-0001  │ 🟢 ACTIVE │ 5s      │ Writing file src/app.py...   │
│ TEST-BUG-0002      │ 🟠 WAITING│ 45s     │ ? Proceed with changes [Y/n] │
│ TEST-FEATURE-0003  │ 🟡 IDLE   │ 2m 30s  │ ✓ Task completed             │
│ TEST-CHORE-0004    │ 🔴 EXITED │ 5m      │ Error: connection refused    │
└────────────────────┴──────────┴─────────┴──────────────────────────────┘
```

**Key bindings:**
- `j/k` - Navigate agents
- `Enter` - Jump to task detail
- `a` - Attach to tmux session (suspends TUI)
- `r` - Refresh now
- `q/Esc` - Back

**Features:**
- Auto-refresh every 2 seconds
- Only shows tasks with active tmux sessions
- Sorted by health (errors/waiting first, then idle, then active)

## CLI Commands

### `agentctl agents`

```bash
$ agentctl agents

🤖 ACTIVE AGENTS (4)

  TEST-FEATURE-0001  🟢 ACTIVE   5s    Writing file src/app.py...
  TEST-BUG-0002      🟠 WAITING  45s   ? Proceed with changes [Y/n]
  TEST-FEATURE-0003  🟡 IDLE     2m    ✓ Task completed
  TEST-CHORE-0004    🔴 EXITED   5m    Error: connection refused

Attach: agentctl attach <task-id>
```

**Options:**
- `agentctl agents` - List all agents with status
- `agentctl agents --watch` - Live updating view (refreshes every 2s)

### `agentctl attach <task-id>`

Attach to a task's tmux session.

**Exit codes:**
- `0` - All agents healthy
- `1` - At least one agent needs attention

## Implementation Order

1. Core module - `agent_monitor.py` with all detection logic
2. CLI command - Quick to test, validates the core works
3. TUI task list - Add "A" column with health indicator
4. TUI task detail - Add agent status line
5. TUI AgentsScreen - Dedicated monitoring view

## Dependencies

- `libtmux` - Already installed, used for session inspection
- No new dependencies needed
