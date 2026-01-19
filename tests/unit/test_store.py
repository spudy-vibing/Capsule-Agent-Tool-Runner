"""
Unit tests for SQLite storage.

Tests cover:
- Database initialization
- Run operations (create, get, list, update)
- Tool call operations
- Tool result operations
- Hash computation
- Run summaries
"""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from capsule.schema import (
    Plan,
    PlanStep,
    Policy,
    PolicyDecision,
    RunMode,
    RunStatus,
    ToolCallStatus,
)
from capsule.store import CapsuleDB, compute_hash, generate_id


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def temp_db_path() -> Path:
    """Create a temporary database path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield Path(f.name)
    # Cleanup happens automatically


@pytest.fixture
def db(temp_db_path: Path) -> CapsuleDB:
    """Create a database instance."""
    database = CapsuleDB(temp_db_path)
    yield database
    database.close()


@pytest.fixture
def sample_plan() -> Plan:
    """Create a sample plan for testing."""
    return Plan(
        version="1.0",
        name="test-plan",
        steps=[
            PlanStep(tool="fs.read", args={"path": "./file1.txt"}),
            PlanStep(tool="fs.read", args={"path": "./file2.txt"}),
            PlanStep(tool="shell.run", args={"cmd": ["echo", "hello"]}),
        ],
    )


@pytest.fixture
def sample_policy() -> Policy:
    """Create a sample policy for testing."""
    return Policy()


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_generate_id_format(self) -> None:
        """Generated IDs have correct format."""
        id1 = generate_id()
        id2 = generate_id()

        assert len(id1) == 8
        assert len(id2) == 8
        assert id1 != id2  # Should be unique

    def test_compute_hash_string(self) -> None:
        """Hash computation for strings."""
        hash1 = compute_hash("hello")
        hash2 = compute_hash("hello")
        hash3 = compute_hash("world")

        assert hash1 == hash2  # Same input = same hash
        assert hash1 != hash3  # Different input = different hash
        assert len(hash1) == 64  # SHA256 hex length

    def test_compute_hash_dict(self) -> None:
        """Hash computation for dictionaries."""
        hash1 = compute_hash({"a": 1, "b": 2})
        hash2 = compute_hash({"b": 2, "a": 1})  # Same content, different order

        assert hash1 == hash2  # Should be equal (sorted keys)

    def test_compute_hash_none(self) -> None:
        """Hash of None returns empty string."""
        assert compute_hash(None) == ""

    def test_compute_hash_bytes(self) -> None:
        """Hash computation for bytes."""
        hash1 = compute_hash(b"binary data")
        assert len(hash1) == 64


# =============================================================================
# Database Initialization Tests
# =============================================================================


class TestDatabaseInit:
    """Tests for database initialization."""

    def test_create_new_database(self, temp_db_path: Path) -> None:
        """Creating a new database initializes schema."""
        db = CapsuleDB(temp_db_path)
        assert temp_db_path.exists()
        db.close()

    def test_reopen_existing_database(self, temp_db_path: Path) -> None:
        """Can reopen an existing database."""
        db1 = CapsuleDB(temp_db_path)
        db1.close()

        db2 = CapsuleDB(temp_db_path)
        db2.close()

    def test_context_manager(self, temp_db_path: Path) -> None:
        """Database works as context manager."""
        with CapsuleDB(temp_db_path) as db:
            assert db is not None

    def test_in_memory_database(self) -> None:
        """Can create in-memory database."""
        with CapsuleDB(":memory:") as db:
            assert db is not None


# =============================================================================
# Run Operations Tests
# =============================================================================


class TestRunOperations:
    """Tests for run CRUD operations."""

    def test_create_run(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """Create a new run."""
        run_id = db.create_run(sample_plan, sample_policy)

        assert run_id is not None
        assert len(run_id) == 8

    def test_get_run(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """Get a run by ID."""
        run_id = db.create_run(sample_plan, sample_policy)
        run = db.get_run(run_id)

        assert run is not None
        assert run.run_id == run_id
        assert run.status == RunStatus.RUNNING
        assert run.mode == RunMode.RUN
        assert run.total_steps == 3  # sample_plan has 3 steps

    def test_get_nonexistent_run(self, db: CapsuleDB) -> None:
        """Getting nonexistent run returns None."""
        run = db.get_run("nonexistent")
        assert run is None

    def test_list_runs_empty(self, db: CapsuleDB) -> None:
        """List runs when database is empty."""
        runs = db.list_runs()
        assert runs == []

    def test_list_runs(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """List runs returns all runs."""
        run_id1 = db.create_run(sample_plan, sample_policy)
        run_id2 = db.create_run(sample_plan, sample_policy)

        runs = db.list_runs()
        assert len(runs) == 2
        # Most recent first
        assert runs[0].run_id == run_id2
        assert runs[1].run_id == run_id1

    def test_list_runs_limit(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """List runs respects limit."""
        for _ in range(5):
            db.create_run(sample_plan, sample_policy)

        runs = db.list_runs(limit=3)
        assert len(runs) == 3

    def test_update_run_status(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """Update run status."""
        run_id = db.create_run(sample_plan, sample_policy)

        db.update_run_status(
            run_id,
            RunStatus.COMPLETED,
            completed_steps=3,
            denied_steps=0,
            failed_steps=0,
        )

        run = db.get_run(run_id)
        assert run.status == RunStatus.COMPLETED
        assert run.completed_at is not None
        assert run.completed_steps == 3

    def test_update_run_failed(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """Update run to failed status."""
        run_id = db.create_run(sample_plan, sample_policy)

        db.update_run_status(
            run_id,
            RunStatus.FAILED,
            completed_steps=1,
            denied_steps=1,
            failed_steps=1,
        )

        run = db.get_run(run_id)
        assert run.status == RunStatus.FAILED
        assert run.completed_at is not None

    def test_get_run_plan(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """Get the plan for a run."""
        run_id = db.create_run(sample_plan, sample_policy)
        plan = db.get_run_plan(run_id)

        assert plan is not None
        assert plan.name == sample_plan.name
        assert len(plan.steps) == len(sample_plan.steps)

    def test_get_run_policy(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """Get the policy for a run."""
        run_id = db.create_run(sample_plan, sample_policy)
        policy = db.get_run_policy(run_id)

        assert policy is not None
        assert policy.boundary == sample_policy.boundary

    def test_replay_mode(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """Create a run in replay mode."""
        run_id = db.create_run(sample_plan, sample_policy, mode=RunMode.REPLAY)
        run = db.get_run(run_id)

        assert run.mode == RunMode.REPLAY


# =============================================================================
# Tool Call Operations Tests
# =============================================================================


class TestToolCallOperations:
    """Tests for tool call operations."""

    def test_record_call(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """Record a tool call."""
        run_id = db.create_run(sample_plan, sample_policy)
        call_id = db.record_call(
            run_id=run_id,
            step_index=0,
            tool_name="fs.read",
            args={"path": "./file.txt"},
        )

        assert call_id is not None
        assert len(call_id) == 8

    def test_get_calls_for_run(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """Get all calls for a run."""
        run_id = db.create_run(sample_plan, sample_policy)

        db.record_call(run_id, 0, "fs.read", {"path": "./a.txt"})
        db.record_call(run_id, 1, "fs.read", {"path": "./b.txt"})
        db.record_call(run_id, 2, "shell.run", {"cmd": ["echo", "hi"]})

        calls = db.get_calls_for_run(run_id)
        assert len(calls) == 3
        assert calls[0].step_index == 0
        assert calls[1].step_index == 1
        assert calls[2].step_index == 2
        assert calls[0].tool_name == "fs.read"
        assert calls[2].tool_name == "shell.run"

    def test_get_calls_empty(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """Get calls for run with no calls."""
        run_id = db.create_run(sample_plan, sample_policy)
        calls = db.get_calls_for_run(run_id)
        assert calls == []


# =============================================================================
# Tool Result Operations Tests
# =============================================================================


class TestToolResultOperations:
    """Tests for tool result operations."""

    def test_record_result(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """Record a tool result."""
        run_id = db.create_run(sample_plan, sample_policy)
        call_id = db.record_call(run_id, 0, "fs.read", {"path": "./file.txt"})

        now = datetime.now(UTC)
        db.record_result(
            call_id=call_id,
            run_id=run_id,
            status=ToolCallStatus.SUCCESS,
            output="file contents",
            error=None,
            policy_decision=PolicyDecision.allow("allowed"),
            started_at=now,
            ended_at=now,
            input_data={"path": "./file.txt"},
        )

        result = db.get_result_for_call(call_id)
        assert result is not None
        assert result.status == ToolCallStatus.SUCCESS
        assert result.output == "file contents"
        assert result.error is None
        assert result.policy_decision.allowed is True

    def test_record_denied_result(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """Record a denied result."""
        run_id = db.create_run(sample_plan, sample_policy)
        call_id = db.record_call(run_id, 0, "fs.read", {"path": "/etc/passwd"})

        now = datetime.now(UTC)
        db.record_result(
            call_id=call_id,
            run_id=run_id,
            status=ToolCallStatus.DENIED,
            output=None,
            error=None,
            policy_decision=PolicyDecision.deny("path blocked"),
            started_at=now,
            ended_at=now,
            input_data={"path": "/etc/passwd"},
        )

        result = db.get_result_for_call(call_id)
        assert result.status == ToolCallStatus.DENIED
        assert result.policy_decision.allowed is False

    def test_record_error_result(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """Record an error result."""
        run_id = db.create_run(sample_plan, sample_policy)
        call_id = db.record_call(run_id, 0, "fs.read", {"path": "./missing.txt"})

        now = datetime.now(UTC)
        db.record_result(
            call_id=call_id,
            run_id=run_id,
            status=ToolCallStatus.ERROR,
            output=None,
            error="File not found",
            policy_decision=PolicyDecision.allow("allowed"),
            started_at=now,
            ended_at=now,
            input_data={"path": "./missing.txt"},
        )

        result = db.get_result_for_call(call_id)
        assert result.status == ToolCallStatus.ERROR
        assert result.error == "File not found"

    def test_get_results_for_run(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """Get all results for a run."""
        run_id = db.create_run(sample_plan, sample_policy)
        now = datetime.now(UTC)

        for i in range(3):
            call_id = db.record_call(run_id, i, "fs.read", {"path": f"./file{i}.txt"})
            db.record_result(
                call_id=call_id,
                run_id=run_id,
                status=ToolCallStatus.SUCCESS,
                output=f"content {i}",
                error=None,
                policy_decision=PolicyDecision.allow("allowed"),
                started_at=now,
                ended_at=now,
                input_data={"path": f"./file{i}.txt"},
            )

        results = db.get_results_for_run(run_id)
        assert len(results) == 3

    def test_result_hashes(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """Results have input/output hashes."""
        run_id = db.create_run(sample_plan, sample_policy)
        call_id = db.record_call(run_id, 0, "fs.read", {"path": "./file.txt"})

        now = datetime.now(UTC)
        db.record_result(
            call_id=call_id,
            run_id=run_id,
            status=ToolCallStatus.SUCCESS,
            output="output data",
            error=None,
            policy_decision=PolicyDecision.allow("allowed"),
            started_at=now,
            ended_at=now,
            input_data={"path": "./file.txt"},
        )

        result = db.get_result_for_call(call_id)
        assert len(result.input_hash) == 64
        assert len(result.output_hash) == 64


# =============================================================================
# Run Summary Tests
# =============================================================================


class TestRunSummary:
    """Tests for run summary functionality."""

    def test_get_run_summary(
        self,
        db: CapsuleDB,
        sample_plan: Plan,
        sample_policy: Policy,
    ) -> None:
        """Get a complete run summary."""
        run_id = db.create_run(sample_plan, sample_policy)
        now = datetime.now(UTC)

        # Record all calls and results
        for i, step in enumerate(sample_plan.steps):
            call_id = db.record_call(run_id, i, step.tool, step.args)
            db.record_result(
                call_id=call_id,
                run_id=run_id,
                status=ToolCallStatus.SUCCESS,
                output=f"result {i}",
                error=None,
                policy_decision=PolicyDecision.allow("allowed"),
                started_at=now,
                ended_at=now,
                input_data=step.args,
            )

        db.update_run_status(run_id, RunStatus.COMPLETED, completed_steps=3)

        summary = db.get_run_summary(run_id)
        assert summary is not None
        assert summary["run_id"] == run_id
        assert summary["status"] == "completed"
        assert len(summary["steps"]) == 3
        assert summary["steps"][0]["tool"] == "fs.read"
        assert summary["steps"][0]["status"] == "success"

    def test_get_summary_nonexistent(self, db: CapsuleDB) -> None:
        """Get summary for nonexistent run returns None."""
        summary = db.get_run_summary("nonexistent")
        assert summary is None
