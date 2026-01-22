"""
Tests for the agent loop module.

Tests:
    - AgentConfig dataclass
    - IterationResult dataclass
    - AgentResult dataclass
    - AgentLoop class
"""

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from capsule.agent.loop import (
    AgentConfig,
    AgentLoop,
    AgentResult,
    IterationResult,
)
from capsule.planner.base import Done, Planner, PlannerState
from capsule.policy.engine import PolicyEngine
from capsule.schema import (
    Policy,
    PolicyDecision,
    ToolCall,
    ToolCallStatus,
    ToolResult,
)
from capsule.store.db import CapsuleDB
from capsule.tools.base import Tool, ToolContext, ToolOutput
from capsule.tools.registry import ToolRegistry


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


class MockTool(Tool):
    """Mock tool for testing."""

    def __init__(self, name: str = "mock.tool", output: str = "mock output"):
        self._name = name
        self._output = output

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Mock tool: {self._name}"

    def execute(self, args, context):
        return ToolOutput.ok(self._output)


class MockPlanner(Planner):
    """Mock planner for testing that returns a sequence of proposals."""

    def __init__(self, proposals: list):
        """
        Initialize with a list of proposals to return.

        Each proposal can be a ToolCall or Done.
        """
        self.proposals = proposals
        self.call_count = 0

    def propose_next(self, state: PlannerState, last_result: ToolResult | None):
        if self.call_count >= len(self.proposals):
            return Done(reason="no_more_proposals")
        proposal = self.proposals[self.call_count]
        self.call_count += 1
        return proposal

    def get_name(self) -> str:
        return "MockPlanner"


class TestAgentConfig:
    """Tests for AgentConfig dataclass."""

    def test_default_config(self):
        """Test creating a config with defaults."""
        config = AgentConfig()
        assert config.max_iterations == 20
        assert config.iteration_timeout_seconds == 60.0
        assert config.total_timeout_seconds == 300.0
        assert config.repetition_threshold == 3
        assert config.max_history_items == 10
        assert config.max_history_chars == 8000

    def test_custom_config(self):
        """Test creating a config with custom values."""
        config = AgentConfig(
            max_iterations=10,
            iteration_timeout_seconds=30.0,
            total_timeout_seconds=120.0,
            repetition_threshold=5,
            max_history_items=20,
            max_history_chars=16000,
        )
        assert config.max_iterations == 10
        assert config.iteration_timeout_seconds == 30.0
        assert config.total_timeout_seconds == 120.0
        assert config.repetition_threshold == 5
        assert config.max_history_items == 20
        assert config.max_history_chars == 16000


class TestIterationResult:
    """Tests for IterationResult dataclass."""

    def test_minimal_iteration_result(self):
        """Test creating an iteration result with minimal fields."""
        result = IterationResult(iteration=0)
        assert result.iteration == 0
        assert result.proposal is None
        assert result.tool_call is None
        assert result.tool_result is None
        assert result.done is None
        assert result.policy_decision is None
        assert result.duration_seconds == 0.0

    def test_iteration_result_with_done(self):
        """Test creating an iteration result with Done."""
        done = Done(final_output="Task completed", reason="task_complete")
        result = IterationResult(iteration=3, done=done)
        assert result.iteration == 3
        assert result.done is not None
        assert result.done.final_output == "Task completed"

    def test_iteration_result_with_tool_call(self):
        """Test creating an iteration result with tool call."""
        tool_call = ToolCall(
            call_id="call-1",
            run_id="run-1",
            step_index=0,
            tool_name="fs.read",
            args={"path": "/test"},
        )
        tool_result = make_tool_result(
            call_id="call-1",
            run_id="run-1",
            status=ToolCallStatus.SUCCESS,
            output="file contents",
        )
        result = IterationResult(
            iteration=0,
            tool_call=tool_call,
            tool_result=tool_result,
            duration_seconds=0.5,
        )
        assert result.tool_call is not None
        assert result.tool_call.tool_name == "fs.read"
        assert result.tool_result is not None
        assert result.tool_result.status == ToolCallStatus.SUCCESS


