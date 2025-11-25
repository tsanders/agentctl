"""CLI entry point for agentctl"""

import typer
from rich.console import Console
from rich.table import Table
from rich import box
from typing import Optional
from enum import Enum

from agentctl.core import database
from agentctl.core.task import start_task
from agentctl.core.agent_monitor import (
    get_all_agent_statuses,
    get_agent_status,
    get_health_display,
    HEALTH_ICONS,
)

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
def dash():
    """Launch interactive TUI dashboard"""
    from agentctl.tui import run_dashboard
    run_dashboard()


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


@app.command()
def agents(
    watch: bool = typer.Option(False, "--watch", "-w", help="Live updating view (refresh every 2s)"),
):
    """Show status of all Claude agents in tmux sessions"""
    import time as time_module

    def show_agents():
        agent_statuses = get_all_agent_statuses()

        if not agent_statuses:
            console.print("\n🤖 [bold cyan]ACTIVE AGENTS[/bold cyan] (0)")
            console.print("[dim]No agents with tmux sessions found[/dim]")
            console.print("\nStart a task with: [cyan]agentctl task start <task-id>[/cyan]")
            return False  # No agents needing attention

        # Check if any need attention
        needs_attention = any(
            s["health"] in ("error", "waiting")
            for s in agent_statuses
        )

        console.print(f"\n🤖 [bold cyan]ACTIVE AGENTS[/bold cyan] ({len(agent_statuses)})")
        console.print()

        table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
        table.add_column("Task", style="cyan", max_width=25)
        table.add_column("Health", style="white", width=12)
        table.add_column("Status", style="white", width=10)
        table.add_column("Recent Output", style="dim", max_width=45)

        for agent in agent_statuses:
            # Format health display
            health_display = get_health_display(agent["health"])

            # Truncate output preview
            output = agent.get("last_output_preview", "") or "-"
            if len(output) > 42:
                output = output[:39] + "..."

            # Color code health
            health_color = {
                "active": "green",
                "idle": "yellow",
                "waiting": "rgb(255,165,0)",  # orange
                "exited": "red",
                "error": "red",
            }.get(agent["health"], "white")

            table.add_row(
                agent["task_id"],
                f"[{health_color}]{health_display}[/{health_color}]",
                agent.get("task_status", "-"),
                output,
            )

        console.print(table)

        # Show warnings if any
        warnings = [
            (a["task_id"], a["warnings"])
            for a in agent_statuses
            if a.get("warnings")
        ]
        if warnings:
            console.print("\n[yellow]Warnings:[/yellow]")
            for task_id, warns in warnings:
                for w in warns:
                    console.print(f"  • {task_id}: {w}")

        console.print("\nAttach: [cyan]agentctl attach <task-id>[/cyan]")

        return needs_attention

    if watch:
        try:
            while True:
                console.clear()
                show_agents()
                console.print("\n[dim]Press Ctrl+C to exit[/dim]")
                time_module.sleep(2)
        except KeyboardInterrupt:
            console.print("\n[dim]Stopped watching[/dim]")
    else:
        needs_attention = show_agents()
        # Exit code 1 if any agent needs attention
        if needs_attention:
            raise typer.Exit(1)


