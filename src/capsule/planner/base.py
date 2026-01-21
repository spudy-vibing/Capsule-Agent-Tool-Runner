"""
Base classes for Capsule planners.

This module defines the abstract interface that all planners must implement,
along with the data structures used to communicate between the agent loop
and the planner.

Design Principles:
    - Planners are stateless between calls (state passed explicitly)
    - All planner output is untrusted and validated by policy engine
    - Planners can signal completion via Done sentinel
    - Error handling is explicit via PlannerError hierarchy
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from capsule.schema import ToolCall, ToolResult


@dataclass
class PlannerState:
    """
    State passed to planner on each iteration.

    This dataclass captures everything the planner needs to decide
    the next action. It's passed fresh on each iteration to ensure
    planners remain stateless.

    Attributes:
        task: Original user task description
        tool_schemas: Available tool definitions (JSON schema format)
        policy_summary: Human-readable policy constraints for context
        history: Previous (ToolCall, ToolResult) pairs in order
        iteration: Current iteration number (0-indexed)
        metadata: Additional context (e.g., pack name, user prefs)

    Example:
        state = PlannerState(
            task="Find all Python files and count lines",
            tool_schemas=[{"name": "fs.read", ...}],
            policy_summary="Can read ./**/*.py, cannot write",
            history=[],
            iteration=0,
        )
    """

    task: str
    tool_schemas: list[dict[str, Any]]
    policy_summary: str
    history: list[tuple[ToolCall, ToolResult]]
    iteration: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate state after initialization."""
        if not self.task:
            raise ValueError("task cannot be empty")
        if self.iteration < 0:
            raise ValueError("iteration must be non-negative")


@dataclass
class Done:
    """
    Sentinel indicating the agent loop should terminate.

    When a planner returns Done instead of a ToolCall, the agent loop
    should stop and return the final output to the user.

    Attributes:
        final_output: Optional final result (string, dict, or None)
        reason: Why the planner is signaling completion

    Reasons:
        - "task_complete": Task successfully accomplished
        - "cannot_proceed": Planner cannot make progress
        - "max_iterations": Hit iteration limit
        - "user_cancel": User requested cancellation

    Example:
        return Done(
            final_output={"files_found": 42, "total_lines": 1234},
            reason="task_complete"
        )
    """

    final_output: str | dict[str, Any] | None = None
    reason: str = "task_complete"

    # Valid reason codes
    VALID_REASONS = frozenset(
        {
            "task_complete",
            "cannot_proceed",
            "max_iterations",
            "user_cancel",
            "policy_blocked",
        }
    )

    def __post_init__(self) -> None:
        """Validate the Done sentinel."""
        if self.reason not in self.VALID_REASONS:
            # Allow custom reasons but warn in logs
            pass


class Planner(ABC):
    """
    Abstract base class for plan generators.

    Planners are responsible for deciding what tool to call next
    given the current state. They receive the task description,
    available tools, and execution history, then propose the next
    action or signal completion.

    Implementations:
        - OllamaPlanner: Uses local Ollama for SLM-based planning
        - (Future) OpenAIPlanner: Uses OpenAI API
        - (Future) AnthropicPlanner: Uses Anthropic API

    Security Note:
        All planner output is UNTRUSTED. The agent loop must validate
        proposed tool calls against the policy engine before execution.

    Example Implementation:
        class MyPlanner(Planner):
            def propose_next(self, state, last_result):
                if state.iteration > 5:
                    return Done(reason="max_iterations")
                return ToolCall(tool_name="fs.read", args={"path": "..."})
    """

    @abstractmethod
    def propose_next(
        self,
        state: PlannerState,
        last_result: ToolResult | None,
    ) -> ToolCall | Done:
        """
        Propose the next tool call or signal completion.

        This is the core method that planners must implement. Given the
        current state (including history of previous calls), decide what
        to do next.

        Args:
            state: Current planner state with task, tools, and history
            last_result: Result of the previous tool call, or None if
                        this is the first iteration

        Returns:
            ToolCall: The next tool to execute with its arguments
            Done: Signal that the task is complete or cannot proceed

        Raises:
            PlannerConnectionError: Cannot connect to planner backend
            PlannerTimeoutError: Planner took too long to respond
            PlannerParseError: Could not parse planner response

        Note:
            The returned ToolCall will be validated against policy
            before execution. If denied, the denial will appear in
            the next iteration's history.
        """
        ...

    def finalize(
        self,
        state: PlannerState,
        done: Done,
    ) -> dict[str, Any] | None:
        """
        Generate final output after Done signal.

        Called by the agent loop after receiving Done to allow the
        planner to generate a summary or final report.

        Args:
            state: Final planner state
            done: The Done sentinel that was returned

        Returns:
            Optional final output dictionary, or None

        Default implementation returns None. Override to provide
        custom finalization logic.
        """
        return None

    def get_name(self) -> str:
        """Return the planner's name for logging."""
        return self.__class__.__name__

    def get_config(self) -> dict[str, Any]:
        """Return planner configuration for debugging."""
        return {}
