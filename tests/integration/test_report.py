"""
Integration tests for the Report module.

Tests cover:
- JSON report generation
- Console report generation
- Report content verification
"""

import json
import tempfile
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from capsule.engine import Engine
from capsule.report import build_report_dict, generate_console_report, generate_json_report
from capsule.schema import (
    FsPolicy,
    Plan,
    PlanStep,
    Policy,
    ToolPolicies,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield Path(f.name)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def executed_run(temp_db, temp_dir):
    """Execute a plan and return run details."""
    # Create test files
    test_file = temp_dir / "test.txt"
    test_file.write_text("Hello, World!")

    plan = Plan(
        version="1.0",
        name="Test Plan",
        description="A test plan for reporting",
        steps=[
            PlanStep(tool="fs.read", args={"path": str(test_file)}),
        ],
    )

    policy = Policy(
        tools=ToolPolicies(
            fs_read=FsPolicy(allow_paths=[str(temp_dir / "**")]),
        ),
    )

    with Engine(db_path=temp_db, working_dir=temp_dir) as engine:
        result = engine.run(plan, policy)

    return {
        "run_id": result.run_id,
        "db_path": temp_db,
        "temp_dir": temp_dir,
        "plan": plan,
        "result": result,
    }


class TestJsonReport:
    """Tests for JSON report generation."""

    def test_generate_json_report_basic(self, executed_run):
        """Test basic JSON report generation."""
        run_id = executed_run["run_id"]
        db_path = executed_run["db_path"]

        json_str = generate_json_report(run_id, db_path)
        report = json.loads(json_str)

        assert "report_version" in report
        assert report["report_version"] == "1.0"
        assert "generated_at" in report
        assert "run" in report
        assert "plan" in report
        assert "policy" in report
        assert "steps" in report
        assert "summary" in report

    def test_json_report_run_metadata(self, executed_run):
        """Test JSON report contains correct run metadata."""
        run_id = executed_run["run_id"]
        db_path = executed_run["db_path"]

        report = build_report_dict(run_id, db_path)

        assert report["run"]["run_id"] == run_id
        assert report["run"]["status"] == "completed"
        assert report["run"]["mode"] == "run"
        assert "created_at" in report["run"]
        assert "plan_hash" in report["run"]
        assert "policy_hash" in report["run"]

    def test_json_report_statistics(self, executed_run):
        """Test JSON report contains correct statistics."""
        run_id = executed_run["run_id"]
        db_path = executed_run["db_path"]

        report = build_report_dict(run_id, db_path)

        stats = report["run"]["statistics"]
        assert stats["total_steps"] == 1
        assert stats["completed_steps"] == 1
        assert stats["denied_steps"] == 0
        assert stats["failed_steps"] == 0

    def test_json_report_steps(self, executed_run):
        """Test JSON report contains correct step details."""
        run_id = executed_run["run_id"]
        db_path = executed_run["db_path"]

        report = build_report_dict(run_id, db_path)

        assert len(report["steps"]) == 1
        step = report["steps"][0]

        assert step["step_index"] == 0
        assert step["tool_name"] == "fs.read"
        assert "path" in step["args"]
        assert step["result"] is not None
        assert step["result"]["status"] == "success"
        assert step["result"]["output"] is not None

    def test_json_report_timing(self, executed_run):
        """Test JSON report contains timing information."""
        run_id = executed_run["run_id"]
        db_path = executed_run["db_path"]

        report = build_report_dict(run_id, db_path)

        step = report["steps"][0]
        timing = step["result"]["timing"]

        assert "started_at" in timing
        assert "ended_at" in timing
        assert "duration_ms" in timing
        assert timing["duration_ms"] >= 0

    def test_json_report_hashes(self, executed_run):
        """Test JSON report contains hash values."""
        run_id = executed_run["run_id"]
        db_path = executed_run["db_path"]

        report = build_report_dict(run_id, db_path)

        step = report["steps"][0]
        hashes = step["result"]["hashes"]

        assert "input" in hashes
        assert "output" in hashes
        assert len(hashes["input"]) == 64  # SHA256 hex length
        assert len(hashes["output"]) == 64

    def test_json_report_plan_content(self, executed_run):
        """Test JSON report contains plan content."""
        run_id = executed_run["run_id"]
        db_path = executed_run["db_path"]

        report = build_report_dict(run_id, db_path)

        plan = report["plan"]
        assert plan["version"] == "1.0"
        assert plan["name"] == "Test Plan"
        assert plan["description"] == "A test plan for reporting"
        assert len(plan["steps"]) == 1

    def test_json_report_policy_content(self, executed_run):
        """Test JSON report contains policy content."""
        run_id = executed_run["run_id"]
        db_path = executed_run["db_path"]

        report = build_report_dict(run_id, db_path)

        policy = report["policy"]
        assert policy["boundary"] == "deny_by_default"
        assert "tools" in policy
        assert "fs.read" in policy["tools"]

    def test_json_report_summary(self, executed_run):
        """Test JSON report contains summary statistics."""
        run_id = executed_run["run_id"]
        db_path = executed_run["db_path"]

        report = build_report_dict(run_id, db_path)

        summary = report["summary"]
        assert "total_duration_ms" in summary
        assert "resources" in summary
        assert "counts" in summary

        assert summary["counts"]["files_read"] == 1
        assert summary["counts"]["files_written"] == 0

    def test_json_report_nonexistent_run(self, temp_db):
        """Test JSON report for nonexistent run raises error."""
        with pytest.raises(ValueError, match="not found"):
            generate_json_report("nonexistent", temp_db)


class TestConsoleReport:
    """Tests for console report generation."""

    def test_generate_console_report(self, executed_run):
        """Test basic console report generation."""
        run_id = executed_run["run_id"]
        db_path = executed_run["db_path"]

        # Capture console output
        output = StringIO()
        test_console = Console(file=output, force_terminal=True)

        generate_console_report(run_id, db_path, console=test_console)

        output_str = output.getvalue()

        # Verify key elements are present
        assert run_id in output_str
        assert "fs.read" in output_str
        assert "Timeline" in output_str
        assert "Summary" in output_str

    def test_console_report_shows_status(self, executed_run):
        """Test console report shows run status."""
        run_id = executed_run["run_id"]
        db_path = executed_run["db_path"]

        output = StringIO()
        test_console = Console(file=output, force_terminal=True)

        generate_console_report(run_id, db_path, console=test_console)

        output_str = output.getvalue()
        assert "COMPLETED" in output_str

    def test_console_report_verbose_mode(self, executed_run):
        """Test console report verbose mode shows more details."""
        run_id = executed_run["run_id"]
        db_path = executed_run["db_path"]

        # Non-verbose output
        output_normal = StringIO()
        console_normal = Console(file=output_normal, force_terminal=True)
        generate_console_report(run_id, db_path, console=console_normal, verbose=False)

        # Verbose output
        output_verbose = StringIO()
        console_verbose = Console(file=output_verbose, force_terminal=True)
        generate_console_report(run_id, db_path, console=console_verbose, verbose=True)

        # Verbose should include more content
        # (at minimum, same content, potentially more args details)
        assert len(output_verbose.getvalue()) >= len(output_normal.getvalue())

    def test_console_report_nonexistent_run(self, temp_db):
        """Test console report for nonexistent run."""
        output = StringIO()
        test_console = Console(file=output, force_terminal=True)

        generate_console_report("nonexistent", temp_db, console=test_console)

        output_str = output.getvalue()
        assert "not found" in output_str


class TestMultiStepReport:
    """Tests for reports with multiple steps."""

    def test_multi_step_json_report(self, temp_db, temp_dir):
        """Test JSON report for multi-step plan."""
        # Create test files
        file1 = temp_dir / "file1.txt"
        file2 = temp_dir / "file2.txt"
        file1.write_text("Content 1")
        file2.write_text("Content 2")

        plan = Plan(
            version="1.0",
            steps=[
                PlanStep(tool="fs.read", args={"path": str(file1)}),
                PlanStep(tool="fs.read", args={"path": str(file2)}),
            ],
        )

        policy = Policy(
            tools=ToolPolicies(
                fs_read=FsPolicy(allow_paths=[str(temp_dir / "**")]),
            ),
        )

        with Engine(db_path=temp_db, working_dir=temp_dir) as engine:
            result = engine.run(plan, policy)

        report = build_report_dict(result.run_id, temp_db)

        assert len(report["steps"]) == 2
        assert report["summary"]["counts"]["files_read"] == 2


class TestDeniedReport:
    """Tests for reports with denied steps."""

    def test_denied_step_json_report(self, temp_db, temp_dir):
        """Test JSON report for denied step."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("Test content")

        plan = Plan(
            version="1.0",
            steps=[
                PlanStep(tool="fs.read", args={"path": str(test_file)}),
            ],
        )

        # Empty policy denies all
        policy = Policy()

        with Engine(db_path=temp_db, working_dir=temp_dir) as engine:
            result = engine.run(plan, policy)

        report = build_report_dict(result.run_id, temp_db)

        assert report["run"]["statistics"]["denied_steps"] == 1
        step = report["steps"][0]
        assert step["result"]["status"] == "denied"
        assert step["result"]["policy_decision"]["allowed"] is False
        assert step["result"]["policy_decision"]["reason"] is not None
