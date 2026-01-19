"""
Integration tests for the Capsule Engine.

Tests cover:
- End-to-end plan execution
- Policy enforcement during execution
- Error handling and recovery
- Run status tracking
- Result storage and retrieval
"""

import tempfile
from pathlib import Path

import pytest

from capsule.engine import Engine
from capsule.schema import (
    FsPolicy,
    Plan,
    PlanStep,
    Policy,
    RunStatus,
    ToolCallStatus,
    ToolPolicies,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def temp_dir() -> Path:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def engine(temp_dir: Path) -> Engine:
    """Create an engine with temporary database."""
    db_path = temp_dir / "test.db"
    eng = Engine(db_path=db_path, working_dir=temp_dir)
    yield eng
    eng.close()


@pytest.fixture
def permissive_fs_policy(temp_dir: Path) -> Policy:
    """Create a policy that allows fs operations in temp dir."""
    return Policy(
        tools=ToolPolicies(
            **{
                "fs.read": FsPolicy(
                    allow_paths=[f"{temp_dir}/**"],
                    allow_hidden=False,
                ),
                "fs.write": FsPolicy(
                    allow_paths=[f"{temp_dir}/**"],
                    allow_hidden=False,
                ),
            }
        )
    )




# =============================================================================
# Basic Execution Tests
# =============================================================================


class TestBasicExecution:
    """Tests for basic plan execution."""

    def test_execute_single_step_plan(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Execute a single step plan successfully."""
        # Create a test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("hello world")

        plan = Plan(
            steps=[
                PlanStep(tool="fs.read", args={"path": str(test_file)}),
            ]
        )

        result = engine.run(plan, permissive_fs_policy)

        assert result.status == RunStatus.COMPLETED
        assert result.success is True
        assert result.total_steps == 1
        assert result.completed_steps == 1
        assert result.denied_steps == 0
        assert result.failed_steps == 0
        assert len(result.steps) == 1
        assert result.steps[0].status == ToolCallStatus.SUCCESS
        assert result.steps[0].output == "hello world"

    def test_execute_multi_step_plan(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Execute a multi-step plan successfully."""
        # Create test files
        file1 = temp_dir / "file1.txt"
        file2 = temp_dir / "file2.txt"
        file1.write_text("content 1")
        file2.write_text("content 2")

        plan = Plan(
            steps=[
                PlanStep(tool="fs.read", args={"path": str(file1)}),
                PlanStep(tool="fs.read", args={"path": str(file2)}),
            ]
        )

        result = engine.run(plan, permissive_fs_policy)

        assert result.status == RunStatus.COMPLETED
        assert result.success is True
        assert result.total_steps == 2
        assert result.completed_steps == 2
        assert len(result.steps) == 2
        assert result.steps[0].output == "content 1"
        assert result.steps[1].output == "content 2"

    def test_execute_fs_write_plan(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Execute a plan that writes files."""
        output_file = temp_dir / "output.txt"

        plan = Plan(
            steps=[
                PlanStep(
                    tool="fs.write",
                    args={"path": str(output_file), "content": "written content"},
                ),
            ]
        )

        result = engine.run(plan, permissive_fs_policy)

        assert result.status == RunStatus.COMPLETED
        assert result.success is True
        assert output_file.exists()
        assert output_file.read_text() == "written content"

    def test_execute_write_then_read(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Execute a plan that writes then reads a file."""
        output_file = temp_dir / "output.txt"

        plan = Plan(
            steps=[
                PlanStep(
                    tool="fs.write",
                    args={"path": str(output_file), "content": "written content"},
                ),
                PlanStep(
                    tool="fs.read",
                    args={"path": str(output_file)},
                ),
            ]
        )

        result = engine.run(plan, permissive_fs_policy)

        assert result.status == RunStatus.COMPLETED
        assert result.success is True
        assert result.steps[1].output == "written content"


# =============================================================================
# Policy Denial Tests
# =============================================================================


class TestPolicyDenials:
    """Tests for policy denial handling."""

    def test_deny_path_outside_allowed(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Deny access to paths outside allowed patterns."""
        plan = Plan(
            steps=[
                PlanStep(tool="fs.read", args={"path": "/etc/passwd"}),
            ]
        )

        result = engine.run(plan, permissive_fs_policy)

        assert result.status == RunStatus.FAILED
        assert result.success is False
        assert result.denied_steps == 1
        assert result.steps[0].status == ToolCallStatus.DENIED
        assert result.steps[0].policy_decision.allowed is False

    def test_deny_hidden_files(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Deny access to hidden files when not allowed."""
        hidden_file = temp_dir / ".hidden"
        hidden_file.write_text("secret")

        plan = Plan(
            steps=[
                PlanStep(tool="fs.read", args={"path": str(hidden_file)}),
            ]
        )

        result = engine.run(plan, permissive_fs_policy)

        assert result.status == RunStatus.FAILED
        assert result.denied_steps == 1
        assert result.steps[0].status == ToolCallStatus.DENIED

    def test_fail_fast_stops_on_denial(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Fail-fast mode stops execution on first denial."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        plan = Plan(
            steps=[
                PlanStep(tool="fs.read", args={"path": "/etc/passwd"}),  # Denied
                PlanStep(tool="fs.read", args={"path": str(test_file)}),  # Would succeed
            ]
        )

        result = engine.run(plan, permissive_fs_policy, fail_fast=True)

        assert result.status == RunStatus.FAILED
        assert len(result.steps) == 1  # Only first step executed
        assert result.denied_steps == 1

    def test_continue_on_denial_without_fail_fast(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Without fail-fast, continue after denial."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        plan = Plan(
            steps=[
                PlanStep(tool="fs.read", args={"path": "/etc/passwd"}),  # Denied
                PlanStep(tool="fs.read", args={"path": str(test_file)}),  # Succeeds
            ]
        )

        result = engine.run(plan, permissive_fs_policy, fail_fast=False)

        assert result.status == RunStatus.FAILED  # Still failed overall
        assert len(result.steps) == 2  # Both steps executed
        assert result.denied_steps == 1
        assert result.completed_steps == 1
        assert result.steps[1].status == ToolCallStatus.SUCCESS


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling during execution."""

    def test_handle_file_not_found(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Handle file not found errors gracefully."""
        plan = Plan(
            steps=[
                PlanStep(tool="fs.read", args={"path": str(temp_dir / "missing.txt")}),
            ]
        )

        result = engine.run(plan, permissive_fs_policy)

        assert result.status == RunStatus.FAILED
        assert result.failed_steps == 1
        assert result.steps[0].status == ToolCallStatus.ERROR
        assert result.steps[0].error is not None

    def test_handle_unknown_tool_denied(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Unknown tools are denied by policy (before tool lookup)."""
        plan = Plan(
            steps=[
                PlanStep(tool="unknown.tool", args={}),
            ]
        )

        result = engine.run(plan, permissive_fs_policy)

        assert result.status == RunStatus.FAILED
        # Unknown tools are denied by policy, not "tool not found" error
        assert result.denied_steps == 1
        assert result.steps[0].status == ToolCallStatus.DENIED
        assert "unknown tool" in result.steps[0].policy_decision.reason.lower()

    def test_fail_fast_stops_on_error(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Fail-fast mode stops execution on first error."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        plan = Plan(
            steps=[
                PlanStep(tool="fs.read", args={"path": str(temp_dir / "missing.txt")}),
                PlanStep(tool="fs.read", args={"path": str(test_file)}),
            ]
        )

        result = engine.run(plan, permissive_fs_policy, fail_fast=True)

        assert result.status == RunStatus.FAILED
        assert len(result.steps) == 1
        assert result.failed_steps == 1


# =============================================================================
# Storage Integration Tests
# =============================================================================


class TestStorageIntegration:
    """Tests for storage integration."""

    def test_run_is_recorded(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Runs are recorded in the database."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        plan = Plan(
            steps=[
                PlanStep(tool="fs.read", args={"path": str(test_file)}),
            ]
        )

        result = engine.run(plan, permissive_fs_policy)

        # Verify run is in database
        runs = engine.list_runs()
        assert len(runs) == 1
        assert runs[0]["run_id"] == result.run_id

    def test_run_summary_available(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Run summary is available after execution."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        plan = Plan(
            steps=[
                PlanStep(tool="fs.read", args={"path": str(test_file)}),
            ]
        )

        result = engine.run(plan, permissive_fs_policy)
        summary = engine.get_run_summary(result.run_id)

        assert summary is not None
        assert summary["run_id"] == result.run_id
        assert summary["status"] == "completed"
        assert len(summary["steps"]) == 1

    def test_multiple_runs_tracked(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Multiple runs are tracked independently."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        plan = Plan(
            steps=[
                PlanStep(tool="fs.read", args={"path": str(test_file)}),
            ]
        )

        result1 = engine.run(plan, permissive_fs_policy)
        result2 = engine.run(plan, permissive_fs_policy)

        assert result1.run_id != result2.run_id

        runs = engine.list_runs()
        assert len(runs) == 2


# =============================================================================
# Context Manager Tests
# =============================================================================


class TestContextManager:
    """Tests for context manager usage."""

    def test_engine_as_context_manager(self, temp_dir: Path) -> None:
        """Engine works as context manager."""
        db_path = temp_dir / "test.db"

        with Engine(db_path=db_path, working_dir=temp_dir) as engine:
            assert engine is not None

    def test_run_in_context_manager(
        self,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Can run plans within context manager."""
        db_path = temp_dir / "test.db"
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        plan = Plan(
            steps=[
                PlanStep(tool="fs.read", args={"path": str(test_file)}),
            ]
        )

        with Engine(db_path=db_path, working_dir=temp_dir) as engine:
            result = engine.run(plan, permissive_fs_policy)
            assert result.success is True


# =============================================================================
# RunResult Property Tests
# =============================================================================


class TestRunResultProperties:
    """Tests for RunResult properties."""

    def test_success_property_true(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Success is True when all steps complete."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        plan = Plan(
            steps=[
                PlanStep(tool="fs.read", args={"path": str(test_file)}),
            ]
        )

        result = engine.run(plan, permissive_fs_policy)
        assert result.success is True

    def test_success_property_false_on_denial(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Success is False when steps are denied."""
        plan = Plan(
            steps=[
                PlanStep(tool="fs.read", args={"path": "/etc/passwd"}),
            ]
        )

        result = engine.run(plan, permissive_fs_policy)
        assert result.success is False

    def test_success_property_false_on_error(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Success is False when steps error."""
        plan = Plan(
            steps=[
                PlanStep(tool="fs.read", args={"path": str(temp_dir / "missing.txt")}),
            ]
        )

        result = engine.run(plan, permissive_fs_policy)
        assert result.success is False

    def test_duration_is_recorded(
        self,
        engine: Engine,
        temp_dir: Path,
        permissive_fs_policy: Policy,
    ) -> None:
        """Duration is recorded for runs and steps."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        plan = Plan(
            steps=[
                PlanStep(tool="fs.read", args={"path": str(test_file)}),
            ]
        )

        result = engine.run(plan, permissive_fs_policy)

        assert result.duration_ms > 0
        assert result.steps[0].duration_ms > 0
