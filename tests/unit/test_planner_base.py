"""
Tests for the planner base module.

Tests:
    - PlannerState dataclass
    - Done sentinel
    - Planner ABC interface
"""

from datetime import UTC, datetime

import pytest

from capsule.planner.base import Done, Planner, PlannerState
from capsule.schema import PolicyDecision, ToolCall, ToolCallStatus, ToolResult


def make_tool_result(
    call_id: str,
    run_id: str,
    status: ToolCallStatus,
    output=None,
    error=None,
) -> ToolResult:
    """Helper to create a ToolResult with all required fields."""
    now = datetime.now(UTC)
    return ToolResult(
        call_id=call_id,
        run_id=run_id,
        status=status,
        output=output,
        error=error,
        policy_decision=PolicyDecision(allowed=status == ToolCallStatus.SUCCESS, reason="test"),
        started_at=now,
        ended_at=now,
        input_hash="test_input_hash",
        output_hash="test_output_hash",
    )


class TestPlannerState:
    """Tests for PlannerState dataclass."""

    def test_create_minimal_state(self):
        """Test creating a state with minimal required fields."""
        state = PlannerState(
            task="List files",
            tool_schemas=[],
            policy_summary="Read-only",
            history=[],
            iteration=0,
        )
        assert state.task == "List files"
        assert state.tool_schemas == []
        assert state.policy_summary == "Read-only"
        assert state.history == []
        assert state.iteration == 0
        assert state.metadata == {}

    def test_create_state_with_tool_schemas(self):
        """Test creating a state with tool schemas."""
        schemas = [
            {"name": "fs.read", "description": "Read file", "args": {"path": {"type": "string"}}},
            {"name": "fs.write", "description": "Write file", "args": {"path": {"type": "string"}}},
        ]
        state = PlannerState(
            task="Read and modify config",
            tool_schemas=schemas,
            policy_summary="Can read/write ./config",
            history=[],
            iteration=0,
        )
        assert len(state.tool_schemas) == 2
        assert state.tool_schemas[0]["name"] == "fs.read"

    def test_create_state_with_history(self):
        """Test creating a state with execution history."""
        call = ToolCall(
            call_id="call-1",
            run_id="run-1",
            step_index=0,
            tool_name="fs.read",
            args={"path": "/etc/passwd"},
        )
        result = make_tool_result(
            call_id="call-1",
            run_id="run-1",
            status=ToolCallStatus.SUCCESS,
            output="root:x:0:0:...",
        )
        history = [(call, result)]

        state = PlannerState(
            task="Check users",
            tool_schemas=[],
            policy_summary="Read /etc",
            history=history,
            iteration=1,
        )
        assert len(state.history) == 1
        assert state.history[0][0].tool_name == "fs.read"
        assert state.history[0][1].status == ToolCallStatus.SUCCESS

    def test_create_state_with_metadata(self):
        """Test creating a state with custom metadata."""
        state = PlannerState(
            task="Debug task",
            tool_schemas=[],
            policy_summary="Full access",
            history=[],
            iteration=0,
            metadata={"debug": True, "user": "test"},
        )
        assert state.metadata["debug"] is True
        assert state.metadata["user"] == "test"

    def test_state_iteration_tracking(self):
        """Test that iteration is properly tracked."""
        state = PlannerState(
            task="Multi-step task",
            tool_schemas=[],
            policy_summary="",
            history=[],
            iteration=5,
        )
        assert state.iteration == 5