@app.command()
def attach(
    task_id: str = typer.Argument(..., help="Task ID to attach to"),
):
    """Attach to a task's tmux session"""
    import subprocess

    # Get task to find tmux session
    task = database.get_task(task_id)
    if not task:
        console.print(f"[red]Error:[/red] Task '{task_id}' not found")
        raise typer.Exit(1)

    tmux_session = task.get("tmux_session")
    if not tmux_session:
        console.print(f"[red]Error:[/red] Task '{task_id}' has no tmux session")
        console.print("Start the task first with: [cyan]agentctl task start {task_id}[/cyan]")
        raise typer.Exit(1)

    # Check if session exists
    from agentctl.core.tmux import session_exists
    if not session_exists(tmux_session):
        console.print(f"[red]Error:[/red] tmux session '{tmux_session}' not found")
        console.print("The session may have been closed.")
        raise typer.Exit(1)

    console.print(f"Attaching to [cyan]{tmux_session}[/cyan]...")
    console.print("[dim]Press Ctrl+B, D to detach[/dim]\n")

    # Execute tmux attach
    subprocess.run(["tmux", "attach", "-t", tmux_session])


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
    task_id: Optional[str] = typer.Argument(None, help="Task ID (auto-generated for markdown tasks)"),
    title: str = typer.Option(..., help="Task title"),
    project_id: str = typer.Option(..., help="Project ID"),
    category: str = typer.Option("FEATURE", help="Category (FEATURE, BUG, REFACTOR)"),
    task_type: str = typer.Option("feature", help="Task type"),
    priority: TaskPriority = typer.Option(TaskPriority.MEDIUM, help="Priority level"),
    description: Optional[str] = typer.Option(None, help="Task description"),
    repository_id: Optional[str] = typer.Option(None, help="Repository ID (optional)"),
):
    """Create a new task"""
    from agentctl.core.task import create_markdown_task

    # Verify project exists
    project = database.get_project(project_id)
    if not project:
        console.print(f"[red]Error:[/red] Project '{project_id}' not found")
        console.print(f"Create it first with: [cyan]agentctl project create {project_id}[/cyan]")
        raise typer.Exit(1)

    # Verify repository if provided
    if repository_id:
        repo = database.get_repository(repository_id)
        if not repo:
            console.print(f"[red]Error:[/red] Repository '{repository_id}' not found")
            raise typer.Exit(1)

    # Check if project uses markdown tasks
    if project.get('tasks_path'):
        # Create markdown task (ID will be auto-generated)
        actual_task_id = create_markdown_task(
            project_id=project_id,
            category=category,
            title=title,
            description=description,
            repository_id=repository_id,
            task_type=task_type,
            priority=priority.value
        )
        if not actual_task_id:
            console.print("[red]Error:[/red] Failed to create markdown task")
            raise typer.Exit(1)

        console.print(f"✓ Markdown task [cyan]{actual_task_id}[/cyan] created")
        console.print(f"  Title: {title}")
        console.print(f"  Project: {project['name']}")
        console.print(f"  File: {project['tasks_path']}/{actual_task_id}.md")
    else:
        # Create database task (user must provide ID)
        if not task_id:
            console.print("[red]Error:[/red] Task ID is required for database tasks")
            console.print("Either provide a task ID or configure tasks_path for the project")
            raise typer.Exit(1)

        database.create_task(
            task_id=task_id,
            project_id=project_id,
            category=category,
            task_type=task_type,
            title=title,
            description=description,
            priority=priority.value,
            repository_id=repository_id
        )

        console.print(f"✓ Task [cyan]{task_id}[/cyan] created")
        console.print(f"  Title: {title}")
        console.print(f"  Project: {project['name']}")

    if repository_id:
        console.print(f"  Repository: {repository_id}")
    console.print(f"  Priority: [{priority.value}]{priority.value.upper()}[/{priority.value}]")


@task_app.command("validate")
def task_validate(
    project_id: Optional[str] = typer.Argument(None, help="Project ID (optional, validates all if not specified)"),
):
    """Validate markdown task files"""
    from agentctl.core import task_sync

    if project_id:
        # Validate specific project
        result = task_sync.sync_project_tasks(project_id)

        console.print(f"\n📋 [bold]Validation Results for {project_id}[/bold]")
        console.print(f"  ✓ Valid tasks: [green]{result.synced_count}[/green]")
        console.print(f"  ✗ Invalid tasks: [red]{result.error_count}[/red]")

        if result.errors:
            console.print("\n[red]Errors:[/red]")
            for error in result.errors:
                console.print(f"  • {error}")

        raise typer.Exit(0 if result.error_count == 0 else 1)
    else:
        # Validate all projects
        results = task_sync.sync_all_tasks()

        total_valid = sum(r.synced_count for r in results.values())
        total_invalid = sum(r.error_count for r in results.values())

        console.print(f"\n📋 [bold]Validation Results (All Projects)[/bold]")
        console.print(f"  Projects scanned: {len(results)}")
        console.print(f"  ✓ Valid tasks: [green]{total_valid}[/green]")
        console.print(f"  ✗ Invalid tasks: [red]{total_invalid}[/red]")

        for project_id, result in results.items():
            if result.error_count > 0:
                console.print(f"\n[yellow]{project_id}:[/yellow]")
                for error in result.errors[:3]:  # Show first 3 errors per project
                    console.print(f"  • {error}")
                if len(result.errors) > 3:
                    console.print(f"  ... and {len(result.errors) - 3} more errors")

        raise typer.Exit(0 if total_invalid == 0 else 1)


@task_app.command("sync")
def task_sync_cmd(
    project_id: Optional[str] = typer.Argument(None, help="Project ID (optional, syncs all if not specified)"),
):
    """Manually sync markdown task files to database"""
    from agentctl.core import task_sync

    if project_id:
        # Sync specific project
        with console.status(f"[bold green]Syncing tasks for {project_id}..."):
            result = task_sync.sync_project_tasks(project_id)

        console.print(f"✓ Synced {result.synced_count} tasks for {project_id}")
        if result.error_count > 0:
            console.print(f"⚠️  {result.error_count} errors encountered")
            console.print("Run [cyan]agentctl task validate {project_id}[/cyan] for details")
    else:
        # Sync all projects
        with console.status("[bold green]Syncing all projects..."):
            results = task_sync.sync_all_tasks()

        total_synced = sum(r.synced_count for r in results.values())
        total_errors = sum(r.error_count for r in results.values())

        console.print(f"✓ Synced {total_synced} tasks across {len(results)} projects")
        if total_errors > 0:
            console.print(f"⚠️  {total_errors} errors encountered")
            console.print("Run [cyan]agentctl task validate[/cyan] for details")


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


