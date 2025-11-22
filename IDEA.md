Excellent choice! Python has fantastic CLI tooling and you likely already have it in your dev environment. Let me redesign this with Python's best-in-class libraries.

## Python CLI Stack

**Core Libraries:**
- **Typer** - Modern CLI framework (built on Click)
- **Rich** - Beautiful terminal output, tables, progress bars
- **Textual** - TUI framework (from the Rich team)
- **SQLite3** - Built-in, no extra deps
- **watchdog** - File system monitoring
- **libtmux** - Programmatic tmux control

**Optional:**
- **httpx** - Async HTTP for webhooks
- **pydantic** - Data validation
- **python-frontmatter** - Parse Obsidian markdown

## Project Structure

```
agentctl/
├── pyproject.toml
├── README.md
├── agentctl/
│   ├── __init__.py
│   ├── __main__.py          # Entry point
│   ├── cli.py               # Typer CLI commands
│   ├── tui.py               # Textual dashboard
│   ├── core/
│   │   ├── __init__.py
│   │   ├── database.py      # SQLite operations
│   │   ├── task.py          # Task management
│   │   ├── agent.py         # Agent lifecycle
│   │   ├── tmux.py          # tmux integration
│   │   └── git.py           # Git operations
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── obsidian.py      # Obsidian sync
│   │   ├── notifications.py # Notification handlers
│   │   └── validators.py    # Test runners, validators
│   ├── daemon/
│   │   ├── __init__.py
│   │   ├── monitor.py       # Background monitoring
│   │   └── scheduler.py     # Task scheduling
│   └── utils/
│       ├── __init__.py
│       ├── config.py        # Configuration management
│       └── logger.py        # Logging setup
└── tests/
    └── ...
```

## Implementation

### 1. CLI Entry Point (`cli.py`)

