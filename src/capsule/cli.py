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
    doctor      Check system environment and dependencies

Architecture Note:
    The CLI is intentionally thin - it parses arguments and delegates to the
    engine module for actual execution. This separation allows the core logic
    to be used programmatically without the CLI.
"""

import json
import sys
import traceback
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from capsule import __version__
from capsule.engine import Engine, RunResult
from capsule.replay import ReplayEngine
from capsule.report import generate_console_report, generate_json_report
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
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable debug mode with full error tracebacks.",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output results in JSON format.",
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
        if verbose and not json_output:
            console.print(f"[dim]Loaded plan: {plan_path}[/dim]")
            console.print(f"[dim]  Steps: {len(plan.steps)}[/dim]")
    except Exception as e:
        if json_output:
            _output_json_error("plan_load_error", str(e), debug)
        else:
            console.print(f"[red]Error loading plan: {e}[/red]")
            if debug:
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise typer.Exit(code=1)

    try:
        policy = load_policy(policy_path)
        if verbose and not json_output:
            console.print(f"[dim]Loaded policy: {policy_path}[/dim]")
    except Exception as e:
        if json_output:
            _output_json_error("policy_load_error", str(e), debug)
        else:
            console.print(f"[red]Error loading policy: {e}[/red]")
            if debug:
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise typer.Exit(code=1)

    # Execute the plan
    try:
        with Engine(db_path=db_path, working_dir=Path.cwd()) as engine:
            if verbose and not json_output:
                console.print(f"[dim]Using database: {db_path}[/dim]")
                console.print("[dim]Executing plan...[/dim]")
                console.print()

            result = engine.run(plan, policy, fail_fast=not no_fail_fast)

            # Display results
            if json_output:
                _output_json_result(result)
            else:
                _display_run_result(result, verbose)

            # Exit with appropriate code
            if result.success:
                raise typer.Exit(code=0)
            else:
                raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        if json_output:
            _output_json_error("execution_error", str(e), debug)
        else:
            console.print(f"[red]Execution error: {e}[/red]")
            if debug:
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
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


def _output_json_result(result: RunResult) -> None:
    """Output run results in JSON format."""
    output = {
        "run_id": result.run_id,
        "status": result.status.value,
        "success": result.success,
        "total_steps": result.total_steps,
        "completed_steps": result.completed_steps,
        "denied_steps": result.denied_steps,
        "failed_steps": result.failed_steps,
        "duration_ms": result.duration_ms,
        "steps": [
            {
                "step_index": step.step_index,
                "tool_name": step.tool_name,
                "args": step.args,
                "status": step.status.value,
                "output": step.output,
                "error": step.error,
                "policy_decision": {
                    "allowed": step.policy_decision.allowed,
                    "reason": step.policy_decision.reason,
                    "rule_matched": step.policy_decision.rule_matched,
                } if step.policy_decision else None,
                "duration_ms": step.duration_ms,
            }
            for step in result.steps
        ],
    }
    print(json.dumps(output, indent=2, default=str))


def _output_json_error(error_type: str, message: str, include_traceback: bool = False) -> None:
    """Output an error in JSON format."""
    output = {
        "error": True,
        "error_type": error_type,
        "message": message,
    }
    if include_traceback:
        output["traceback"] = traceback.format_exc()
    print(json.dumps(output, indent=2))


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
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Enable verbose output for debugging.",
        ),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable debug mode with full error tracebacks.",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output results in JSON format.",
        ),
    ] = False,
    verify: Annotated[
        bool,
        typer.Option(
            "--verify",
            help="Verify data integrity of the run before replaying.",
        ),
    ] = False,
) -> None:
    """
    Replay a previous run using stored results.

    Replays execute the same plan but return stored results instead of
    executing tools. This enables deterministic reproduction of past runs.

    Example:
        $ capsule replay abc123 --db runs.db
    """
    db_path = db or Path("capsule.db")

    if not db_path.exists():
        if json_output:
            _output_json_error("database_not_found", f"Database not found: {db_path}", debug)
        else:
            console.print(f"[red]Database not found: {db_path}[/red]")
        raise typer.Exit(code=1)

    try:
        with ReplayEngine(db_path=db_path) as engine:
            if verbose and not json_output:
                console.print(f"[dim]Using database: {db_path}[/dim]")

            # Optionally verify integrity first
            if verify:
                if verbose and not json_output:
                    console.print("[dim]Verifying run integrity...[/dim]")
                verification = engine.verify_run(run_id)
                if not verification["valid"]:
                    if json_output:
                        _output_json_error("integrity_error", str(verification["errors"]), debug)
                    else:
                        console.print("[red]Integrity verification failed:[/red]")
                        for error in verification["errors"]:
                            console.print(f"  [red]• {error}[/red]")
                    raise typer.Exit(code=1)
                elif verbose and not json_output:
                    console.print("[green]✓ Integrity verified[/green]")

            if verbose and not json_output:
                console.print("[dim]Replaying run...[/dim]")
                console.print()

            result = engine.replay(run_id)

            # Display results
            if json_output:
                _output_replay_json_result(result)
            else:
                _display_replay_result(result, verbose)

            # Exit with appropriate code
            if result.success:
                raise typer.Exit(code=0)
            else:
                raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        if json_output:
            _output_json_error("replay_error", str(e), debug)
        else:
            console.print(f"[red]Replay error: {e}[/red]")
            if debug:
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise typer.Exit(code=1)


def _display_replay_result(result, verbose: bool) -> None:
    """Display replay results in a formatted way."""
    # Status line with color
    if result.status == RunStatus.COMPLETED:
        status_style = "green"
        status_icon = "[green]✓[/green]"
    else:
        status_style = "red"
        status_icon = "[red]✗[/red]"

    console.print(f"{status_icon} Replay [bold]{result.replay_run_id}[/bold]: [{status_style}]{result.status.value}[/{status_style}]")
    console.print(f"[dim]  Original run: {result.original_run_id}[/dim]")

    if not result.plan_verified:
        console.print("[yellow]  Warning: Plan hash mismatch[/yellow]")

    if result.mismatches:
        console.print("[yellow]  Mismatches detected:[/yellow]")
        for mismatch in result.mismatches[:5]:
            console.print(f"[yellow]    • {mismatch}[/yellow]")
        if len(result.mismatches) > 5:
            console.print(f"[yellow]    ... and {len(result.mismatches) - 5} more[/yellow]")

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


def _output_replay_json_result(result) -> None:
    """Output replay results in JSON format."""
    output = {
        "replay_run_id": result.replay_run_id,
        "original_run_id": result.original_run_id,
        "status": result.status.value,
        "success": result.success,
        "plan_verified": result.plan_verified,
        "mismatches": result.mismatches,
        "total_steps": result.total_steps,
        "completed_steps": result.completed_steps,
        "denied_steps": result.denied_steps,
        "failed_steps": result.failed_steps,
        "steps": [
            {
                "step_index": step.step_index,
                "tool_name": step.tool_name,
                "args": step.args,
                "status": step.status.value,
                "output": step.output,
                "error": step.error,
                "original_call_id": step.original_call_id,
                "input_hash": step.input_hash,
                "output_hash": step.output_hash,
                "policy_decision": {
                    "allowed": step.policy_decision.allowed,
                    "reason": step.policy_decision.reason,
                    "rule_matched": step.policy_decision.rule_matched,
                } if step.policy_decision else None,
            }
            for step in result.steps
        ],
    }
    print(json.dumps(output, indent=2, default=str))


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
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Enable verbose output with additional details.",
        ),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable debug mode with full error tracebacks.",
        ),
    ] = False,
) -> None:
    """
    Generate a report for a completed run.

    Console format shows a rich timeline view with status icons.
    JSON format provides structured output for programmatic use.

    Example:
        $ capsule report abc123 --format json
    """
    db_path = db or Path("capsule.db")

    if not db_path.exists():
        console.print(f"[red]Database not found: {db_path}[/red]")
        raise typer.Exit(code=1)

    try:
        if format == "json":
            report_json = generate_json_report(run_id, db_path)
            print(report_json)
        else:
            generate_console_report(run_id, db_path, console=console, verbose=verbose)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]Report error: {e}[/red]")
        if debug:
            console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise typer.Exit(code=1)


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


@app.command()
def doctor(
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output results in JSON format.",
        ),
    ] = False,
) -> None:
    """
    Check system environment and dependencies.

    Verifies that Capsule's dependencies are properly configured:
    - Python version (3.11+)
    - Ollama connectivity and available models
    - Database accessibility

    Example:
        $ capsule doctor
    """
    checks = []
    all_ok = True

    # Check 1: Python version
    py_version = sys.version_info
    py_version_str = f"{py_version.major}.{py_version.minor}.{py_version.micro}"
    py_ok = py_version >= (3, 11)
    checks.append({
        "name": "Python version",
        "ok": py_ok,
        "value": py_version_str,
        "message": "OK" if py_ok else "Requires Python 3.11+",
    })
    if not py_ok:
        all_ok = False

    # Check 2: Ollama connectivity
    ollama_ok = False
    ollama_models: list[str] = []
    ollama_message = ""

    try:
        import httpx

        with httpx.Client(timeout=5.0) as client:
            response = client.get("http://localhost:11434/api/tags")
            if response.status_code == 200:
                data = response.json()
                ollama_models = [m["name"] for m in data.get("models", [])]
                if ollama_models:
                    ollama_ok = True
                    ollama_message = f"{len(ollama_models)} model(s) available"
                else:
                    ollama_message = "Connected but no models. Run: ollama pull qwen2.5:0.5b"
            else:
                ollama_message = f"HTTP {response.status_code}"
    except httpx.ConnectError:
        ollama_message = "Not running. Install from https://ollama.ai and run: ollama serve"
    except Exception as e:
        ollama_message = f"Error: {e}"

    checks.append({
        "name": "Ollama",
        "ok": ollama_ok,
        "value": "localhost:11434",
        "message": ollama_message,
        "models": ollama_models if ollama_ok else None,
    })
    if not ollama_ok:
        all_ok = False

    # Check 3: Default database path writability
    db_path = Path("capsule.db")
    db_ok = True
    db_message = ""

    try:
        if db_path.exists():
            db_message = f"Exists ({db_path.stat().st_size} bytes)"
        else:
            # Check if we can create it
            parent = db_path.parent.resolve()
            if parent.exists() and parent.is_dir():
                db_message = "Not found (will be created on first run)"
            else:
                db_ok = False
                db_message = f"Parent directory not writable: {parent}"
    except Exception as e:
        db_ok = False
        db_message = f"Error: {e}"

    checks.append({
        "name": "Database",
        "ok": db_ok,
        "value": str(db_path),
        "message": db_message,
    })
    if not db_ok:
        all_ok = False

    # Output results
    if json_output:
        output = {
            "ok": all_ok,
            "version": __version__,
            "checks": checks,
        }
        print(json.dumps(output, indent=2))
    else:
        console.print(f"[bold]Capsule Doctor[/bold] v{__version__}")
        console.print()

        for check in checks:
            icon = "[green]✓[/green]" if check["ok"] else "[red]✗[/red]"
            name = check["name"]
            value = check.get("value", "")
            message = check.get("message", "")

            if check["ok"]:
                console.print(f"{icon} {name}: [dim]{value}[/dim] - {message}")
            else:
                console.print(f"{icon} {name}: [dim]{value}[/dim]")
                console.print(f"    [red]{message}[/red]")

            # Show models if Ollama check
            if check["name"] == "Ollama" and check.get("models"):
                console.print("    Available models:")
                for model in check["models"][:5]:
                    console.print(f"      [cyan]• {model}[/cyan]")
                if len(check["models"]) > 5:
                    console.print(f"      [dim]... and {len(check['models']) - 5} more[/dim]")

        console.print()
        if all_ok:
            console.print("[green]All checks passed![/green]")
        else:
            console.print("[yellow]Some checks failed. See above for details.[/yellow]")

    raise typer.Exit(code=0 if all_ok else 1)


# =============================================================================
# Agent Subcommand Group
# =============================================================================

agent_app = typer.Typer(
    name="agent",
    help="Run dynamic agent tasks with planner-driven execution.",
    no_args_is_help=True,
)
app.add_typer(agent_app, name="agent")


@agent_app.command("run")
def agent_run(
    task: Annotated[
        str,
        typer.Argument(help="The task description for the agent to execute."),
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
    tools_path: Annotated[
        Optional[Path],
        typer.Option(
            "--tools",
            "-t",
            help="Path to the tools YAML file (optional, uses built-in tools by default).",
            exists=True,
            readable=True,
            resolve_path=True,
        ),
    ] = None,
    planner_backend: Annotated[
        str,
        typer.Option(
            "--planner",
            help="Planner backend to use.",
        ),
    ] = "ollama",
    model: Annotated[
        str,
        typer.Option(
            "--model",
            "-m",
            help="Model name for the planner.",
        ),
    ] = "qwen2.5:0.5b",
    max_iterations: Annotated[
        int,
        typer.Option(
            "--max-iterations",
            help="Maximum number of iterations.",
        ),
    ] = 20,
    working_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--working-dir",
            "-w",
            help="Working directory for tool execution.",
            resolve_path=True,
        ),
    ] = None,
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--out",
            "-o",
            help="Path to output SQLite database. Defaults to capsule.db.",
            resolve_path=True,
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output results in JSON format.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Enable verbose output.",
        ),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable debug mode with full error tracebacks.",
        ),
    ] = False,
    pretty: Annotated[
        bool,
        typer.Option(
            "--pretty",
            help="Human-readable output showing full tool results.",
        ),
    ] = False,
) -> None:
    """
    Execute a dynamic agent task using a planner.

    The agent uses a planner (like Ollama with an SLM) to dynamically
    decide what tools to call based on the task description and
    execution history.

    Example:
        $ capsule agent run "List all Python files" --policy policy.yaml
        $ capsule agent run "Count lines in README.md" -p policy.yaml --model qwen2.5:0.5b
    """
    from capsule.agent import AgentConfig, AgentLoop
    from capsule.planner.ollama import OllamaPlanner
    from capsule.policy.engine import PolicyEngine
    from capsule.schema import PlannerConfig
    from capsule.store.db import CapsuleDB
    from capsule.tools.registry import default_registry

    db_path = output or Path("capsule.db")
    work_dir = str(working_dir or Path.cwd())

    # Load policy
    try:
        policy = load_policy(policy_path)
        if verbose and not json_output:
            console.print(f"[dim]Loaded policy: {policy_path}[/dim]")
    except Exception as e:
        if json_output:
            _output_json_error("policy_load_error", str(e), debug)
        else:
            console.print(f"[red]Error loading policy: {e}[/red]")
            if debug:
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise typer.Exit(code=1)

    # Create planner
    if planner_backend == "ollama":
        planner_config = PlannerConfig(
            backend="ollama",
            model=model,
        )
        planner = OllamaPlanner(planner_config)

        # Check connection
        ok, message = planner.check_connection()
        if not ok:
            if json_output:
                _output_json_error("planner_connection_error", message, debug)
            else:
                console.print(f"[red]Planner error: {message}[/red]")
            raise typer.Exit(code=1)

        if verbose and not json_output:
            console.print(f"[dim]Using planner: {planner.get_name()}[/dim]")
    else:
        if json_output:
            _output_json_error("invalid_planner", f"Unknown planner: {planner_backend}", debug)
        else:
            console.print(f"[red]Unknown planner: {planner_backend}[/red]")
        raise typer.Exit(code=1)

    # Create components
    try:
        policy_engine = PolicyEngine(policy)
        db = CapsuleDB(db_path)
        agent_config = AgentConfig(max_iterations=max_iterations)

        if verbose and not json_output:
            console.print(f"[dim]Using database: {db_path}[/dim]")
            console.print(f"[dim]Working directory: {work_dir}[/dim]")
            console.print(f"[dim]Max iterations: {max_iterations}[/dim]")
            console.print()
            console.print(f"[bold]Task:[/bold] {task}")
            console.print()

        # Create and run agent loop
        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=default_registry,
            db=db,
            config=agent_config,
        )

        result = loop.run(task=task, working_dir=work_dir)

        # Output results
        if json_output:
            _output_agent_json_result(result)
        elif pretty:
            _display_agent_result_pretty(result, task)
        else:
            _display_agent_result(result, verbose)

        # Cleanup
        db.close()
        planner.close()

        # Exit with appropriate code
        if result.status == "completed":
            raise typer.Exit(code=0)
        else:
            raise typer.Exit(code=1)

    except typer.Exit:
        raise
    except Exception as e:
        if json_output:
            _output_json_error("agent_error", str(e), debug)
        else:
            console.print(f"[red]Agent error: {e}[/red]")
            if debug:
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise typer.Exit(code=1)


def _display_agent_result(result, verbose: bool, validation=None) -> None:
    """Display agent results in a formatted way."""
    from capsule.schema import ToolCallStatus

    # Status line with color
    status = result.status
    if status == "completed":
        status_style = "green"
        status_icon = "[green]✓[/green]"
    elif status in ("max_iterations", "timeout", "repetition_detected"):
        status_style = "yellow"
        status_icon = "[yellow]![/yellow]"
    else:
        status_style = "red"
        status_icon = "[red]✗[/red]"

    console.print(
        f"{status_icon} Agent Run [bold]{result.run_id}[/bold]: "
        f"[{status_style}]{status}[/{status_style}]"
    )
    console.print(f"[dim]  Planner: {result.planner_name}[/dim]")
    console.print(f"[dim]  Duration: {result.total_duration_seconds:.2f}s[/dim]")
    console.print()

    if result.error_message:
        console.print(f"[red]Error: {result.error_message}[/red]")
        console.print()

    # Iteration table
    if result.iterations:
        table = Table(show_header=True, header_style="bold")
        table.add_column("#", style="dim", width=3)
        table.add_column("Tool", style="cyan")
        table.add_column("Status", width=10)
        table.add_column("Duration", justify="right", width=10)
        table.add_column("Details")

        for iter_result in result.iterations:
            iter_num = str(iter_result.iteration + 1)

            # Check if this was a done signal
            if iter_result.done:
                tool_name = "[done]"
                status_col = "[blue]done[/blue]"
                details = iter_result.done.reason
            elif iter_result.tool_call:
                tool_name = iter_result.tool_call.tool_name

                if iter_result.tool_result:
                    tr_status = iter_result.tool_result.status
                    if tr_status == ToolCallStatus.SUCCESS:
                        status_col = "[green]success[/green]"
                        output = iter_result.tool_result.output
                        if output:
                            details = str(output)[:50]
                            if len(str(output)) > 50:
                                details += "..."
                        else:
                            details = ""
                    elif tr_status == ToolCallStatus.DENIED:
                        status_col = "[yellow]denied[/yellow]"
                        details = (
                            iter_result.policy_decision.reason
                            if iter_result.policy_decision
                            else ""
                        )
                    else:
                        status_col = "[red]error[/red]"
                        details = iter_result.tool_result.error or ""
                else:
                    status_col = "[dim]pending[/dim]"
                    details = ""
            else:
                tool_name = "[unknown]"
                status_col = "[dim]unknown[/dim]"
                details = ""

            duration = f"{iter_result.duration_seconds:.2f}s"

            # Truncate details
            if len(details) > 50:
                details = details[:47] + "..."

            table.add_row(iter_num, tool_name, status_col, duration, details)

        console.print(table)
        console.print()

    # Final output
    if result.final_output:
        console.print("[bold]Final Output:[/bold]")
        if isinstance(result.final_output, dict):
            console.print(json.dumps(result.final_output, indent=2))
        else:
            console.print(str(result.final_output))
        console.print()

    # Summary
    total_iterations = len(result.iterations)
    successful = sum(
        1
        for i in result.iterations
        if i.tool_result and i.tool_result.status == ToolCallStatus.SUCCESS
    )
    denied = sum(
        1
        for i in result.iterations
        if i.tool_result and i.tool_result.status == ToolCallStatus.DENIED
    )
    failed = sum(
        1
        for i in result.iterations
        if i.tool_result and i.tool_result.status == ToolCallStatus.ERROR
    )

    console.print(
        f"[dim]Iterations: {total_iterations} | "
        f"Successful: {successful} | "
        f"Denied: {denied} | "
        f"Failed: {failed}[/dim]"
    )

    # Show validation results if present
    if validation is not None:
        console.print()
        if validation.hallucinated_paths:
            console.print("[yellow]⚠ Output Validation Warning[/yellow]")
            console.print(
                f"[yellow]  Found {len(validation.hallucinated_paths)} path(s) not accessed during execution:[/yellow]"
            )
            for path in validation.hallucinated_paths[:5]:
                console.print(f"[yellow]    - {path}[/yellow]")
            if len(validation.hallucinated_paths) > 5:
                console.print(f"[yellow]    ... and {len(validation.hallucinated_paths) - 5} more[/yellow]")

            if validation.accessed_paths:
                console.print(f"[dim]  Actually accessed: {', '.join(validation.accessed_paths[:3])}[/dim]")
        elif validation.accessed_paths:
            console.print("[green]✓ Output validation passed[/green]")
            if verbose:
                console.print(f"[dim]  Files accessed: {len(validation.accessed_paths)}[/dim]")


def _display_agent_result_pretty(result, task: str) -> None:
    """Display agent results in human-readable format with full tool outputs."""
    from capsule.schema import ToolCallStatus

    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.markdown import Markdown

    # Header
    console.print()
    console.print(Panel(f"[bold]{task}[/bold]", title="Task", border_style="blue"))
    console.print()

    # Status
    status = result.status
    if status == "completed":
        status_icon = "[green]✓[/green]"
        status_text = "[green]Completed[/green]"
    elif status in ("max_iterations", "timeout", "repetition_detected"):
        status_icon = "[yellow]![/yellow]"
        status_text = f"[yellow]{status}[/yellow]"
    else:
        status_icon = "[red]✗[/red]"
        status_text = f"[red]{status}[/red]"

    console.print(f"{status_icon} Status: {status_text} | Duration: {result.total_duration_seconds:.2f}s")
    console.print()

    if result.error_message:
        console.print(Panel(f"[red]{result.error_message}[/red]", title="Error", border_style="red"))
        console.print()

    # Iterations with full output
    for iter_result in result.iterations:
        iter_num = iter_result.iteration + 1

        if iter_result.done:
            # Done signal
            console.print(f"[bold blue]Step {iter_num}:[/bold blue] [blue]Done[/blue]")
            if iter_result.done.reason:
                console.print(f"  Reason: {iter_result.done.reason}")
            if iter_result.done.final_output:
                console.print(f"  Output: {iter_result.done.final_output}")
            console.print()

        elif iter_result.tool_call:
            tc = iter_result.tool_call
            tr = iter_result.tool_result

            # Tool call header
            args_str = ", ".join(f"{k}={repr(v)}" for k, v in tc.args.items())
            console.print(f"[bold cyan]Step {iter_num}:[/bold cyan] {tc.tool_name}({args_str})")

            if tr:
                if tr.status == ToolCallStatus.SUCCESS:
                    console.print(f"  [green]✓ Success[/green] ({iter_result.duration_seconds:.2f}s)")

                    # Display output
                    if tr.output:
                        output = tr.output
                        if isinstance(output, dict):
                            # Shell command output
                            if "stdout" in output:
                                stdout = output.get("stdout", "")
                                stderr = output.get("stderr", "")
                                return_code = output.get("return_code", 0)

                                if stdout:
                                    console.print()
                                    console.print(Panel(
                                        stdout.rstrip(),
                                        title=f"Output (exit {return_code})",
                                        border_style="green" if return_code == 0 else "yellow",
                                    ))
                                if stderr:
                                    console.print(Panel(stderr.rstrip(), title="Stderr", border_style="yellow"))
                            else:
                                # Other dict output
                                console.print()
                                console.print(Panel(
                                    json.dumps(output, indent=2),
                                    title="Output",
                                    border_style="green",
                                ))
                        else:
                            # String output (file contents, etc.)
                            output_str = str(output)
                            if len(output_str) > 2000:
                                output_str = output_str[:2000] + "\n... (truncated)"
                            console.print()
                            console.print(Panel(output_str, title="Output", border_style="green"))

                elif tr.status == ToolCallStatus.DENIED:
                    console.print(f"  [yellow]✗ Denied[/yellow]: {tr.error or 'Policy violation'}")

                else:
                    console.print(f"  [red]✗ Error[/red]: {tr.error or 'Unknown error'}")

            console.print()

    # Final output if any
    if result.final_output:
        console.print(Panel(
            str(result.final_output),
            title="[bold]Final Answer[/bold]",
            border_style="green",
        ))
        console.print()

    # Summary line
    total = len(result.iterations)
    successful = sum(1 for i in result.iterations if i.tool_result and i.tool_result.status == ToolCallStatus.SUCCESS)
    console.print(f"[dim]─── {total} steps, {successful} successful ───[/dim]")


def _output_agent_json_result(result, validation=None) -> None:
    """Output agent results in JSON format."""
    from capsule.schema import ToolCallStatus

    output = {
        "run_id": result.run_id,
        "task": result.task,
        "status": result.status,
        "planner_name": result.planner_name,
        "total_duration_seconds": result.total_duration_seconds,
        "final_output": result.final_output,
        "error_message": result.error_message,
        "iterations": [
            {
                "iteration": i.iteration,
                "duration_seconds": i.duration_seconds,
                "tool_call": {
                    "tool_name": i.tool_call.tool_name,
                    "args": i.tool_call.args,
                }
                if i.tool_call
                else None,
                "tool_result": {
                    "status": i.tool_result.status.value,
                    "output": i.tool_result.output,
                    "error": i.tool_result.error,
                }
                if i.tool_result
                else None,
                "done": {
                    "final_output": i.done.final_output,
                    "reason": i.done.reason,
                }
                if i.done
                else None,
                "policy_decision": {
                    "allowed": i.policy_decision.allowed,
                    "reason": i.policy_decision.reason,
                }
                if i.policy_decision
                else None,
            }
            for i in result.iterations
        ],
    }

    # Add validation results if present
    if validation is not None:
        output["validation"] = {
            "is_valid": validation.is_valid,
            "hallucinated_paths": validation.hallucinated_paths,
            "accessed_paths": validation.accessed_paths,
            "warnings": validation.warnings,
        }

    print(json.dumps(output, indent=2, default=str))


# =============================================================================
# Pack Subcommand Group
# =============================================================================

pack_app = typer.Typer(
    name="pack",
    help="Manage and run Capsule packs.",
    no_args_is_help=True,
)
app.add_typer(pack_app, name="pack")


@pack_app.command("list")
def pack_list(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output in JSON format."),
    ] = False,
) -> None:
    """List available packs (bundled and discovered)."""
    from capsule.pack.loader import PackLoader

    try:
        packs = PackLoader.list_bundled_packs()

        if json_output:
            output = {
                "packs": packs,
                "count": len(packs),
            }
            print(json.dumps(output, indent=2))
        else:
            if not packs:
                console.print("[dim]No packs found.[/dim]")
                console.print()
                console.print(
                    "[dim]Packs should be in the 'packs/' directory with a manifest.yaml file.[/dim]"
                )
            else:
                console.print(f"[bold]Available Packs ({len(packs)})[/bold]")
                console.print()
                for pack_name in packs:
                    try:
                        loader = PackLoader.resolve_pack(pack_name)
                        manifest = loader.manifest
                        desc = manifest.description[:60] + "..." if len(manifest.description) > 60 else manifest.description
                        console.print(f"  [cyan]{pack_name}[/cyan] v{manifest.version}")
                        if desc:
                            console.print(f"    [dim]{desc}[/dim]")
                    except Exception:
                        console.print(f"  [cyan]{pack_name}[/cyan] [red](error loading)[/red]")

        raise typer.Exit(code=0)

    except typer.Exit:
        raise
    except Exception as e:
        if json_output:
            _output_json_error("pack_list_error", str(e), False)
        else:
            console.print(f"[red]Error listing packs: {e}[/red]")
        raise typer.Exit(code=1)


@pack_app.command("info")
def pack_info(
    pack_name: Annotated[
        str,
        typer.Argument(help="Pack name or path to pack directory."),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output in JSON format."),
    ] = False,
) -> None:
    """Show detailed information about a pack."""
    from capsule.pack.loader import PackLoader

    try:
        loader = PackLoader.resolve_pack(pack_name)
        manifest = loader.manifest

        if json_output:
            output = {
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "author": manifest.author,
                "license": manifest.license,
                "tags": manifest.tags,
                "capsule_version": manifest.capsule_version,
                "tools_required": manifest.tools_required,
                "yaml_entry": manifest.yaml_entry,
                "prompt_template": manifest.prompt_template,
                "policy": "policy.yaml",
                "inputs": {
                    name: {
                        "type": schema.type,
                        "required": schema.required,
                        "default": schema.default,
                        "description": schema.description,
                        "enum": schema.enum,
                    }
                    for name, schema in manifest.inputs.items()
                },
                "outputs": {
                    name: {
                        "type": schema.type,
                        "description": schema.description,
                    }
                    for name, schema in manifest.outputs.items()
                },
                "pack_path": str(loader.pack_path),
            }
            print(json.dumps(output, indent=2))
        else:
            console.print(f"[bold cyan]{manifest.name}[/bold cyan] v{manifest.version}")
            console.print()

            if manifest.description:
                console.print(f"[bold]Description:[/bold] {manifest.description}")

            if manifest.author:
                console.print(f"[bold]Author:[/bold] {manifest.author}")

            console.print(f"[bold]License:[/bold] {manifest.license}")

            if manifest.tags:
                console.print(f"[bold]Tags:[/bold] {', '.join(manifest.tags)}")

            console.print(f"[bold]Capsule Version:[/bold] {manifest.capsule_version}")
            console.print()

            console.print(f"[bold]Tools Required:[/bold] {', '.join(manifest.tools_required) or 'none'}")
            console.print(f"[bold]YAML Entry:[/bold] {manifest.yaml_entry or 'none (agent-only)'}")
            console.print(f"[bold]Prompt Template:[/bold] {manifest.prompt_template or 'none'}")
            console.print("[bold]Policy:[/bold] policy.yaml")
            console.print()

            if manifest.inputs:
                console.print("[bold]Inputs:[/bold]")
                for name, schema in manifest.inputs.items():
                    req = "[red]*[/red]" if schema.required else ""
                    default = f" (default: {schema.default})" if schema.default is not None else ""
                    console.print(f"  {req}[cyan]{name}[/cyan]: {schema.type}{default}")
                    if schema.description:
                        console.print(f"    [dim]{schema.description}[/dim]")
                    if schema.enum:
                        console.print(f"    [dim]Allowed: {', '.join(schema.enum)}[/dim]")
                console.print()

            if manifest.outputs:
                console.print("[bold]Outputs:[/bold]")
                for name, schema in manifest.outputs.items():
                    console.print(f"  [cyan]{name}[/cyan]: {schema.type}")
                    if schema.description:
                        console.print(f"    [dim]{schema.description}[/dim]")
                console.print()

            console.print(f"[dim]Pack path: {loader.pack_path}[/dim]")

        raise typer.Exit(code=0)

    except typer.Exit:
        raise
    except Exception as e:
        if json_output:
            _output_json_error("pack_info_error", str(e), False)
        else:
            console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


@pack_app.command("validate")
def pack_validate(
    pack_path: Annotated[
        Path,
        typer.Argument(
            help="Path to pack directory.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output in JSON format."),
    ] = False,
) -> None:
    """Validate a pack's structure and manifest."""
    from capsule.pack.loader import PackLoader

    try:
        loader = PackLoader(pack_path)
        errors = loader.validate_structure()

        if json_output:
            output = {
                "valid": len(errors) == 0,
                "errors": errors,
                "pack_path": str(pack_path),
            }
            if len(errors) == 0:
                output["manifest"] = {
                    "name": loader.manifest.name,
                    "version": loader.manifest.version,
                }
            print(json.dumps(output, indent=2))
        else:
            if errors:
                console.print(f"[red]Pack validation failed: {len(errors)} error(s)[/red]")
                console.print()
                for error in errors:
                    console.print(f"  [red]•[/red] {error}")
            else:
                manifest = loader.manifest
                console.print(f"[green]✓[/green] Pack [cyan]{manifest.name}[/cyan] v{manifest.version} is valid")

        raise typer.Exit(code=0 if len(errors) == 0 else 1)

    except typer.Exit:
        raise
    except Exception as e:
        if json_output:
            _output_json_error("pack_validate_error", str(e), False)
        else:
            console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


