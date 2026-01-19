"""
CLI entry point for Capsule.

This module provides the Typer-based command-line interface for Capsule.
All user interactions flow through these commands.

Commands:
    run         Execute a plan under policy constraints
    replay      Replay a previous run from stored results
    report      Generate a report for a completed run
    list-runs   List all recorded runs
    show-run    Show details of a specific run

Architecture Note:
    The CLI is intentionally thin - it parses arguments and delegates to the
    engine module for actual execution. This separation allows the core logic
    to be used programmatically without the CLI.
"""

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from capsule import __version__
from capsule.engine import Engine
from capsule.schema import RunStatus, ToolCallStatus, load_plan, load_policy

# Initialize Typer app with metadata
app = typer.Typer(
    name="capsule",
    help="Execute agent tool calls under strict policy controls.",
    add_completion=False,
    no_args_is_help=True,
)

# Rich console for formatted output
console = Console()


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"[bold]capsule[/bold] version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version",
            "-v",
            help="Show version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """
    Capsule - Safe execution environment for agent tool calls.

    Run agent plans under strict policy controls with full audit logging
    and deterministic replay capabilities.
    """
    pass


@app.command()
def run(
    plan_path: Annotated[
        Path,
        typer.Argument(
            help="Path to the plan YAML file.",
            exists=True,
            readable=True,
            resolve_path=True,
        ),
    ],
    policy_path: Annotated[
        Path,
        typer.Option(
            "--policy",
            "-p",
            help="Path to the policy YAML file.",
            exists=True,
            readable=True,
            resolve_path=True,
        ),
    ],
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--out",
            "-o",
            help="Path to output SQLite database. Defaults to capsule.db in current directory.",
            resolve_path=True,
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Enable verbose output for debugging.",
        ),
    ] = False,
    no_fail_fast: Annotated[
        bool,
        typer.Option(
            "--no-fail-fast",
            help="Continue execution even after errors or denials.",
        ),
    ] = False,
) -> None:
    """
    Execute a plan under policy constraints.

    Reads the plan and policy YAML files, evaluates each step against the policy,
    executes allowed tool calls, and stores all results in SQLite for audit and replay.

    Example:
        $ capsule run my_plan.yaml --policy strict.yaml --out run.db
    """
    db_path = output or Path("capsule.db")

    # Load plan and policy
    try:
        plan = load_plan(plan_path)
        if verbose:
            console.print(f"[dim]Loaded plan: {plan_path}[/dim]")
            console.print(f"[dim]  Steps: {len(plan.steps)}[/dim]")
    except Exception as e:
        console.print(f"[red]Error loading plan: {e}[/red]")
        raise typer.Exit(code=1)

    try:
        policy = load_policy(policy_path)
        if verbose:
            console.print(f"[dim]Loaded policy: {policy_path}[/dim]")
    except Exception as e:
        console.print(f"[red]Error loading policy: {e}[/red]")
        raise typer.Exit(code=1)

    # Execute the plan
    with Engine(db_path=db_path, working_dir=Path.cwd()) as engine:
        if verbose:
            console.print(f"[dim]Using database: {db_path}[/dim]")
            console.print("[dim]Executing plan...[/dim]")
            console.print()

        result = engine.run(plan, policy, fail_fast=not no_fail_fast)

        # Display results
        _display_run_result(result, verbose)

        # Exit with appropriate code
        if result.success:
            raise typer.Exit(code=0)
        else:
            raise typer.Exit(code=1)


def _display_run_result(result, verbose: bool) -> None:
    """Display run results in a formatted way."""
    # Status line with color
    if result.status == RunStatus.COMPLETED:
        status_style = "green"
        status_icon = "[green]✓[/green]"
    else:
        status_style = "red"
        status_icon = "[red]✗[/red]"

    console.print(f"{status_icon} Run [bold]{result.run_id}[/bold]: [{status_style}]{result.status.value}[/{status_style}]")
    console.print()

    # Step summary table
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=3)
    table.add_column("Tool", style="cyan")
    table.add_column("Status", width=10)
    table.add_column("Details")

    for step in result.steps:
        step_num = str(step.step_index + 1)
        tool_name = step.tool_name

        if step.status == ToolCallStatus.SUCCESS:
            status = "[green]success[/green]"
            # Show truncated output
            if step.output is not None:
                output_str = str(step.output)
                if len(output_str) > 50:
                    details = output_str[:47] + "..."
                else:
                    details = output_str
            else:
                details = ""
        elif step.status == ToolCallStatus.DENIED:
            status = "[yellow]denied[/yellow]"
            details = step.policy_decision.reason if step.policy_decision else ""
        else:  # ERROR
            status = "[red]error[/red]"
            details = step.error or ""

        # Truncate details
        if len(details) > 60:
            details = details[:57] + "..."

        table.add_row(step_num, tool_name, status, details)

    console.print(table)
    console.print()

    # Summary stats
    console.print(f"[dim]Total: {result.total_steps} | Completed: {result.completed_steps} | Denied: {result.denied_steps} | Failed: {result.failed_steps}[/dim]")
    console.print(f"[dim]Duration: {result.duration_ms:.1f}ms[/dim]")


@app.command()
def replay(
    run_id: Annotated[
        str,
        typer.Argument(help="The run ID to replay."),
    ],
    db: Annotated[
        Optional[Path],
        typer.Option(
            "--db",
            help="Path to the SQLite database containing the run.",
            exists=True,
            readable=True,
            resolve_path=True,
        ),
    ] = None,
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--out",
            "-o",
            help="Path to output SQLite database for replay results.",
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """
    Replay a previous run using stored results.

    Replays execute the same plan but return stored results instead of
    executing tools. This enables deterministic reproduction of past runs.

    Example:
        $ capsule replay abc123 --db runs.db
    """
    # TODO: Implement in Phase 3, Step 3.1 (Replay Engine)
    console.print(f"[yellow]replay command not yet implemented[/yellow]")
    console.print(f"  Run ID: {run_id}")
    console.print(f"  Database: {db or 'capsule.db'}")
    console.print(f"  Output: {output or 'replay.db'}")


@app.command()
def report(
    run_id: Annotated[
        str,
        typer.Argument(help="The run ID to generate a report for."),
    ],
    db: Annotated[
        Optional[Path],
        typer.Option(
            "--db",
            help="Path to the SQLite database containing the run.",
            exists=True,
            readable=True,
            resolve_path=True,
        ),
    ] = None,
    format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format: console or json.",
        ),
    ] = "console",
) -> None:
    """
    Generate a report for a completed run.

    Console format shows a rich timeline view with status icons.
    JSON format provides structured output for programmatic use.

    Example:
        $ capsule report abc123 --format json
    """
    # TODO: Implement in Phase 3, Step 3.2 (Report Commands)
    console.print(f"[yellow]report command not yet implemented[/yellow]")
    console.print(f"  Run ID: {run_id}")
    console.print(f"  Database: {db or 'capsule.db'}")
    console.print(f"  Format: {format}")


@app.command("list-runs")
def list_runs(
    db: Annotated[
        Optional[Path],
        typer.Option(
            "--db",
            help="Path to the SQLite database.",
            exists=True,
            readable=True,
            resolve_path=True,
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-n",
            help="Maximum number of runs to show.",
        ),
    ] = 20,
) -> None:
    """
    List all recorded runs.

    Shows a table of all runs with their IDs, timestamps, and status.

    Example:
        $ capsule list-runs --db runs.db
    """
    db_path = db or Path("capsule.db")

    if not db_path.exists():
        console.print(f"[yellow]No database found at {db_path}[/yellow]")
        raise typer.Exit(code=0)

    with Engine(db_path=db_path) as engine:
        runs = engine.list_runs(limit=limit)

        if not runs:
            console.print("[dim]No runs found.[/dim]")
            raise typer.Exit(code=0)

        table = Table(show_header=True, header_style="bold")
        table.add_column("Run ID", style="cyan")
        table.add_column("Created")
        table.add_column("Status", width=10)
        table.add_column("Mode", width=8)
        table.add_column("Steps", justify="right")
        table.add_column("Completed", justify="right")
        table.add_column("Denied", justify="right")
        table.add_column("Failed", justify="right")

        for r in runs:
            status = r["status"]
            if status == "completed":
                status_display = "[green]completed[/green]"
            elif status == "failed":
                status_display = "[red]failed[/red]"
            else:
                status_display = f"[yellow]{status}[/yellow]"

            table.add_row(
                r["run_id"],
                r["created_at"][:19],  # Truncate to seconds
                status_display,
                r["mode"],
                str(r["total_steps"]),
                str(r["completed_steps"]),
                str(r["denied_steps"]),
                str(r["failed_steps"]),
            )

        console.print(table)


@app.command("show-run")
def show_run(
    run_id: Annotated[
        str,
        typer.Argument(help="The run ID to show."),
    ],
    db: Annotated[
        Optional[Path],
        typer.Option(
            "--db",
            help="Path to the SQLite database containing the run.",
            exists=True,
            readable=True,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """
    Show details of a specific run.

    Displays the run metadata, all tool calls, and their results.

    Example:
        $ capsule show-run abc123 --db runs.db
    """
    db_path = db or Path("capsule.db")

    if not db_path.exists():
        console.print(f"[red]Database not found: {db_path}[/red]")
        raise typer.Exit(code=1)

    with Engine(db_path=db_path) as engine:
        summary = engine.get_run_summary(run_id)

        if not summary:
            console.print(f"[red]Run not found: {run_id}[/red]")
            raise typer.Exit(code=1)

        # Header
        status = summary["status"]
        if status == "completed":
            status_display = "[green]completed[/green]"
        elif status == "failed":
            status_display = "[red]failed[/red]"
        else:
            status_display = f"[yellow]{status}[/yellow]"

        console.print(f"[bold]Run {summary['run_id']}[/bold]")
        console.print(f"  Status: {status_display}")
        console.print(f"  Mode: {summary['mode']}")
        console.print(f"  Created: {summary['created_at'][:19]}")
        if summary.get("completed_at"):
            console.print(f"  Completed: {summary['completed_at'][:19]}")
        console.print()

        # Steps
        if summary.get("steps"):
            table = Table(show_header=True, header_style="bold")
            table.add_column("#", style="dim", width=3)
            table.add_column("Tool", style="cyan")
            table.add_column("Status", width=10)
            table.add_column("Duration", justify="right")
            table.add_column("Details")

            for step in summary["steps"]:
                step_num = str(step.get("step_index", 0) + 1)
                tool_name = step.get("tool", "unknown")
                step_status = step.get("status", "unknown")

                if step_status == "success":
                    status_col = "[green]success[/green]"
                elif step_status == "denied":
                    status_col = "[yellow]denied[/yellow]"
                else:
                    status_col = f"[red]{step_status}[/red]"

                # Calculate duration
                started = step.get("started_at", "")
                ended = step.get("ended_at", "")
                if started and ended:
                    duration = "—"  # Would need datetime parsing
                else:
                    duration = "—"

                # Details
                if step_status == "success":
                    output = step.get("output", "")
                    if output:
                        details = str(output)[:50] + ("..." if len(str(output)) > 50 else "")
                    else:
                        details = ""
                elif step_status == "denied":
                    policy = step.get("policy_decision", {})
                    details = policy.get("reason", "") if isinstance(policy, dict) else ""
                else:
                    details = step.get("error", "") or ""

                if len(details) > 60:
                    details = details[:57] + "..."

                table.add_row(step_num, tool_name, status_col, duration, details)

            console.print(table)
        else:
            console.print("[dim]No steps recorded.[/dim]")


if __name__ == "__main__":
    app()