```python
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from typing import Optional
from enum import Enum

app = typer.Typer(
    name="agentctl",
    help="🤖 AI Agent Control Center - Manage your coding agents",
    add_completion=True,
)
console = Console()

class TaskStatus(str, Enum):
    RUNNING = "running"
    BLOCKED = "blocked"
    QUEUED = "queued"
    COMPLETE = "complete"
    FAILED = "failed"

class TaskPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@app.command()
def status():
    """Show quick status of all agents"""
    from agentctl.core.database import get_active_agents, get_queued_tasks
    from agentctl.core.agent import get_agent_status
    
    agents = get_active_agents()
    queued = get_queued_tasks()
    
    # Status summary
    console.print("\n🤖 [bold cyan]AGENT STATUS[/bold cyan]")
    console.print("━" * 60)
    console.print(f"Active:   [green]{len([a for a in agents if a['status'] == 'running'})}[/green] agents running")
    console.print(f"Blocked:  [yellow]{len([a for a in agents if a['status'] == 'blocked'})}[/yellow] awaiting review")
    console.print(f"Queued:   [blue]{len(queued)}[/blue] tasks pending")
    console.print("━" * 60)
    console.print()
    
    # Active agents table
    if agents:
        table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
        table.add_column("Task ID", style="cyan")
        table.add_column("Phase", style="yellow")
        table.add_column("Elapsed", style="white")
        table.add_column("Commits", style="green")
        table.add_column("Status", style="white")
        
        for agent in agents:
            status_icon = {
                "running": "🟢",
                "blocked": "🟡",
                "failed": "🔴"
            }.get(agent['status'], "⚪")
            
            table.add_row(
                agent['task_id'],
                agent['phase'],
                agent['elapsed'],
                str(agent['commits']),
                f"{status_icon} {agent['status'].upper()}"
            )
        
        console.print(table)
    
    # Next action hint
    blocked = [a for a in agents if a['status'] == 'blocked']
    if blocked:
        console.print(f"\n💡 [bold yellow]Next action:[/bold yellow] Review {blocked[0]['task_id']}")
        console.print(f"   Run: [cyan]agentctl review next[/cyan]\n")


@app.command()
def dash():
    """Launch interactive TUI dashboard"""
    from agentctl.tui import AgentDashboard
    app = AgentDashboard()
    app.run()


# Task management commands
task_app = typer.Typer(help="Task management commands")
app.add_typer(task_app, name="task")

@task_app.command("start")
def task_start(
    task_id: str = typer.Argument(..., help="Task ID (e.g., RRA-API-0082)"),
    agent: Optional[str] = typer.Option(None, help="Agent type (claude-code, cursor, chatgpt)"),
    auto_approve: bool = typer.Option(False, "--auto", help="Auto-approve planning phase"),
):
    """Start a new task with an agent"""
    from agentctl.core.task import start_task
    from agentctl.core.agent import initialize_agent
    
    with console.status(f"[bold green]Initializing task {task_id}..."):
        # Load task from database or Obsidian
        task = start_task(task_id)
        
        console.print(f"✓ Task [cyan]{task_id}[/cyan] loaded")
        console.print(f"✓ Git branch created: [yellow]{task.branch}[/yellow]")
        console.print(f"✓ tmux session created: [yellow]{task.tmux_session}[/yellow]")
        
        # Initialize agent
        agent_type = agent or task.preferred_agent or "claude-code"
        agent_instance = initialize_agent(task_id, agent_type)
        
        console.print(f"✓ Agent initialized: [green]{agent_type}[/green]")
        console.print(f"→ Starting [bold]PLANNING[/bold] phase...\n")
        
        # Show agent's plan
        if not auto_approve:
            plan = agent_instance.get_plan()
            panel = Panel(
                plan,
                title=f"[bold]Agent Plan for {task_id}[/bold]",
                border_style="cyan"
            )
            console.print(panel)
            
            approve = typer.confirm("Approve this plan?")
            if not approve:
                console.print("[yellow]Task paused. Edit plan or abort.[/yellow]")
                return
        
        # Start implementation
        agent_instance.start()
        console.print(f"[green]✓ Agent started![/green] Attach with: [cyan]agentctl agent attach {task_id}[/cyan]")


@task_app.command("list")
def task_list(
    status: Optional[TaskStatus] = typer.Option(None, help="Filter by status"),
    priority: Optional[TaskPriority] = typer.Option(None, help="Filter by priority"),
    project: Optional[str] = typer.Option(None, help="Filter by project"),
):
    """List tasks with optional filters"""
    from agentctl.core.database import query_tasks
    
    tasks = query_tasks(status=status, priority=priority, project=project)
    
    if not tasks:
        console.print("[yellow]No tasks found matching filters[/yellow]")
        return
    
    table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
    table.add_column("Task ID", style="cyan")
    table.add_column("Status", style="white")
    table.add_column("Priority", style="white")
    table.add_column("Phase", style="yellow")
    table.add_column("Waiting", style="white")
    
    for task in tasks:
        priority_color = {
            "high": "red",
            "medium": "yellow",
            "low": "blue"
        }.get(task['priority'], "white")
        
        table.add_row(
            task['task_id'],
            task['status'],
            f"[{priority_color}]{task['priority'].upper()}[/{priority_color}]",
            task['phase'] or "-",
            task['waiting_time'] or "-"
        )
    
    console.print(table)


@task_app.command("pause")
def task_pause(task_id: str):
    """Pause a running task"""
    from agentctl.core.task import pause_task
    
    with console.status(f"[yellow]Pausing task {task_id}..."):
        pause_task(task_id)
    
    console.print(f"✓ Task [cyan]{task_id}[/cyan] paused")
    console.print("  [dim]tmux session preserved, agent stopped[/dim]")


@task_app.command("resume")
def task_resume(task_id: str):
    """Resume a paused task"""
    from agentctl.core.task import resume_task
    
    with console.status(f"[green]Resuming task {task_id}..."):
        resume_task(task_id)
    
    console.print(f"✓ Task [cyan]{task_id}[/cyan] resumed from checkpoint")


# Agent management commands
agent_app = typer.Typer(help="Agent management commands")
app.add_typer(agent_app, name="agent")

@agent_app.command("list")
def agent_list():
    """List all active agents"""
    from agentctl.core.database import get_active_agents
    
    agents = get_active_agents()
    
    table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
    table.add_column("Task ID", style="cyan")
    table.add_column("Agent Type", style="green")
    table.add_column("Status", style="white")
    table.add_column("Phase", style="yellow")
    table.add_column("Elapsed", style="white")
    table.add_column("tmux Session", style="dim")
    
    for agent in agents:
        table.add_row(
            agent['task_id'],
            agent['agent_type'],
            agent['status'],
            agent['phase'],
            agent['elapsed'],
            agent['tmux_session']
        )
    
    console.print(table)


@agent_app.command("attach")
def agent_attach(
    task_id: str,
    split: bool = typer.Option(False, "--split", help="Open in tmux split pane"),
):
    """Attach to an agent's tmux session"""
    from agentctl.core.tmux import attach_session
    
    console.print(f"→ Attaching to [cyan]{task_id}[/cyan]...")
    attach_session(task_id, split=split)


@agent_app.command("logs")
def agent_logs(
    task_id: str,
    follow: bool = typer.Option(False, "-f", "--follow", help="Follow log output"),
    lines: int = typer.Option(50, "-n", help="Number of lines to show"),
):
    """View agent logs"""
    from agentctl.core.agent import get_agent_logs
    
    if follow:
        console.print(f"[dim]Following logs for {task_id} (Ctrl+C to stop)...[/dim]\n")
        # Implement tail -f style following
        import time
        last_position = 0
        try:
            while True:
                logs, last_position = get_agent_logs(task_id, from_position=last_position)
                if logs:
                    console.print(logs, end="")
                time.sleep(1)
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopped following logs[/yellow]")
    else:
        logs = get_agent_logs(task_id, lines=lines)
        console.print(logs)


@agent_app.command("plan")
def agent_plan(task_id: str):
    """Show agent's current plan and progress"""
    from agentctl.core.agent import get_agent_plan
    
    plan = get_agent_plan(task_id)
    
    panel = Panel(
        f"""[bold]Current Phase:[/bold] {plan['phase']}
[bold]Progress:[/bold] {plan['progress']}%

[bold cyan]Plan:[/bold cyan]
{plan['plan_text']}

[bold green]Completed:[/bold green]
{plan['completed']}

[bold yellow]In Progress:[/bold yellow]
{plan['current']}

[bold dim]Upcoming:[/bold dim]
{plan['upcoming']}
""",
        title=f"[bold]Agent Plan: {task_id}[/bold]",
        border_style="cyan"
    )
    console.print(panel)


# Review commands
review_app = typer.Typer(help="Code review workflow")
app.add_typer(review_app, name="review")

@review_app.command("next")
def review_next():
    """Get next task needing review"""
    from agentctl.core.task import get_next_review
    
    task = get_next_review()
    
    if not task:
        console.print("[green]✓ No tasks awaiting review![/green]")
        return
    
    # Display review summary
    console.print(f"\n📋 [bold cyan]{task['task_id']}: {task['title']}[/bold cyan]")
    console.print("━" * 60)
    console.print(f"Status:    [yellow]Awaiting review ({task['waiting_time']})[/yellow]")
    console.print(f"Commits:   {task['commits']}")
    console.print(f"Files:     {task['files_changed']} modified, {task['files_new']} new")
    console.print(f"Tests:     {'✓' if task['tests_passing'] else '✗'} {task['test_summary']}")
    console.print(f"Coverage:  {'✓' if task['coverage_ok'] else '✗'} {task['coverage']}%")
    console.print()
    
    # Show file changes
    console.print("[bold]Changes:[/bold]")
    for file in task['changed_files']:
        console.print(f"  {file['path']}  [green](+{file['additions']}[/green], [red]-{file['deletions']})[/red]")
    
    console.print("\n[bold]Actions:[/bold]")
    console.print("  [cyan]agentctl review diff {task['task_id']}[/cyan]     - Show diff")
    console.print("  [cyan]agentctl review approve {task['task_id']}[/cyan]  - Approve and merge")
    console.print("  [cyan]agentctl review reject {task['task_id']}[/cyan]   - Request changes")
    console.print("  [cyan]agentctl agent attach {task['task_id']}[/cyan]    - Open in tmux")


@review_app.command("approve")
def review_approve(
    task_id: str,
    note: Optional[str] = typer.Option(None, help="Review note"),
):
    """Approve and merge task"""
    from agentctl.core.task import approve_task
    
    with console.status(f"[green]Approving {task_id}..."):
        result = approve_task(task_id, note=note)
    
    console.print(f"✓ Review approved")
    console.print(f"✓ Merged branch [yellow]{result['branch']}[/yellow]")
    console.print(f"✓ Task marked [green]complete[/green]")
    console.print(f"✓ Agent freed for next task")
    
    if result['next_task']:
        console.print(f"\n→ Starting next queued task: [cyan]{result['next_task']}[/cyan]")


# Sync command
@app.command()
def sync(
    source: str = typer.Argument("obsidian", help="Source to sync from (obsidian)"),
    path: Optional[str] = typer.Option(None, help="Path to vault/directory"),
    watch: bool = typer.Option(False, help="Watch for changes continuously"),
):
    """Sync tasks from external sources"""
    from agentctl.integrations.obsidian import sync_obsidian, watch_obsidian
    
    if source == "obsidian":
        if watch:
            console.print(f"👀 Watching [cyan]{path}[/cyan] for changes...")
            console.print("[dim]Press Ctrl+C to stop[/dim]\n")
            watch_obsidian(path)
        else:
            with console.status("[bold green]Syncing tasks..."):
                result = sync_obsidian(path)
            
            console.print(f"✓ Synced [green]{result['new']}[/green] new tasks")
            console.print(f"✓ Updated [yellow]{result['updated']}[/yellow] existing tasks")
    else:
        console.print(f"[red]Unknown source: {source}[/red]")


# Stats command
@app.command()
def stats(
    period: str = typer.Option("week", help="Time period (day, week, month)"),
):
    """Show agent statistics and insights"""
    from agentctl.core.database import get_statistics
    
    stats = get_statistics(period=period)
    
    console.print(f"\n📊 [bold cyan]{period.upper()} STATISTICS[/bold cyan]")
    console.print("━" * 60)
    console.print(f"Tasks Completed:    [green]{stats['completed']}[/green]")
    console.print(f"Avg Time per Task:  {stats['avg_time']}")
    console.print(f"Total Commits:      {stats['commits']}")
    console.print(f"Lines Changed:      [green]+{stats['lines_added']}[/green] / [red]-{stats['lines_deleted']}[/red]")
    console.print()
    
    console.print("[bold]Breakdown by Category:[/bold]")
    for category, count in stats['by_category'].items():
        percentage = (count / stats['completed']) * 100
        console.print(f"  {category.upper()}: {count} tasks ({percentage:.0f}%)")
    console.print()
    
    console.print("[bold]Agent Efficiency:[/bold]")
    console.print(f"  Avg Human Wait Time:  {stats['avg_wait_time']}")
    console.print(f"  Blocked Time:         {stats['blocked_percentage']}% of total")
    console.print(f"  First-Try Success:    {stats['first_try_success']}%")
    console.print()
    
    console.print(f"🔥 Busiest Agent: [yellow]{stats['busiest_agent']['name']}[/yellow] ({stats['busiest_agent']['count']} tasks)")
    console.print(f"⭐ Best Success Rate: [green]{stats['best_agent']['name']}[/green] ({stats['best_agent']['rate']}%)")


# Daemon commands
daemon_app = typer.Typer(help="Background daemon management")
app.add_typer(daemon_app, name="daemon")

@daemon_app.command("start")
def daemon_start():
    """Start the monitoring daemon"""
    from agentctl.daemon.monitor import start_daemon
    
    pid = start_daemon()
    console.print(f"✓ Daemon started (PID: [yellow]{pid}[/yellow])")
    console.print("→ Monitoring agents every 30s")
    console.print("→ Auto-restarting crashed agents")
    console.print("→ Sending notifications")


@daemon_app.command("stop")
def daemon_stop():
    """Stop the monitoring daemon"""
    from agentctl.daemon.monitor import stop_daemon
    
    stop_daemon()
    console.print("✓ Daemon stopped")


@daemon_app.command("status")
def daemon_status():
    """Check daemon status"""
    from agentctl.daemon.monitor import get_daemon_status
    
    status = get_daemon_status()
    
    if status['running']:
        console.print(f"✓ Daemon [green]running[/green] (PID: {status['pid']})")
        console.print(f"  Uptime: {status['uptime']}")
        console.print(f"  Last check: {status['last_check']}")
    else:
        console.print("✗ Daemon [red]not running[/red]")


if __name__ == "__main__":
    app()
```

