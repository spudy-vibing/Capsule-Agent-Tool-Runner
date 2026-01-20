"""
JSON report generator for Capsule.

Generates structured JSON output for programmatic consumption.
Includes all run metadata, tool calls, results, and policy decisions.

Design Principles:
    - Complete data: Include everything for full reproducibility
    - Consistent schema: Same structure across all runs
    - Human-readable keys: Use descriptive snake_case names
    - ISO timestamps: Standard datetime format
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from capsule.store import CapsuleDB


def generate_json_report(
    run_id: str,
    db_path: str | Path = "capsule.db",
    indent: int = 2,
) -> str:
    """
    Generate a JSON report for a run.

    Args:
        run_id: ID of the run to report on
        db_path: Path to the SQLite database
        indent: JSON indentation level (default: 2)

    Returns:
        JSON string with full run report

    Raises:
        ValueError: If run not found
    """
    report = build_report_dict(run_id, db_path)
    return json.dumps(report, indent=indent, default=_json_serializer)


def build_report_dict(
    run_id: str,
    db_path: str | Path = "capsule.db",
) -> dict[str, Any]:
    """
    Build a report dictionary for a run.

    Args:
        run_id: ID of the run to report on
        db_path: Path to the SQLite database

    Returns:
        Dictionary with full run report

    Raises:
        ValueError: If run not found
    """
    with CapsuleDB(db_path) as db:
        # Load run data
        run = db.get_run(run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")

        # Load plan and policy
        plan = db.get_run_plan(run_id)
        policy = db.get_run_policy(run_id)

        # Load calls and results
        calls = db.get_calls_for_run(run_id)
        results = db.get_results_for_run(run_id)
        results_by_call = {r.call_id: r for r in results}

        # Build report structure
        report = {
            "report_version": "1.0",
            "generated_at": datetime.now(UTC).isoformat(),
            "run": {
                "run_id": run.run_id,
                "created_at": run.created_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "status": run.status.value,
                "mode": run.mode.value,
                "plan_hash": run.plan_hash,
                "policy_hash": run.policy_hash,
                "statistics": {
                    "total_steps": run.total_steps,
                    "completed_steps": run.completed_steps,
                    "denied_steps": run.denied_steps,
                    "failed_steps": run.failed_steps,
                },
            },
            "plan": _serialize_plan(plan) if plan else None,
            "policy": _serialize_policy(policy) if policy else None,
            "steps": [],
            "summary": _build_summary(calls, results_by_call),
        }

        # Build steps array
        for call in calls:
            result = results_by_call.get(call.call_id)
            step = {
                "step_index": call.step_index,
                "call_id": call.call_id,
                "tool_name": call.tool_name,
                "args": call.args,
                "created_at": call.created_at.isoformat(),
            }

            if result:
                step["result"] = {
                    "status": result.status.value,
                    "output": result.output,
                    "error": result.error,
                    "policy_decision": {
                        "allowed": result.policy_decision.allowed,
                        "reason": result.policy_decision.reason,
                        "rule_matched": result.policy_decision.rule_matched,
                    },
                    "timing": {
                        "started_at": result.started_at.isoformat(),
                        "ended_at": result.ended_at.isoformat(),
                        "duration_ms": (result.ended_at - result.started_at).total_seconds() * 1000,
                    },
                    "hashes": {
                        "input": result.input_hash,
                        "output": result.output_hash,
                    },
                }
            else:
                step["result"] = None

            report["steps"].append(step)

        return report


def _serialize_plan(plan: Any) -> dict[str, Any]:
    """Serialize a Plan object to dict."""
    return {
        "version": plan.version,
        "name": plan.name,
        "description": plan.description,
        "steps": [
            {
                "tool": step.tool,
                "args": step.args,
                "id": step.id,
                "name": step.name,
            }
            for step in plan.steps
        ],
    }


def _serialize_policy(policy: Any) -> dict[str, Any]:
    """Serialize a Policy object to dict."""
    return {
        "boundary": policy.boundary.value,
        "global_timeout_seconds": policy.global_timeout_seconds,
        "max_calls_per_tool": policy.max_calls_per_tool,
        "tools": {
            "fs.read": {
                "allow_paths": policy.tools.fs_read.allow_paths,
                "deny_paths": policy.tools.fs_read.deny_paths,
                "max_size_bytes": policy.tools.fs_read.max_size_bytes,
                "allow_hidden": policy.tools.fs_read.allow_hidden,
            },
            "fs.write": {
                "allow_paths": policy.tools.fs_write.allow_paths,
                "deny_paths": policy.tools.fs_write.deny_paths,
                "max_size_bytes": policy.tools.fs_write.max_size_bytes,
                "allow_hidden": policy.tools.fs_write.allow_hidden,
            },
            "http.get": {
                "allow_domains": policy.tools.http_get.allow_domains,
                "deny_private_ips": policy.tools.http_get.deny_private_ips,
                "max_response_bytes": policy.tools.http_get.max_response_bytes,
                "timeout_seconds": policy.tools.http_get.timeout_seconds,
            },
            "shell.run": {
                "allow_executables": policy.tools.shell_run.allow_executables,
                "deny_tokens": policy.tools.shell_run.deny_tokens,
                "timeout_seconds": policy.tools.shell_run.timeout_seconds,
                "max_output_bytes": policy.tools.shell_run.max_output_bytes,
            },
        },
    }


def _build_summary(calls: list, results_by_call: dict) -> dict[str, Any]:
    """Build summary statistics for the report."""
    files_read = []
    files_written = []
    domains = []
    commands = []
    total_duration_ms = 0.0

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

    return {
        "total_duration_ms": total_duration_ms,
        "resources": {
            "files_read": files_read,
            "files_written": files_written,
            "domains_contacted": list(set(domains)),
            "shell_commands": list(set(commands)),
        },
        "counts": {
            "files_read": len(files_read),
            "files_written": len(files_written),
            "unique_domains": len(set(domains)),
            "unique_commands": len(set(commands)),
        },
    }


def _json_serializer(obj: Any) -> Any:
    """Custom JSON serializer for non-standard types."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
