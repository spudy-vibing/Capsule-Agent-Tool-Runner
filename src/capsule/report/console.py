"""
Console report generator for Capsule.

Generates beautiful terminal output using Rich library.
Displays a timeline view of all tool calls with status icons,
arguments, results, and summary statistics.

Design Principles:
    - Human-readable first: Optimize for quick scanning
    - Status at a glance: Use icons and colors for status
    - Progressive detail: Summary first, details on request
    - Consistent formatting: Predictable layout across runs
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from capsule.schema import RunMode, RunStatus, ToolCallStatus
from capsule.store import CapsuleDB


# Status icons
ICON_SUCCESS = "[green]✓[/green]"
ICON_ERROR = "[red]✗[/red]"
ICON_DENIED = "[yellow]⊘[/yellow]"
ICON_PENDING = "[dim]○[/dim]"


def generate_console_report(
    run_id: str,
    db_path: str | Path = "capsule.db",
    console: Console | None = None,
    verbose: bool = False,
) -> None:
    """
    Generate and print a console report for a run.

    Args:
        run_id: ID of the run to report on
        db_path: Path to the SQLite database
        console: Rich Console instance (creates one if not provided)
        verbose: Whether to show verbose output (args, full output)
    """
    if console is None:
        console = Console()

    with CapsuleDB(db_path) as db:
        # Load run data
        run = db.get_run(run_id)
        if run is None:
            console.print(f"[red]Run not found: {run_id}[/red]")
            return

        calls = db.get_calls_for_run(run_id)
        results = db.get_results_for_run(run_id)
        results_by_call = {r.call_id: r for r in results}

        # Print header panel
        _print_header(console, run)
        console.print()

        # Print timeline
        _print_timeline(console, calls, results_by_call, verbose)
        console.print()

        # Print summary
        _print_summary(console, run, calls, results_by_call)


def _print_header(console: Console, run: Any) -> None:
    """Print the run header with status."""
    # Determine status styling
    if run.status == RunStatus.COMPLETED:
        status_style = "green"
        icon = ICON_SUCCESS
    elif run.status == RunStatus.FAILED:
        status_style = "red"
        icon = ICON_ERROR
    elif run.status == RunStatus.RUNNING:
        status_style = "yellow"
        icon = "[yellow]►[/yellow]"
    else:
        status_style = "dim"
        icon = ICON_PENDING

    # Format header
    header = Text()
    header.append(f" Run ", style="bold")
    header.append(run.run_id, style="bold cyan")
    header.append(f" │ ", style="dim")
    header.append(run.status.value.upper(), style=f"bold {status_style}")
    header.append(f" {icon}")

    # Mode indicator
    if run.mode == RunMode.REPLAY:
        header.append(" │ ", style="dim")
        header.append("REPLAY", style="bold magenta")

    console.print(Panel(header, expand=False))

    # Print timestamps
    console.print(f"  [dim]Created:[/dim]  {run.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if run.completed_at:
        duration = (run.completed_at - run.created_at).total_seconds()
        console.print(f"  [dim]Completed:[/dim] {run.completed_at.strftime('%Y-%m-%d %H:%M:%S')} ({duration:.2f}s)")


def _print_timeline(
    console: Console,
    calls: list,
    results_by_call: dict,
    verbose: bool,
) -> None:
    """Print the timeline of tool calls."""
    console.print("[bold]Timeline[/bold]")
    console.print()

    table = Table(
        show_header=True,
        header_style="bold",
        show_lines=verbose,
        expand=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Status", width=6, justify="center")
    table.add_column("Tool", style="cyan", width=15)
    table.add_column("Duration", justify="right", width=10)
    table.add_column("Details", overflow="fold")

    for call in calls:
        result = results_by_call.get(call.call_id)
        step_num = str(call.step_index + 1)

        # Status icon
        if result is None:
            status_icon = ICON_PENDING
            status_str = "pending"
        elif result.status == ToolCallStatus.SUCCESS:
            status_icon = ICON_SUCCESS
            status_str = "success"
        elif result.status == ToolCallStatus.DENIED:
            status_icon = ICON_DENIED
            status_str = "denied"
        else:
            status_icon = ICON_ERROR
            status_str = "error"

        # Duration
        if result:
            duration = (result.ended_at - result.started_at).total_seconds() * 1000
            duration_str = f"{duration:.1f}ms"
        else:
            duration_str = "—"

        # Details
        details = _format_details(call, result, verbose)

        table.add_row(step_num, status_icon, call.tool_name, duration_str, details)

    console.print(table)


def _format_details(call: Any, result: Any, verbose: bool) -> str:
    """Format the details column for a step."""
    parts = []

    # Show key arguments
    if verbose and call.args:
        args_str = ", ".join(f"{k}={_truncate(str(v), 30)}" for k, v in call.args.items())
        parts.append(f"[dim]args:[/dim] {args_str}")

    if result is None:
        return "\n".join(parts) if parts else "[dim]pending[/dim]"

    # Show result details based on status
    if result.status == ToolCallStatus.SUCCESS:
        if result.output is not None:
            output_str = str(result.output)
            if verbose:
                parts.append(f"[dim]output:[/dim] {_truncate(output_str, 100)}")
            else:
                parts.append(_truncate(output_str, 60))
    elif result.status == ToolCallStatus.DENIED:
        reason = result.policy_decision.reason if result.policy_decision else "unknown"
        parts.append(f"[yellow]{reason}[/yellow]")
        if result.policy_decision and result.policy_decision.rule_matched:
            parts.append(f"[dim]rule: {result.policy_decision.rule_matched}[/dim]")
    else:  # ERROR
        if result.error:
            parts.append(f"[red]{_truncate(result.error, 80)}[/red]")

    return "\n".join(parts) if parts else ""


def _truncate(s: str, max_len: int) -> str:
    """Truncate string with ellipsis."""
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _print_summary(
    console: Console,
    run: Any,
    calls: list,
    results_by_call: dict,
) -> None:
    """Print summary statistics."""
    console.print("[bold]Summary[/bold]")
    console.print()

    # Calculate statistics
    files_read = []
    files_written = []
    domains = []
    commands = []
    total_duration_ms = 0

    for call in calls:
        result = results_by_call.get(call.call_id)

        if result:
            duration = (result.ended_at - result.started_at).total_seconds() * 1000
            total_duration_ms += duration

        if call.tool_name == "fs.read":
            path = call.args.get("path", "unknown")
            files_read.append(path)
        elif call.tool_name == "fs.write":
            path = call.args.get("path", "unknown")
            files_written.append(path)
        elif call.tool_name == "http.get":
            url = call.args.get("url", "unknown")
            # Extract domain from URL
            if "://" in url:
                domain = url.split("://")[1].split("/")[0]
            else:
                domain = url.split("/")[0]
            domains.append(domain)
        elif call.tool_name == "shell.run":
            cmd = call.args.get("cmd", [])
            if isinstance(cmd, list) and cmd:
                commands.append(cmd[0])

    # Print stats table
    stats_table = Table(show_header=False, box=None, padding=(0, 2))
    stats_table.add_column("Metric", style="dim")
    stats_table.add_column("Value")

    stats_table.add_row("Total Steps", str(run.total_steps))
    stats_table.add_row(
        "Completed",
        f"[green]{run.completed_steps}[/green]" if run.completed_steps > 0 else "0",
    )
    stats_table.add_row(
        "Denied",
        f"[yellow]{run.denied_steps}[/yellow]" if run.denied_steps > 0 else "0",
    )
    stats_table.add_row(
        "Failed",
        f"[red]{run.failed_steps}[/red]" if run.failed_steps > 0 else "0",
    )
    stats_table.add_row("Duration", f"{total_duration_ms:.1f}ms")

    console.print(stats_table)
    console.print()

    # Print resource access summary
    if files_read or files_written or domains or commands:
        console.print("[bold]Resources Accessed[/bold]")
        console.print()

        if files_read:
            console.print(f"  [dim]Files Read ({len(files_read)}):[/dim]")
            for f in files_read[:5]:  # Show first 5
                console.print(f"    • {f}")
            if len(files_read) > 5:
                console.print(f"    [dim]... and {len(files_read) - 5} more[/dim]")

        if files_written:
            console.print(f"  [dim]Files Written ({len(files_written)}):[/dim]")
            for f in files_written[:5]:
                console.print(f"    • {f}")
            if len(files_written) > 5:
                console.print(f"    [dim]... and {len(files_written) - 5} more[/dim]")

        if domains:
            unique_domains = list(set(domains))
            console.print(f"  [dim]Domains Contacted ({len(unique_domains)}):[/dim]")
            for d in unique_domains[:5]:
                console.print(f"    • {d}")
            if len(unique_domains) > 5:
                console.print(f"    [dim]... and {len(unique_domains) - 5} more[/dim]")

        if commands:
            unique_commands = list(set(commands))
            console.print(f"  [dim]Shell Commands ({len(unique_commands)}):[/dim]")
            for c in unique_commands[:5]:
                console.print(f"    • {c}")
            if len(unique_commands) > 5:
                console.print(f"    [dim]... and {len(unique_commands) - 5} more[/dim]")
