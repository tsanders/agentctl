# agentctl

> AI Agent Control Center - Manage your coding agents

## Overview

`agentctl` is a CLI tool for managing multiple AI coding agents working on tasks in parallel. It provides:

- Task tracking and management
- Git branch automation
- tmux session management
- Agent status monitoring
- Event logging and history

## Installation

```bash
# Clone the repository
cd agentctl

# Install with uv
uv venv
uv pip install -e .
```

## Quick Start

```bash
# Initialize the database
uv run agentctl init

# Create a task
uv run agentctl task create RRA-API-0001 \
  --title "Implement user authentication" \
  --project RRA \
  --category FEATURE \
  --priority high

# Start working on a task
uv run agentctl task start RRA-API-0001

# Check agent status
uv run agentctl status

# List all tasks
uv run agentctl task list

# List active agents
uv run agentctl agent list
```

## Commands

### Core Commands

- `agentctl init` - Initialize the database
- `agentctl status` - Show quick status of all agents

### Task Management

- `agentctl task create` - Create a new task
- `agentctl task start` - Start working on a task (creates git branch + tmux session)
- `agentctl task list` - List tasks with optional filters

### Agent Management

- `agentctl agent list` - List all active agents

## How It Works

When you start a task with `agentctl task start`:

1. Creates a git branch: `feature/TASK-ID` (or `bugfix/`, `refactor/`)
2. Creates a tmux session: `agent-TASK-ID`
3. Updates task status to "running"
4. Logs the event to the database

You can then attach to the tmux session and run your agent CLI (Claude Code, Cursor, etc.) within that session.

## Database

`agentctl` uses SQLite to store:
- Task information (id, project, category, status, priority, etc.)
- Events (task started, commits, phase changes, etc.)
- Checkpoints (for resuming work)

Database location: `~/.agentctl/agentctl.db`

## Task ID Format

Tasks follow the format: `[PROJECT]-[CATEGORY]-[NNNN]`

Examples:
- `RRA-API-0082` - API feature for RRA project
- `RRA-BUG-0103` - Bug fix for RRA project
- `RRA-WEB-0290` - Web frontend feature for RRA project

## Development

```bash
# Install development dependencies
uv pip install -e ".[dev]"

# Run tests (when implemented)
pytest

# Format code
black src/

# Lint
ruff check src/
```

## Roadmap

- [x] Basic task management
- [x] Git integration
- [x] tmux session management
- [x] Agent status tracking
- [ ] Task pause/resume
- [ ] Obsidian sync integration
- [ ] TUI dashboard
- [ ] Background daemon
- [ ] Notification system
- [ ] Review workflow
- [ ] Statistics and analytics

## License

MIT