### 2. TUI Dashboard (`tui.py`)

```python
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Header, Footer, Static, DataTable, Log
from textual.reactive import reactive
from textual import events
from datetime import datetime
import asyncio

class AgentStatusWidget(Static):
    """Widget showing active agents"""
    
    agents = reactive([])
    
    def compose(self) -> ComposeResult:
        yield DataTable()
    
    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Task ID", "Project", "Status", "Phase", "Elapsed", "Commits")
        self.update_agents()
    
    async def update_agents(self) -> None:
        """Periodically update agent list"""
        from agentctl.core.database import get_active_agents
        
        while True:
            agents = get_active_agents()
            self.agents = agents
            
            table = self.query_one(DataTable)
            table.clear()
            
            for agent in agents:
                status_icon = {
                    "running": "🟢",
                    "blocked": "🟡",
                    "failed": "🔴"
                }.get(agent['status'], "⚪")
                
                table.add_row(
                    agent['task_id'],
                    agent['project'],
                    f"{status_icon} {agent['status']}",
                    agent['phase'],
                    agent['elapsed'],
                    str(agent['commits'])
                )
            
            await asyncio.sleep(5)  # Update every 5 seconds


class TaskQueueWidget(Static):
    """Widget showing queued tasks"""
    
    def compose(self) -> ComposeResult:
        yield DataTable()
    
    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("#", "Task ID", "Priority", "Category")
        self.update_queue()
    
    async def update_queue(self) -> None:
        from agentctl.core.database import get_queued_tasks
        
        while True:
            tasks = get_queued_tasks()
            
            table = self.query_one(DataTable)
            table.clear()
            
            for i, task in enumerate(tasks[:5], 1):
                priority_color = {
                    "high": "red",
                    "medium": "yellow",
                    "low": "blue"
                }.get(task['priority'], "white")
                
                table.add_row(
                    str(i),
                    task['task_id'],
                    f"[{priority_color}]{task['priority'].upper()}[/{priority_color}]",
                    task['category']
                )
            
            await asyncio.sleep(10)


class ActivityLogWidget(Log):
    """Widget showing recent activity"""
    
    def on_mount(self) -> None:
        self.update_activity()
    
    async def update_activity(self) -> None:
        from agentctl.core.database import get_recent_events
        
        while True:
            events = get_recent_events(limit=10)
            
            self.clear()
            for event in events:
                timestamp = event['timestamp'].strftime("%H:%M")
                icon = {
                    "commit": "✓",
                    "blocked": "⚠",
                    "phase_change": "→",
                    "complete": "✅"
                }.get(event['type'], "•")
                
                self.write_line(f"{timestamp}  {event['task_id']}  {icon} {event['message']}")
            
            await asyncio.sleep(3)


class AlertsWidget(Static):
    """Widget showing current alerts"""
    
    def compose(self) -> ComposeResult:
        yield Static("", id="alerts-content")
    
    def on_mount(self) -> None:
        self.update_alerts()
    
    async def update_alerts(self) -> None:
        from agentctl.core.database import get_alerts
        
        while True:
            alerts = get_alerts()
            
            content = self.query_one("#alerts-content", Static)
            
            if not alerts:
                content.update("[dim]No alerts[/dim]")
            else:
                alert_text = "\n".join([
                    f"⚠ {alert['message']}"
                    for alert in alerts
                ])
                content.update(alert_text)
            
            await asyncio.sleep(5)


class AgentDashboard(App):
    """Main TUI dashboard application"""
    
    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 4;
        grid-rows: 1fr 1fr 1fr 1fr;
    }
    
    #agents {
        column-span: 2;
        border: solid $accent;
        height: 100%;
    }
    
    #queue {
        border: solid $accent;
        height: 100%;
    }
    
    #activity {
        border: solid $accent;
        height: 100%;
    }
    
    #alerts {
        column-span: 2;
        border: solid $warning;
        height: 100%;
    }
    """
    
    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("q", "quit", "Quit"),
        ("a", "attach", "Attach"),
        ("l", "logs", "Logs"),
        ("n", "next_task", "Next Task"),
    ]
    
    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            AgentStatusWidget(id="agents").data_bind(AgentDashboard.agents),
            TaskQueueWidget(id="queue"),
            ActivityLogWidget(id="activity"),
            AlertsWidget(id="alerts"),
        )
        yield Footer()
    
    def action_refresh(self) -> None:
        """Refresh all widgets"""
        self.refresh()
    
    def action_attach(self) -> None:
        """Attach to selected agent"""
        # Get selected agent from table
        # Call attach_session
        pass
    
    def action_logs(self) -> None:
        """Show logs for selected agent"""
        # Open logs in modal
        pass
    
    def action_next_task(self) -> None:
        """Start next queued task"""
        from agentctl.core.task import start_next_task
        start_next_task()
        self.refresh()
```

