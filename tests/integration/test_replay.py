"""
Integration tests for the Replay Engine.

Tests cover:
- Basic replay functionality
- Plan verification
- Mismatch detection
- Data integrity verification
"""

import tempfile
from pathlib import Path

import pytest

from capsule.engine import Engine
from capsule.replay import ReplayEngine
from capsule.schema import (
    Plan,
    PlanStep,
    Policy,
    RunMode,
    RunStatus,
    ToolCallStatus,
    ToolPolicies,
    FsPolicy,
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
def simple_plan(temp_dir):
    """Create a simple plan for testing."""
    # Create a test file
    test_file = temp_dir / "test.txt"
    test_file.write_text("Hello, World!")

    return Plan(
        version="1.0",
        steps=[
            PlanStep(tool="fs.read", args={"path": str(test_file)}),
        ],
    )


@pytest.fixture
def permissive_policy(temp_dir):
    """Create a permissive policy for testing."""
    return Policy(
        tools=ToolPolicies(
            fs_read=FsPolicy(allow_paths=[str(temp_dir / "**")]),
            fs_write=FsPolicy(allow_paths=[str(temp_dir / "**")]),
        ),
    )


class TestReplayBasic:
    """Basic replay functionality tests."""

    def test_replay_successful_run(self, temp_db, temp_dir, simple_plan, permissive_policy):
        """Test replaying a successful run returns same results."""
        # Execute the plan first
        with Engine(db_path=temp_db, working_dir=temp_dir) as engine:
            run_result = engine.run(simple_plan, permissive_policy)
            original_run_id = run_result.run_id

        assert run_result.status == RunStatus.COMPLETED
        assert run_result.completed_steps == 1

        # Replay the run
        with ReplayEngine(db_path=temp_db) as replay_engine:
            replay_result = replay_engine.replay(original_run_id)

        assert replay_result.status == RunStatus.COMPLETED
        assert replay_result.original_run_id == original_run_id
        assert replay_result.total_steps == 1
        assert replay_result.completed_steps == 1
        assert len(replay_result.mismatches) == 0
        assert replay_result.success

    def test_replay_creates_new_run_record(self, temp_db, temp_dir, simple_plan, permissive_policy):
        """Test that replay creates a new run record with mode='replay'."""
        # Execute the plan first
        with Engine(db_path=temp_db, working_dir=temp_dir) as engine:
            run_result = engine.run(simple_plan, permissive_policy)
            original_run_id = run_result.run_id

        # Replay the run
        with ReplayEngine(db_path=temp_db) as replay_engine:
            replay_result = replay_engine.replay(original_run_id)
            replay_run_id = replay_result.replay_run_id

        # Verify replay created new run record
        with Engine(db_path=temp_db) as engine:
            runs = engine.list_runs()

        assert len(runs) == 2

        # Find the replay run
        replay_run = next((r for r in runs if r["run_id"] == replay_run_id), None)
        assert replay_run is not None
        assert replay_run["mode"] == "replay"

    def test_replay_returns_stored_output(self, temp_db, temp_dir, simple_plan, permissive_policy):
        """Test that replay returns the exact stored output."""
        # Execute the plan first
        with Engine(db_path=temp_db, working_dir=temp_dir) as engine:
            run_result = engine.run(simple_plan, permissive_policy)
            original_run_id = run_result.run_id
            original_output = run_result.steps[0].output

        # Modify the file (shouldn't affect replay)
        test_file = Path(simple_plan.steps[0].args["path"])
        test_file.write_text("Modified content!")

        # Replay the run
        with ReplayEngine(db_path=temp_db) as replay_engine:
            replay_result = replay_engine.replay(original_run_id)

        # Should still return original output, not modified content
        assert replay_result.steps[0].output == original_output
        assert "Hello, World!" in str(replay_result.steps[0].output)

    def test_replay_nonexistent_run(self, temp_db):
        """Test replaying a nonexistent run raises error."""
        from capsule.errors import ReplayRunNotFoundError

        with ReplayEngine(db_path=temp_db) as replay_engine:
            with pytest.raises(ReplayRunNotFoundError):
                replay_engine.replay("nonexistent")


class TestReplayMultiStep:
    """Tests for multi-step plan replays."""

    def test_replay_multi_step_plan(self, temp_db, temp_dir):
        """Test replaying a multi-step plan."""
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

        # Execute the plan
        with Engine(db_path=temp_db, working_dir=temp_dir) as engine:
            run_result = engine.run(plan, policy)
            original_run_id = run_result.run_id

        assert run_result.completed_steps == 2

        # Replay
        with ReplayEngine(db_path=temp_db) as replay_engine:
            replay_result = replay_engine.replay(original_run_id)

        assert replay_result.total_steps == 2
        assert replay_result.completed_steps == 2
        assert replay_result.success


class TestReplayWithDenials:
    """Tests for replaying runs with policy denials."""

    def test_replay_denied_run(self, temp_db, temp_dir):
        """Test replaying a run where steps were denied."""
        # Create a test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("Test content")

        plan = Plan(
            version="1.0",
            steps=[
                PlanStep(tool="fs.read", args={"path": str(test_file)}),
            ],
        )

        # Use empty policy - will deny all
        policy = Policy()

        # Execute the plan (will be denied)
        with Engine(db_path=temp_db, working_dir=temp_dir) as engine:
            run_result = engine.run(plan, policy)
            original_run_id = run_result.run_id

        assert run_result.denied_steps == 1

        # Replay - should return same denial
        with ReplayEngine(db_path=temp_db) as replay_engine:
            replay_result = replay_engine.replay(original_run_id)

        assert replay_result.denied_steps == 1
        assert replay_result.steps[0].status == ToolCallStatus.DENIED


class TestReplayVerification:
    """Tests for replay verification features."""

    def test_verify_run_integrity(self, temp_db, temp_dir, simple_plan, permissive_policy):
        """Test verifying run integrity."""
        # Execute the plan
        with Engine(db_path=temp_db, working_dir=temp_dir) as engine:
            run_result = engine.run(simple_plan, permissive_policy)
            run_id = run_result.run_id

        # Verify integrity
        with ReplayEngine(db_path=temp_db) as replay_engine:
            verification = replay_engine.verify_run(run_id)

        assert verification["valid"] is True
        assert len(verification["errors"]) == 0
        assert verification["stats"]["run_id"] == run_id
        assert verification["stats"]["total_calls"] == 1
        assert verification["stats"]["total_results"] == 1

    def test_verify_nonexistent_run(self, temp_db):
        """Test verifying a nonexistent run."""
        with ReplayEngine(db_path=temp_db) as replay_engine:
            verification = replay_engine.verify_run("nonexistent")

        assert verification["valid"] is False
        assert "not found" in verification["errors"][0]


class TestReplayPlanVerification:
    """Tests for plan hash verification during replay."""

    def test_replay_with_matching_plan(self, temp_db, temp_dir, simple_plan, permissive_policy):
        """Test replay with matching plan hash."""
        # Execute
        with Engine(db_path=temp_db, working_dir=temp_dir) as engine:
            run_result = engine.run(simple_plan, permissive_policy)
            original_run_id = run_result.run_id

        # Replay with same plan
        with ReplayEngine(db_path=temp_db) as replay_engine:
            replay_result = replay_engine.replay(
                original_run_id, verify_plan=True, plan=simple_plan
            )

        assert replay_result.plan_verified is True
        assert len(replay_result.mismatches) == 0

    def test_replay_with_different_plan(self, temp_db, temp_dir, simple_plan, permissive_policy):
        """Test replay detects different plan."""
        # Execute
        with Engine(db_path=temp_db, working_dir=temp_dir) as engine:
            run_result = engine.run(simple_plan, permissive_policy)
            original_run_id = run_result.run_id

        # Create a different plan
        different_plan = Plan(
            version="1.0",
            steps=[
                PlanStep(tool="fs.read", args={"path": "/different/path"}),
            ],
        )

        # Replay with different plan
        with ReplayEngine(db_path=temp_db) as replay_engine:
            replay_result = replay_engine.replay(
                original_run_id, verify_plan=True, plan=different_plan
            )

        assert replay_result.plan_verified is False
        assert any("hash mismatch" in m for m in replay_result.mismatches)

    def test_replay_without_verification(self, temp_db, temp_dir, simple_plan, permissive_policy):
        """Test replay without plan verification."""
        # Execute
        with Engine(db_path=temp_db, working_dir=temp_dir) as engine:
            run_result = engine.run(simple_plan, permissive_policy)
            original_run_id = run_result.run_id

        # Create a different plan
        different_plan = Plan(
            version="1.0",
            steps=[
                PlanStep(tool="fs.read", args={"path": "/different/path"}),
            ],
        )

        # Replay with verify_plan=False should still work
        with ReplayEngine(db_path=temp_db) as replay_engine:
            replay_result = replay_engine.replay(
                original_run_id, verify_plan=False, plan=different_plan
            )

        # Should succeed even with different plan
        assert replay_result.plan_verified is True  # Verification wasn't performed


class TestReplayContextManager:
    """Tests for ReplayEngine context manager."""

    def test_context_manager(self, temp_db):
        """Test ReplayEngine as context manager."""
        with ReplayEngine(db_path=temp_db) as engine:
            assert engine.db is not None

        # After context exits, connection should be closed
        assert engine.db._conn is None