class TestAgentResult:
    """Tests for AgentResult dataclass."""

    def test_minimal_agent_result(self):
        """Test creating an agent result with minimal fields."""
        result = AgentResult(
            run_id="run-1",
            task="Test task",
            status="completed",
        )
        assert result.run_id == "run-1"
        assert result.task == "Test task"
        assert result.status == "completed"
        assert result.iterations == []
        assert result.final_output is None
        assert result.total_duration_seconds == 0.0
        assert result.planner_name == ""
        assert result.error_message is None

    def test_agent_result_with_iterations(self):
        """Test creating an agent result with iterations."""
        iter1 = IterationResult(iteration=0)
        iter2 = IterationResult(iteration=1)
        result = AgentResult(
            run_id="run-1",
            task="Multi-step task",
            status="completed",
            iterations=[iter1, iter2],
            final_output="Done",
            total_duration_seconds=2.5,
            planner_name="TestPlanner",
        )
        assert len(result.iterations) == 2
        assert result.final_output == "Done"
        assert result.total_duration_seconds == 2.5
        assert result.planner_name == "TestPlanner"

    def test_agent_result_with_error(self):
        """Test creating an agent result with error."""
        result = AgentResult(
            run_id="run-1",
            task="Failed task",
            status="error",
            error_message="Something went wrong",
        )
        assert result.status == "error"
        assert result.error_message == "Something went wrong"


