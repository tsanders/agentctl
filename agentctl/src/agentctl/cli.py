"""CLI entry point for agentctl"""

import typer
from rich.console import Console
from rich.table import Table
from rich import box
from typing import Optional
from enum import Enum

from agentctl.core import database
from agentctl.core.task import start_task

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
def init():
    """Initialize agentctl database"""
    database.init_db()
    console.print("✓ Database initialized at [cyan]~/.agentctl/agentctl.db[/cyan]")


@app.command()
def status():
    """Show quick status of all agents"""
    agents = database.get_active_agents()
    queued = database.get_queued_tasks()

    # Status summary
    console.print("\n🤖 [bold cyan]AGENT STATUS[/bold cyan]")
    console.print("━" * 60)
    console.print(f"Active:   [green]{len([a for a in agents if a['status'] == 'running'])}[/green] agents running")
    console.print(f"Blocked:  [yellow]{len([a for a in agents if a['status'] == 'blocked'])}[/yellow] awaiting review")
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
    else:
        console.print("[dim]No active agents[/dim]")

    # Next action hint
    blocked = [a for a in agents if a['status'] == 'blocked']
    if blocked:
        console.print(f"\n💡 [bold yellow]Next action:[/bold yellow] Review {blocked[0]['task_id']}")
        console.print(f"   Run: [cyan]agentctl review next[/cyan]\n")


# Task management commands
task_app = typer.Typer(help="Task management commands")
app.add_typer(task_app, name="task")


@task_app.command("start")
def task_start(
    task_id: str = typer.Argument(..., help="Task ID (e.g., RRA-API-0082)"),
    agent: Optional[str] = typer.Option(None, help="Agent type (claude-code, cursor, chatgpt)"),
    working_dir: Optional[str] = typer.Option(None, help="Working directory for the task"),
):
    """Start a new task with an agent"""
    from pathlib import Path

    work_dir = Path(working_dir) if working_dir else None

    try:
        with console.status(f"[bold green]Initializing task {task_id}..."):
            task = start_task(task_id, agent_type=agent, working_dir=work_dir)

        console.print(f"✓ Task [cyan]{task_id}[/cyan] started")
        console.print(f"✓ Git branch: [yellow]{task.branch}[/yellow]")
        console.print(f"✓ tmux session: [yellow]{task.tmux_session}[/yellow]")
        console.print(f"✓ Agent: [green]{agent or 'claude-code'}[/green]")
        console.print(f"\n→ Attach to agent session:")
        console.print(f"   [cyan]tmux attach -t {task.tmux_session}[/cyan]")

    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@task_app.command("list")
def task_list(
    status: Optional[TaskStatus] = typer.Option(None, help="Filter by status"),
    priority: Optional[TaskPriority] = typer.Option(None, help="Filter by priority"),
    project: Optional[str] = typer.Option(None, help="Filter by project"),
):
    """List tasks with optional filters"""
    tasks = database.query_tasks(
        status=status.value if status else None,
        priority=priority.value if priority else None,
        project=project
    )

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
        }.get(task.get('priority', 'medium'), "white")

        table.add_row(
            task['task_id'],
            task.get('status', 'unknown'),
            f"[{priority_color}]{task.get('priority', 'medium').upper()}[/{priority_color}]",
            task.get('phase') or "-",
            task.get('waiting_time') or "-"
        )

    console.print(table)


@task_app.command("create")
def task_create(
    task_id: str = typer.Argument(..., help="Task ID (e.g., RRA-API-0082)"),
    title: str = typer.Option(..., help="Task title"),
    project: str = typer.Option(..., help="Project code"),
    category: str = typer.Option("FEATURE", help="Category (FEATURE, BUG, REFACTOR)"),
    task_type: str = typer.Option("feature", help="Task type"),
    priority: TaskPriority = typer.Option(TaskPriority.MEDIUM, help="Priority level"),
    description: Optional[str] = typer.Option(None, help="Task description"),
):
    """Create a new task"""
    database.create_task(
        task_id=task_id,
        project=project,
        category=category,
        task_type=task_type,
        title=title,
        description=description,
        priority=priority.value
    )

    console.print(f"✓ Task [cyan]{task_id}[/cyan] created")
    console.print(f"  Title: {title}")
    console.print(f"  Priority: [{priority.value}]{priority.value.upper()}[/{priority.value}]")


# Agent management commands
agent_app = typer.Typer(help="Agent management commands")
app.add_typer(agent_app, name="agent")


@agent_app.command("list")
def agent_list():
    """List all active agents"""
    agents = database.get_active_agents()

    if not agents:
        console.print("[yellow]No active agents[/yellow]")
        return

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
            agent['tmux_session'] or "-"
        )

    console.print(table)


def main():
    """Main entry point"""
    app()


if __name__ == "__main__":
    main()