class TestDone:
    """Tests for Done sentinel class."""

    def test_create_done_minimal(self):
        """Test creating a Done with minimal fields."""
        done = Done()
        assert done.final_output is None
        assert done.reason == "task_complete"

    def test_create_done_with_output(self):
        """Test creating a Done with final output."""
        done = Done(final_output="Files copied successfully")
        assert done.final_output == "Files copied successfully"
        assert done.reason == "task_complete"

    def test_create_done_with_dict_output(self):
        """Test creating a Done with dict output."""
        output = {"files_copied": 5, "total_size": 1024}
        done = Done(final_output=output)
        assert done.final_output == output
        assert done.final_output["files_copied"] == 5

    def test_create_done_with_custom_reason(self):
        """Test creating a Done with custom reason."""
        done = Done(reason="cannot_proceed")
        assert done.reason == "cannot_proceed"

    def test_create_done_full(self):
        """Test creating a Done with all fields."""
        done = Done(
            final_output="Completed with warnings",
            reason="partial_success",
        )
        assert done.final_output == "Completed with warnings"
        assert done.reason == "partial_success"

    def test_done_is_truthy(self):
        """Test that Done instances are truthy (for isinstance checks)."""
        done = Done()
        assert done  # Should be truthy

    def test_done_equality(self):
        """Test Done equality comparison."""
        done1 = Done(reason="task_complete")
        done2 = Done(reason="task_complete")
        done3 = Done(reason="cannot_proceed")

        assert done1 == done2
        assert done1 != done3


class TestPlannerABC:
    """Tests for the Planner abstract base class."""

    def test_cannot_instantiate_directly(self):
        """Test that Planner cannot be instantiated directly."""
        with pytest.raises(TypeError, match="abstract"):
            Planner()

    def test_subclass_must_implement_propose_next(self):
        """Test that subclasses must implement propose_next."""

        class IncompletePlanner(Planner):
            pass

        with pytest.raises(TypeError, match="abstract"):
            IncompletePlanner()

    def test_subclass_with_propose_next(self):
        """Test that a complete subclass can be instantiated."""

        class SimplePlanner(Planner):
            def propose_next(self, state, last_result):
                return Done(reason="test")

        planner = SimplePlanner()
        assert planner is not None

    def test_finalize_default_implementation(self):
        """Test that finalize has a default implementation."""

        class MinimalPlanner(Planner):
            def propose_next(self, state, last_result):
                return Done()

        planner = MinimalPlanner()
        state = PlannerState(
            task="Test",
            tool_schemas=[],
            policy_summary="",
            history=[],
            iteration=0,
        )
        done = Done(final_output="result")

        # Default finalize should return None
        result = planner.finalize(state, done)
        assert result is None

    def test_custom_finalize_implementation(self):
        """Test that finalize can be overridden."""

        class CustomPlanner(Planner):
            def propose_next(self, state, last_result):
                return Done()

            def finalize(self, state, done):
                return {"task": state.task, "iterations": state.iteration}

        planner = CustomPlanner()
        state = PlannerState(
            task="Custom task",
            tool_schemas=[],
            policy_summary="",
            history=[],
            iteration=3,
        )
        done = Done()

        result = planner.finalize(state, done)
        assert result == {"task": "Custom task", "iterations": 3}

    def test_propose_next_returns_tool_call(self):
        """Test that propose_next can return a ToolCall."""

        class ToolCallingPlanner(Planner):
            def propose_next(self, state, last_result):
                return ToolCall(
                    call_id="call-1",
                    run_id="run-1",
                    step_index=state.iteration,
                    tool_name="fs.read",
                    args={"path": "/test"},
                )

        planner = ToolCallingPlanner()
        state = PlannerState(
            task="Read file",
            tool_schemas=[],
            policy_summary="",
            history=[],
            iteration=0,
        )

        result = planner.propose_next(state, None)
        assert isinstance(result, ToolCall)
        assert result.tool_name == "fs.read"

    def test_propose_next_returns_done(self):
        """Test that propose_next can return Done."""

        class DonePlanner(Planner):
            def propose_next(self, state, last_result):
                if state.iteration >= 3:
                    return Done(reason="max_iterations")
                return ToolCall(
                    call_id=f"call-{state.iteration}",
                    run_id="run-1",
                    step_index=state.iteration,
                    tool_name="noop",
                    args={},
                )

        planner = DonePlanner()

        # First few iterations return ToolCall
        state = PlannerState(
            task="Test",
            tool_schemas=[],
            policy_summary="",
            history=[],
            iteration=0,
        )
        result = planner.propose_next(state, None)
        assert isinstance(result, ToolCall)

        # After 3 iterations, return Done
        state = PlannerState(
            task="Test",
            tool_schemas=[],
            policy_summary="",
            history=[],
            iteration=3,
        )
        result = planner.propose_next(state, None)
        assert isinstance(result, Done)
        assert result.reason == "max_iterations"