class TestAgentLoop:
    """Tests for AgentLoop class."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        db = CapsuleDB(db_path)
        yield db
        db.close()
        Path(db_path).unlink(missing_ok=True)

    @pytest.fixture
    def mock_policy(self):
        """Create a mock policy that allows all operations."""
        return Policy(
            tools={
                "fs.read": {
                    "allow_paths": ["./**"],
                },
                "fs.write": {
                    "allow_paths": ["./**"],
                },
                "shell.run": {
                    "allow_executables": ["echo", "ls"],
                },
            },
        )

    @pytest.fixture
    def mock_registry(self):
        """Create a mock tool registry."""
        registry = ToolRegistry()
        registry.register(MockTool("fs.read", "file contents"))
        registry.register(MockTool("fs.write", "written"))
        registry.register(MockTool("shell.run", "command output"))
        return registry

    def test_agent_loop_init(self, temp_db, mock_policy, mock_registry):
        """Test initializing an agent loop."""
        planner = MockPlanner([Done()])
        policy_engine = PolicyEngine(mock_policy)

        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=mock_registry,
            db=temp_db,
        )

        assert loop.planner is planner
        assert loop.policy_engine is policy_engine
        assert loop.registry is mock_registry
        assert loop.db is temp_db
        assert loop.config.max_iterations == 20  # default

    def test_agent_loop_init_with_custom_config(self, temp_db, mock_policy, mock_registry):
        """Test initializing an agent loop with custom config."""
        planner = MockPlanner([Done()])
        policy_engine = PolicyEngine(mock_policy)
        config = AgentConfig(max_iterations=5)

        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=mock_registry,
            db=temp_db,
            config=config,
        )

        assert loop.config.max_iterations == 5

    def test_agent_loop_simple_task_completes(self, temp_db, mock_policy, mock_registry):
        """Test that a simple task completes successfully."""
        # Planner immediately signals done
        planner = MockPlanner([Done(final_output="Task done", reason="task_complete")])
        policy_engine = PolicyEngine(mock_policy)

        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=mock_registry,
            db=temp_db,
        )

        result = loop.run("Simple task")

        assert result.status == "completed"
        assert result.final_output == "Task done"
        assert len(result.iterations) == 1
        assert result.iterations[0].done is not None

    def test_agent_loop_executes_tool_calls(self, temp_db, mock_policy, mock_registry):
        """Test that the loop executes tool calls."""
        proposals = [
            ToolCall(
                call_id="pending",
                run_id="pending",
                step_index=0,
                tool_name="fs.read",
                args={"path": "/test.txt"},
            ),
            Done(final_output="Read complete"),
        ]
        planner = MockPlanner(proposals)
        policy_engine = PolicyEngine(mock_policy)

        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=mock_registry,
            db=temp_db,
        )

        result = loop.run("Read a file")

        assert result.status == "completed"
        assert len(result.iterations) == 2
        # First iteration should have a tool call
        assert result.iterations[0].tool_call is not None
        assert result.iterations[0].tool_call.tool_name == "fs.read"
        # Second iteration should be done
        assert result.iterations[1].done is not None

    def test_agent_loop_handles_done_signal(self, temp_db, mock_policy, mock_registry):
        """Test that the loop stops on Done signal."""
        planner = MockPlanner([
            ToolCall(
                call_id="pending",
                run_id="pending",
                step_index=0,
                tool_name="fs.read",
                args={"path": "/test"},
            ),
            Done(reason="task_complete", final_output="All done"),
        ])
        policy_engine = PolicyEngine(mock_policy)

        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=mock_registry,
            db=temp_db,
        )

        result = loop.run("Task with done signal")

        assert result.status == "completed"
        assert result.final_output == "All done"

    def test_agent_loop_max_iterations(self, temp_db, mock_policy, mock_registry):
        """Test that the loop stops at max iterations."""
        # Planner always returns tool calls, never Done
        calls = [
            ToolCall(
                call_id="pending",
                run_id="pending",
                step_index=i,
                tool_name="fs.read",
                args={"path": f"/test{i}"},
            )
            for i in range(100)  # More than max_iterations
        ]
        planner = MockPlanner(calls)
        policy_engine = PolicyEngine(mock_policy)
        config = AgentConfig(max_iterations=5)

        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=mock_registry,
            db=temp_db,
            config=config,
        )

        result = loop.run("Infinite task")

        assert result.status == "max_iterations"
        assert len(result.iterations) == 5

    def test_agent_loop_policy_denial(self, temp_db, mock_registry):
        """Test that policy denials are handled."""
        # Create a restrictive policy that denies everything
        strict_policy = Policy()  # Default denies all

        proposals = [
            ToolCall(
                call_id="pending",
                run_id="pending",
                step_index=0,
                tool_name="fs.read",
                args={"path": "/etc/passwd"},  # Not allowed
            ),
            Done(reason="cannot_proceed"),
        ]
        planner = MockPlanner(proposals)
        policy_engine = PolicyEngine(strict_policy)

        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=mock_registry,
            db=temp_db,
        )

        result = loop.run("Read sensitive file")

        assert result.status == "completed"
        # First iteration should be denied
        assert result.iterations[0].tool_result is not None
        assert result.iterations[0].tool_result.status == ToolCallStatus.DENIED

    def test_agent_loop_repetition_detection(self, temp_db, mock_policy, mock_registry):
        """Test that repetition detection stops the loop."""
        # Same tool call repeated many times
        same_call = ToolCall(
            call_id="pending",
            run_id="pending",
            step_index=0,
            tool_name="fs.read",
            args={"path": "/same/file"},
        )
        proposals = [same_call for _ in range(10)]
        planner = MockPlanner(proposals)
        policy_engine = PolicyEngine(mock_policy)
        config = AgentConfig(repetition_threshold=3)

        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=mock_registry,
            db=temp_db,
            config=config,
        )

        result = loop.run("Repetitive task")

        assert result.status == "repetition_detected"
        # Should stop after threshold iterations
        assert len(result.iterations) <= 3

    def test_agent_loop_history_truncation(self, temp_db, mock_policy, mock_registry):
        """Test that history is truncated."""
        calls = [
            ToolCall(
                call_id="pending",
                run_id="pending",
                step_index=i,
                tool_name="fs.read",
                args={"path": f"/file{i}.txt"},  # Different files to avoid repetition
            )
            for i in range(15)
        ] + [Done()]
        planner = MockPlanner(calls)
        policy_engine = PolicyEngine(mock_policy)
        config = AgentConfig(max_history_items=5)

        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=mock_registry,
            db=temp_db,
            config=config,
        )

        result = loop.run("Long task")

        assert result.status == "completed"
        # All iterations recorded
        assert len(result.iterations) == 16  # 15 calls + 1 done

    def test_agent_loop_records_proposals_in_db(self, temp_db, mock_policy, mock_registry):
        """Test that tool calls are recorded in the database."""
        proposals = [
            ToolCall(
                call_id="pending",
                run_id="pending",
                step_index=0,
                tool_name="fs.read",
                args={"path": "/test.txt"},
            ),
            Done(),
        ]
        planner = MockPlanner(proposals)
        policy_engine = PolicyEngine(mock_policy)

        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=mock_registry,
            db=temp_db,
        )

        result = loop.run("Task to record")

        # Verify that calls were recorded in DB
        # The run should exist
        runs = temp_db.list_runs()
        assert len(runs) >= 1

    def test_agent_loop_get_tool_schemas(self, temp_db, mock_policy, mock_registry):
        """Test that tool schemas are correctly generated."""
        planner = MockPlanner([Done()])
        policy_engine = PolicyEngine(mock_policy)

        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=mock_registry,
            db=temp_db,
        )

        schemas = loop._get_tool_schemas()

        assert len(schemas) == 3  # fs.read, fs.write, shell.run
        names = [s["name"] for s in schemas]
        assert "fs.read" in names
        assert "fs.write" in names
        assert "shell.run" in names

    def test_agent_loop_build_policy_summary(self, temp_db, mock_policy, mock_registry):
        """Test that policy summary is correctly built."""
        planner = MockPlanner([Done()])
        policy_engine = PolicyEngine(mock_policy)

        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=mock_registry,
            db=temp_db,
        )

        summary = loop._build_policy_summary()

        assert "read:" in summary.lower() or "read" in summary.lower()
        assert "./**" in summary or "write" in summary.lower()

    def test_agent_loop_truncate_history_by_items(self, temp_db, mock_policy, mock_registry):
        """Test history truncation by number of items."""
        planner = MockPlanner([Done()])
        policy_engine = PolicyEngine(mock_policy)
        config = AgentConfig(max_history_items=3)

        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=mock_registry,
            db=temp_db,
            config=config,
        )

        # Create 5 history items
        history = []
        for i in range(5):
            call = ToolCall(
                call_id=f"call-{i}",
                run_id="run-1",
                step_index=i,
                tool_name="fs.read",
                args={"path": f"/file{i}"},
            )
            result = make_tool_result(
                call_id=f"call-{i}",
                run_id="run-1",
                status=ToolCallStatus.SUCCESS,
                output=f"content{i}",
            )
            history.append((call, result))

        truncated = loop._truncate_history(history)

        assert len(truncated) == 3
        # Should keep the most recent items
        assert truncated[-1][0].call_id == "call-4"

    def test_agent_loop_detect_repetition_no_history(self, temp_db, mock_policy, mock_registry):
        """Test repetition detection with empty history."""
        planner = MockPlanner([Done()])
        policy_engine = PolicyEngine(mock_policy)

        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=mock_registry,
            db=temp_db,
        )

        proposal = ToolCall(
            call_id="pending",
            run_id="pending",
            step_index=0,
            tool_name="fs.read",
            args={"path": "/test"},
        )

        # Empty history should not trigger repetition
        assert loop._detect_repetition([], proposal) is False

    def test_agent_loop_detect_repetition_different_calls(self, temp_db, mock_policy, mock_registry):
        """Test repetition detection with different calls."""
        planner = MockPlanner([Done()])
        policy_engine = PolicyEngine(mock_policy)

        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=mock_registry,
            db=temp_db,
        )

        # History with different calls
        history = []
        for i in range(3):
            call = ToolCall(
                call_id=f"call-{i}",
                run_id="run-1",
                step_index=i,
                tool_name="fs.read",
                args={"path": f"/file{i}"},  # Different paths
            )
            result = make_tool_result(
                call_id=f"call-{i}",
                run_id="run-1",
                status=ToolCallStatus.SUCCESS,
            )
            history.append((call, result))

        # New proposal with different path
        proposal = ToolCall(
            call_id="pending",
            run_id="pending",
            step_index=3,
            tool_name="fs.read",
            args={"path": "/new/file"},
        )

        assert loop._detect_repetition(history, proposal) is False

    def test_agent_loop_detect_repetition_same_calls(self, temp_db, mock_policy, mock_registry):
        """Test repetition detection with same consecutive calls."""
        planner = MockPlanner([Done()])
        policy_engine = PolicyEngine(mock_policy)
        config = AgentConfig(repetition_threshold=3)

        loop = AgentLoop(
            planner=planner,
            policy_engine=policy_engine,
            registry=mock_registry,
            db=temp_db,
            config=config,
        )

        # History with same call repeated
        history = []
        for i in range(2):  # 2 calls in history
            call = ToolCall(
                call_id=f"call-{i}",
                run_id="run-1",
                step_index=i,
                tool_name="fs.read",
                args={"path": "/same/file"},  # Same path
            )
            result = make_tool_result(
                call_id=f"call-{i}",
                run_id="run-1",
                status=ToolCallStatus.SUCCESS,
            )
            history.append((call, result))

        # Same proposal again (would be the 3rd consecutive)
        proposal = ToolCall(
            call_id="pending",
            run_id="pending",
            step_index=2,
            tool_name="fs.read",
            args={"path": "/same/file"},
        )

        # With threshold=3 and 2 in history, this would be the 3rd - should trigger
        assert loop._detect_repetition(history, proposal) is True