@pack_app.command("run")
def pack_run(
    pack_name: Annotated[
        str,
        typer.Argument(help="Pack name or path to pack directory."),
    ],
    input_args: Annotated[
        Optional[list[str]],
        typer.Option(
            "--input",
            "-i",
            help="Input argument in key=value format. Can be repeated.",
        ),
    ] = None,
    policy_path: Annotated[
        Optional[Path],
        typer.Option(
            "--policy",
            "-p",
            help="Path to policy YAML file (overrides pack policy).",
            exists=True,
            readable=True,
            resolve_path=True,
        ),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            "-m",
            help="Execution mode: 'agent' (planner-driven) or 'yaml' (plan-based).",
        ),
    ] = "agent",
    planner_backend: Annotated[
        str,
        typer.Option("--planner", help="Planner backend to use."),
    ] = "ollama",
    model: Annotated[
        str,
        typer.Option("--model", help="Model name for the planner."),
    ] = "qwen2.5:0.5b",
    max_iterations: Annotated[
        int,
        typer.Option("--max-iterations", help="Maximum agent iterations."),
    ] = 50,
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--out",
            "-o",
            help="Path to output SQLite database.",
            resolve_path=True,
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output in JSON format."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose output."),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable debug output with tracebacks."),
    ] = False,
) -> None:
    """Execute a pack in agent or YAML mode."""
    from capsule.pack.loader import PackLoader
    from capsule.schema import load_policy

    try:
        # Load pack
        loader = PackLoader.resolve_pack(pack_name)
        manifest = loader.manifest

        if verbose and not json_output:
            console.print(f"[bold]Running pack:[/bold] {manifest.name} v{manifest.version}")
            console.print()

        # Parse input arguments
        inputs = {}
        if input_args:
            for arg in input_args:
                if "=" not in arg:
                    raise ValueError(f"Invalid input format: {arg}. Expected key=value")
                key, value = arg.split("=", 1)
                # Try to parse JSON for complex values
                try:
                    inputs[key] = json.loads(value)
                except json.JSONDecodeError:
                    inputs[key] = value

        # Validate and apply defaults
        validated_inputs = loader.get_validated_inputs(inputs)

        if verbose and not json_output:
            console.print("[bold]Inputs:[/bold]")
            for key, value in validated_inputs.items():
                console.print(f"  {key}: {value}")
            console.print()

        # Load/merge policy
        if policy_path:
            policy = load_policy(policy_path)
        else:
            policy = loader.load_policy()

        # Choose execution mode
        if mode == "yaml":
            # YAML mode: run static plan
            plan = loader.get_plan()
            if plan is None:
                raise ValueError(
                    f"Pack '{manifest.name}' has no YAML entry. Use --mode agent instead."
                )

            # Run via engine
            db_path = output or Path("capsule.db")

            with Engine(db_path=db_path, working_dir=Path.cwd()) as engine:
                result = engine.run(plan, policy, fail_fast=False)

                if json_output:
                    _output_json_result(result)
                else:
                    _display_run_result(result, verbose)

                raise typer.Exit(code=0 if result.success else 1)

        elif mode == "agent":
            # Agent mode: run with planner
            from capsule.agent.loop import AgentConfig, AgentLoop
            from capsule.planner.ollama import OllamaConfig, OllamaPlanner
            from capsule.policy.engine import PolicyEngine
            from capsule.store.db import CapsuleDB
            from capsule.tools.registry import default_registry

            # Check planner backend
            if planner_backend != "ollama":
                raise ValueError(f"Unknown planner backend: {planner_backend}. Only 'ollama' is supported.")

            # Render pack system prompt if available
            pack_prompt = None
            if manifest.prompt_template:
                pack_prompt = loader.render_prompt(validated_inputs)
                if verbose and not json_output:
                    console.print("[bold]Pack Prompt:[/bold]")
                    console.print(f"[dim]{pack_prompt[:500]}...[/dim]" if len(pack_prompt) > 500 else f"[dim]{pack_prompt}[/dim]")
                    console.print()

            # Create combined system prompt that includes:
            # 1. Pack's task-specific instructions
            # 2. OllamaPlanner's JSON response format rules
            # Note: Double braces {{ and }} are literal braces in f-strings
            # Note: {policy_summary} is included even though pack prompt may already
            #       have it via Jinja2, because OllamaPlanner's .format() expects it
            # IMPORTANT: Escape braces in pack_prompt because OllamaPlanner calls
            #            .format() on the system prompt, and pack prompts may contain
            #            regex patterns with braces like {16} or {3,}
            if pack_prompt:
                # Build combined system prompt with JSON format instructions at the top
                # OllamaPlanner uses .replace() for {tool_schemas} and {policy_summary}
                # so we can use literal braces in the JSON examples
                combined_system_prompt = f"""## CRITICAL: Response Format

You MUST respond with ONLY a valid JSON object. No markdown, no explanations, ONLY JSON.

To call a tool: {{"tool": "tool_name", "args": {{...}}}}
When complete: {{"done": true, "reason": "task_complete", "output": "your_summary"}}

Available tools:
{{tool_schemas}}

Policy constraints:
{{policy_summary}}

---

## Your Task

{pack_prompt}

---

REMEMBER: Respond with ONLY valid JSON. Your response must start with {{ and end with }}."""
            else:
                # Use default OllamaPlanner prompt
                combined_system_prompt = None

            # Initialize planner with combined prompt
            ollama_config = OllamaConfig(
                model=model,
                system_prompt=combined_system_prompt,
            )
            planner = OllamaPlanner(ollama_config)

            # Check planner connection
            ok, message = planner.check_connection()
            if not ok:
                if not json_output:
                    console.print(f"[red]Planner not available: {message}[/red]")
                    console.print("[dim]Run 'capsule doctor' to check your setup.[/dim]")
                raise typer.Exit(code=1)

            # Build task description - just the inputs, not the full prompt
            task = f"Execute the task described in the system prompt with these inputs: {json.dumps(validated_inputs)}"

            # Initialize components
            policy_engine = PolicyEngine(policy)
            db_path = output or Path("capsule.db")
            db = CapsuleDB(db_path)
            agent_config = AgentConfig(max_iterations=max_iterations)

            # Create and run agent loop
            loop = AgentLoop(
                planner=planner,
                policy_engine=policy_engine,
                registry=default_registry,
                db=db,
                config=agent_config,
            )

            result = loop.run(task=task, working_dir=Path.cwd())

            # Validate output against execution context
            from capsule.agent.validation import validate_output, format_validation_result
            validation = validate_output(
                result.final_output,
                result.execution_context,
                strict=False,  # Warn but don't fail
            )

            # Output results
            if json_output:
                _output_agent_json_result(result, validation)
            else:
                _display_agent_result(result, verbose, validation)

            # Cleanup
            db.close()
            planner.close()

            # Exit with appropriate code
            if result.status == "completed":
                raise typer.Exit(code=0)
            else:
                raise typer.Exit(code=1)

        else:
            raise ValueError(f"Unknown mode: {mode}. Use 'agent' or 'yaml'.")

    except typer.Exit:
        raise
    except Exception as e:
        if json_output:
            _output_json_error("pack_run_error", str(e), debug)
        else:
            console.print(f"[red]Error: {e}[/red]")
            if debug:
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