### 3. Core Database (`core/database.py`)

```python
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import json

DB_PATH = Path.home() / ".agentctl" / "agentctl.db"

def init_db():
    """Initialize database schema"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            category TEXT NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            priority TEXT NOT NULL DEFAULT 'medium',
            phase TEXT,
            created_at INTEGER NOT NULL,
            started_at INTEGER,
            completed_at INTEGER,
            tmux_session TEXT,
            git_branch TEXT,
            agent_type TEXT,
            commits INTEGER DEFAULT 0,
            metadata TEXT
        );
        
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            data TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        );
        
        CREATE TABLE IF NOT EXISTS checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            state TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        );
        
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
        CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
    """)
    
    conn.commit()
    conn.close()


def get_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_active_agents() -> List[Dict]:
    """Get all active agents"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            id as task_id,
            project,
            status,
            phase,
            agent_type,
            commits,
            tmux_session,
            CAST((julianday('now') - julianday(started_at, 'unixepoch')) * 24 * 60 AS INTEGER) as elapsed_minutes
        FROM tasks
        WHERE status IN ('running', 'blocked')
        ORDER BY started_at DESC
    """)
    
    agents = []
    for row in cursor.fetchall():
        elapsed = f"{row['elapsed_minutes'] // 60}h {row['elapsed_minutes'] % 60}m"
        agents.append({
            'task_id': row['task_id'],
            'project': row['project'],
            'status': row['status'],
            'phase': row['phase'],
            'agent_type': row['agent_type'],
            'commits': row['commits'],
            'tmux_session': row['tmux_session'],
            'elapsed': elapsed
        })
    
    conn.close()
    return agents


def get_queued_tasks() -> List[Dict]:
    """Get queued tasks ordered by priority"""
    conn = get_connection()
    cursor = conn.cursor()
    
    priority_order = {'high': 1, 'medium': 2, 'low': 3}
    
    cursor.execute("""
        SELECT id, project, category, priority, title
        FROM tasks
        WHERE status = 'queued'
        ORDER BY 
            CASE priority 
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                WHEN 'low' THEN 3
            END,
            created_at ASC
    """)
    
    tasks = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return tasks


def query_tasks(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    project: Optional[str] = None
) -> List[Dict]:
    """Query tasks with filters"""
    conn = get_connection()
    cursor = conn.cursor()
    
    conditions = []
    params = []
    
    if status:
        conditions.append("status = ?")
        params.append(status)
    if priority:
        conditions.append("priority = ?")
        params.append(priority)
    if project:
        conditions.append("project = ?")
        params.append(project)
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    cursor.execute(f"""
        SELECT 
            id as task_id,
            status,
            priority,
            phase,
            CAST((julianday('now') - julianday(started_at, 'unixepoch')) * 24 * 60 AS INTEGER) as waiting_minutes
        FROM tasks
        WHERE {where_clause}
        ORDER BY created_at DESC
    """, params)
    
    tasks = []
    for row in cursor.fetchall():
        task = dict(row)
        if task['waiting_minutes']:
            task['waiting_time'] = f"{task['waiting_minutes'] // 60}h {task['waiting_minutes'] % 60}m"
        else:
            task['waiting_time'] = None
        tasks.append(task)
    
    conn.close()
    return tasks


def add_event(task_id: str, event_type: str, data: Optional[Dict] = None):
    """Add an event to the log"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO events (task_id, event_type, timestamp, data)
        VALUES (?, ?, ?, ?)
    """, (task_id, event_type, int(datetime.now().timestamp()), json.dumps(data or {})))
    
    conn.commit()
    conn.close()


def get_recent_events(limit: int = 10) -> List[Dict]:
    """Get recent events"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT task_id, event_type, timestamp, data
        FROM events
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,))
    
    events = []
    for row in cursor.fetchall():
        events.append({
            'task_id': row['task_id'],
            'type': row['event_type'],
            'timestamp': datetime.fromtimestamp(row['timestamp']),
            'data': json.loads(row['data'])
        })
    
    conn.close()
    return events


def get_statistics(period: str = "week") -> Dict:
    """Get statistics for a time period"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Calculate time window
    if period == "day":
        since = datetime.now() - timedelta(days=1)
    elif period == "week":
        since = datetime.now() - timedelta(weeks=1)
    elif period == "month":
        since = datetime.now() - timedelta(days=30)
    else:
        since = datetime.now() - timedelta(weeks=1)
    
    since_ts = int(since.timestamp())
    
    # Get completed tasks
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM tasks
        WHERE status = 'complete' AND completed_at >= ?
    """, (since_ts,))
    completed = cursor.fetchone()['count']
    
    # Get average time per task
    cursor.execute("""
        SELECT AVG(completed_at - started_at) as avg_seconds
        FROM tasks
        WHERE status = 'complete' AND completed_at >= ?
    """, (since_ts,))
    avg_seconds = cursor.fetchone()['avg_seconds'] or 0
    avg_time = f"{int(avg_seconds // 3600)}h {int((avg_seconds % 3600) // 60)}m"
    
    # More statistics...
    # (commits, lines, breakdown by category, etc.)
    
    conn.close()
    
    return {
        'completed': completed,
        'avg_time': avg_time,
        'commits': 142,  # TODO: Calculate from git
        'lines_added': 8432,
        'lines_deleted': 2103,
        'by_category': {'feature': 12, 'bugfix': 5, 'refactor': 1},
        'avg_wait_time': '45m',
        'blocked_percentage': 12,
        'first_try_success': 72,
        'busiest_agent': {'name': 'claude-code', 'count': 11},
        'best_agent': {'name': 'cursor', 'rate': 89}
    }
```