# Project management commands
project_app = typer.Typer(help="Project management commands")
app.add_typer(project_app, name="project")


@project_app.command("create")
def project_create(
    project_id: str = typer.Argument(..., help="Project ID (e.g., RRA)"),
    name: str = typer.Option(..., help="Project name"),
    description: Optional[str] = typer.Option(None, help="Project description"),
    tasks_path: Optional[str] = typer.Option(None, help="Path to markdown task files"),
):
    """Create a new project"""
    from pathlib import Path

    # Validate tasks_path if provided
    if tasks_path:
        path = Path(tasks_path).expanduser().resolve()
        if not path.exists():
            console.print(f"[yellow]Warning:[/yellow] Path does not exist: {path}")
            create = typer.confirm("Create directory?", default=True)
            if create:
                path.mkdir(parents=True, exist_ok=True)
                console.print(f"✓ Created directory: {path}")
            else:
                tasks_path = None

        tasks_path = str(path) if tasks_path else None

    database.create_project(
        project_id=project_id,
        name=name,
        description=description,
        tasks_path=tasks_path
    )

    console.print(f"✓ Project [cyan]{project_id}[/cyan] created")
    console.print(f"  Name: {name}")
    if description:
        console.print(f"  Description: {description}")
    if tasks_path:
        console.print(f"  Tasks Path: {tasks_path}")


@project_app.command("list")
def project_list():
    """List all projects"""
    projects = database.list_projects()

    if not projects:
        console.print("[yellow]No projects found[/yellow]")
        console.print("Create one with: [cyan]agentctl project create PROJECT_ID --name 'Name'[/cyan]")
        return

    table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
    table.add_column("Project ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Description", style="dim")

    for project in projects:
        table.add_row(
            project['id'],
            project['name'],
            project.get('description') or "-"
        )

    console.print(table)


# Repository management commands
repo_app = typer.Typer(help="Repository management commands")
app.add_typer(repo_app, name="repo")


@repo_app.command("create")
def repo_create(
    repository_id: str = typer.Argument(..., help="Repository ID (e.g., RRA-API)"),
    project_id: str = typer.Option(..., help="Project ID"),
    name: str = typer.Option(..., help="Repository name"),
    path: str = typer.Option(..., help="Path to repository"),
    default_branch: str = typer.Option("main", help="Default branch name"),
):
    """Create a new repository"""
    from pathlib import Path

    # Verify project exists
    project = database.get_project(project_id)
    if not project:
        console.print(f"[red]Error:[/red] Project '{project_id}' not found")
        raise typer.Exit(1)

    # Verify path exists
    repo_path = Path(path).resolve()
    if not repo_path.exists():
        console.print(f"[red]Error:[/red] Path does not exist: {repo_path}")
        raise typer.Exit(1)

    database.create_repository(
        repository_id=repository_id,
        project_id=project_id,
        name=name,
        path=str(repo_path),
        default_branch=default_branch
    )

    console.print(f"✓ Repository [cyan]{repository_id}[/cyan] created")
    console.print(f"  Name: {name}")
    console.print(f"  Project: {project['name']}")
    console.print(f"  Path: {repo_path}")
    console.print(f"  Default branch: {default_branch}")


@repo_app.command("list")
def repo_list(
    project_id: Optional[str] = typer.Option(None, help="Filter by project ID"),
):
    """List repositories"""
    repositories = database.list_repositories(project_id=project_id)

    if not repositories:
        console.print("[yellow]No repositories found[/yellow]")
        console.print("Create one with: [cyan]agentctl repo create REPO_ID --project-id PROJECT_ID --name 'Name' --path /path/to/repo[/cyan]")
        return

    table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
    table.add_column("Repository ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Project", style="yellow")
    table.add_column("Path", style="dim")

    for repo in repositories:
        # Get project name
        project = database.get_project(repo['project_id'])
        project_name = project['name'] if project else repo['project_id']

        table.add_row(
            repo['id'],
            repo['name'],
            project_name,
            repo['path']
        )

    console.print(table)


def main():
    """Main entry point"""
    app()


if __name__ == "__main__":
    main()
