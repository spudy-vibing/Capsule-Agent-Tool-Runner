"""
Tests for report coverage gaps:
- Console and JSON reports with fs.write, http.get, shell.run tool types
- JSON serializer edge cases (datetime, Pydantic models)
- Report status rendering for RUNNING and denied steps
"""

import io
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from rich.console import Console

from capsule.engine import Engine
from capsule.report.json import generate_json_report, build_report_dict
from capsule.report.console import generate_console_report
from capsule.schema import load_plan, load_policy


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def db_path(temp_dir):
    return temp_dir / "test.db"


def _create_run(temp_dir, db_path, steps, policy_tools):
    """Helper: create a run and return run_id."""
    plan = {"version": "1.0", "steps": steps}
    plan_path = temp_dir / "plan.yaml"
    plan_path.write_text(yaml.dump(plan))

    policy = {"boundary": "deny_by_default", "tools": policy_tools}
    policy_path = temp_dir / "policy.yaml"
    policy_path.write_text(yaml.dump(policy))

    p = load_plan(plan_path)
    pol = load_policy(policy_path)

    with Engine(db_path=db_path, working_dir=temp_dir) as engine:
        result = engine.run(p, pol, fail_fast=False)

    return result.run_id


def _capture_console_report(run_id, db_path):
    """Capture console report output as a string."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=200)
    generate_console_report(run_id, str(db_path), console=console)
    return buf.getvalue()


class TestReportWithShellTool:
    def test_json_report_shell_run(self, temp_dir, db_path):
        """JSON report includes shell.run tool results."""
        run_id = _create_run(
            temp_dir, db_path,
            steps=[{"tool": "shell.run", "args": {"cmd": ["echo", "hello"]}}],
            policy_tools={
                "shell.run": {
                    "allow_executables": ["echo"],
                    "timeout_seconds": 10,
                },
            },
        )

        report = build_report_dict(run_id, str(db_path))
        assert report is not None
        assert len(report["steps"]) == 1
        assert report["steps"][0]["tool_name"] == "shell.run"
        assert report["steps"][0]["result"]["status"] == "success"

    def test_console_report_shell_run(self, temp_dir, db_path):
        """Console report renders shell.run steps."""
        run_id = _create_run(
            temp_dir, db_path,
            steps=[{"tool": "shell.run", "args": {"cmd": ["echo", "hello"]}}],
            policy_tools={
                "shell.run": {
                    "allow_executables": ["echo"],
                    "timeout_seconds": 10,
                },
            },
        )

        output = _capture_console_report(run_id, db_path)
        assert "shell.run" in output


class TestReportWithWriteTool:
    def test_json_report_fs_write(self, temp_dir, db_path):
        """JSON report includes fs.write steps."""
        output_file = str(temp_dir / "output.txt")
        run_id = _create_run(
            temp_dir, db_path,
            steps=[{"tool": "fs.write", "args": {"path": output_file, "content": "test"}}],
            policy_tools={
                "fs.write": {
                    "allow_paths": [str(temp_dir / "**")],
                    "max_size_bytes": 1048576,
                },
            },
        )

        report = build_report_dict(run_id, str(db_path))
        assert report["steps"][0]["tool_name"] == "fs.write"
        # Summary should track files written
        assert report["summary"]["counts"]["files_written"] >= 1

    def test_console_report_fs_write(self, temp_dir, db_path):
        """Console report renders fs.write steps."""
        output_file = str(temp_dir / "output.txt")
        run_id = _create_run(
            temp_dir, db_path,
            steps=[{"tool": "fs.write", "args": {"path": output_file, "content": "test"}}],
            policy_tools={
                "fs.write": {
                    "allow_paths": [str(temp_dir / "**")],
                    "max_size_bytes": 1048576,
                },
            },
        )

        output = _capture_console_report(run_id, db_path)
        assert "fs.write" in output


class TestReportWithDeniedSteps:
    def test_json_report_denied_step(self, temp_dir, db_path):
        """JSON report correctly shows denied steps."""
        run_id = _create_run(
            temp_dir, db_path,
            steps=[{"tool": "fs.read", "args": {"path": "/etc/passwd"}}],
            policy_tools={},  # Deny everything
        )

        report = build_report_dict(run_id, str(db_path))
        assert report["steps"][0]["result"]["status"] == "denied"
        assert report["steps"][0]["result"]["policy_decision"]["allowed"] is False

    def test_console_report_denied_step(self, temp_dir, db_path):
        """Console report renders denied status."""
        run_id = _create_run(
            temp_dir, db_path,
            steps=[{"tool": "fs.read", "args": {"path": "/etc/passwd"}}],
            policy_tools={},
        )

        output = _capture_console_report(run_id, db_path)
        # The denied icon (⊘) or word "denied" should appear
        assert "denied" in output.lower() or "\u2298" in output


class TestReportWithMultipleToolTypes:
    def test_json_report_mixed_tools(self, temp_dir, db_path):
        """JSON report handles a run with multiple tool types."""
        (temp_dir / "readme.txt").write_text("Hello")
        output_file = str(temp_dir / "out.txt")

        run_id = _create_run(
            temp_dir, db_path,
            steps=[
                {"tool": "fs.read", "args": {"path": str(temp_dir / "readme.txt")}},
                {"tool": "fs.write", "args": {"path": output_file, "content": "result"}},
                {"tool": "shell.run", "args": {"cmd": ["echo", "done"]}},
            ],
            policy_tools={
                "fs.read": {"allow_paths": [str(temp_dir / "**")]},
                "fs.write": {"allow_paths": [str(temp_dir / "**")], "max_size_bytes": 1048576},
                "shell.run": {"allow_executables": ["echo"], "timeout_seconds": 10},
            },
        )

        report = build_report_dict(run_id, str(db_path))
        tools_used = [s["tool_name"] for s in report["steps"]]
        assert "fs.read" in tools_used
        assert "fs.write" in tools_used
        assert "shell.run" in tools_used
        assert report["summary"]["counts"]["files_read"] >= 1
        assert report["summary"]["counts"]["files_written"] >= 1

    def test_console_report_mixed_tools(self, temp_dir, db_path):
        """Console report handles mixed tool types."""
        (temp_dir / "readme.txt").write_text("Hello")

        run_id = _create_run(
            temp_dir, db_path,
            steps=[
                {"tool": "fs.read", "args": {"path": str(temp_dir / "readme.txt")}},
                {"tool": "shell.run", "args": {"cmd": ["echo", "hi"]}},
            ],
            policy_tools={
                "fs.read": {"allow_paths": [str(temp_dir / "**")]},
                "shell.run": {"allow_executables": ["echo"], "timeout_seconds": 10},
            },
        )

        output = _capture_console_report(run_id, db_path)
        assert "fs.read" in output
        assert "shell.run" in output


class TestJsonSerializer:
    def test_datetime_serialization(self):
        """JSON report serializes datetime objects correctly."""
        from capsule.report.json import _json_serializer

        dt = datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC)
        result = _json_serializer(dt)
        assert "2025" in result
        assert "10:30" in result

    def test_unsupported_type_raises(self):
        """JSON serializer raises TypeError for unsupported types."""
        from capsule.report.json import _json_serializer

        with pytest.raises(TypeError):
            _json_serializer(object())