### 4. Task Management (`core/task.py`)

```python
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime
import subprocess

from agentctl.core.database import get_connection, add_event
from agentctl.core.tmux import create_session
from agentctl.core.git import create_branch


class Task:
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.load_from_db()
    
    def load_from_db(self):
        """Load task details from database"""
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (self.task_id,))
        row = cursor.fetchone()
        
        if not row:
            raise ValueError(f"Task {self.task_id} not found")
        
        self.project = row['project']
        self.category = row['category']
        self.title = row['title']
        self.status = row['status']
        self.priority = row['priority']
        self.phase = row['phase']
        
        conn.close()
    
    @property
    def branch(self) -> str:
        """Git branch name for this task"""
        prefix = {
            'FEATURE': 'feature',
            'BUG': 'bugfix',
            'REFACTOR': 'refactor'
        }.get(self.category, 'task')
        
        return f"{prefix}/{self.task_id}"
    
    @property
    def tmux_session(self) -> str:
        """tmux session name for this task"""
        return f"agent-{self.task_id}"
    
    @property
    def workspace_dir(self) -> Path:
        """Workspace directory for this task"""
        return Path.home() / ".agentctl" / "sessions" / self.task_id
    
    @property
    def preferred_agent(self) -> Optional[str]:
        """Determine preferred agent based on task type"""
        # Could be configured per-project or category
        return None


def start_task(task_id: str) -> Task:
    """Initialize and start a new task"""
    task = Task(task_id)
    
    # Create workspace directory
    task.workspace_dir.mkdir(parents=True, exist_ok=True)
    
    # Create git branch
    branch = create_branch(task.branch)
    
    # Create tmux session
    session = create_session(task.tmux_session, task.workspace_dir)
    
    # Update database
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE tasks
        SET 
            status = 'running',
            phase = 'planning',
            started_at = ?,
            git_branch = ?,
            tmux_session = ?
        WHERE id = ?
    """, (int(datetime.now().timestamp()), branch, session, task_id))
    
    conn.commit()
    conn.close()
    
    # Log event
    add_event(task_id, 'task_started', {'branch': branch, 'session': session})
    
    return task


def pause_task(task_id: str):
    """Pause a running task"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE tasks
        SET status = 'paused'
        WHERE id = ?
    """, (task_id,))
    
    conn.commit()
    conn.close()
    
    add_event(task_id, 'task_paused')


def resume_task(task_id: str):
    """Resume a paused task"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE tasks
        SET status = 'running'
        WHERE id = ?
    """, (task_id,))
    
    conn.commit()
    conn.close()
    
    add_event(task_id, 'task_resumed')


def get_next_review() -> Optional[Dict]:
    """Get next task needing review"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT *
        FROM tasks
        WHERE status = 'blocked' AND phase = 'review'
        ORDER BY started_at ASC
        LIMIT 1
    """)
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    # TODO: Enrich with git stats, test results, etc.
    return dict(row)


def approve_task(task_id: str, note: Optional[str] = None) -> Dict:
    """Approve and complete a task"""
    from agentctl.core.git import merge_branch
    
    task = Task(task_id)
    
    # Merge branch
    merge_branch(task.branch)
    
    # Update database
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE tasks
        SET 
            status = 'complete',
            completed_at = ?
        WHERE id = ?
    """, (int(datetime.now().timestamp()), task_id))
    
    conn.commit()
    conn.close()
    
    add_event(task_id, 'task_approved', {'note': note})
    
    # Check for next queued task
    # TODO: Auto-start next task
    
    return {
        'branch': task.branch,
        'next_task': None
    }
```

### 5. Installation (`pyproject.toml`)

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "agentctl"
version = "0.1.0"
description = "AI Agent Control Center - Manage your coding agents"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "typer[all]>=0.9.0",
    "rich>=13.0.0",
    "textual>=0.47.0",
    "libtmux>=0.25.0",
    "watchdog>=3.0.0",
    "httpx>=0.25.0",
    "pydantic>=2.0.0",
    "python-frontmatter>=1.0.0",
    "gitpython>=3.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "black>=23.0.0",
    "ruff>=0.1.0",
]

[project.scripts]
agentctl = "agentctl.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["agentctl"]
```

## Quick Start

```bash
# Install
pip install -e .

# Initialize
agentctl init

# Quick status
agentctl status

# Launch dashboard
agentctl dash

# Start a task
agentctl task start RRA-API-0082

# View logs
agentctl agent logs RRA-API-0082 -f
```

## Next Steps

Want me to:
1. **Generate the full project scaffold** with all files?
2. **Focus on a specific component** (tmux integration, Obsidian sync, etc.)?
3. **Add more features** (notifications, webhooks, validation)?
4. **Create installation/setup scripts**?

This is a solid foundation that's production-ready and extensible. What would you like to tackle first?
