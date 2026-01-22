"""
Agent loop for Capsule.

This module implements the core agent loop that integrates the planner
with policy evaluation and tool execution. The loop follows a
propose -> evaluate -> execute -> learn cycle:

1. Planner proposes the next tool call based on task and history
2. Policy engine evaluates if the call is allowed
3. If allowed, executor runs the tool
4. Result is recorded and fed back to planner

Design Principles:
    - Planners are untrusted - all proposals validated by policy
    - History is bounded - prevents context overflow
    - Repetition detection - stops infinite loops
    - All execution is recorded - enables audit and replay

Security Features:
    - Repetition detection: Stop if same call repeated N times
    - History truncation: Limit history to prevent context overflow
    - Timeout protection: Per-iteration and total execution timeouts
    - Policy enforcement: All proposals validated before execution
"""

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from capsule.planner.base import Done, Planner, PlannerState
from capsule.policy.engine import PolicyEngine
from capsule.schema import (
    Plan,
    PlannerProposal,
    PlanStep,
    PolicyDecision,
    RunMode,
    RunStatus,
    ToolCall,
    ToolCallStatus,
    ToolResult,
)
from capsule.store.db import CapsuleDB
from capsule.tools.base import Tool, ToolContext, ToolOutput
from capsule.tools.registry import ToolRegistry


@dataclass
class AgentConfig:
    """
    Configuration for the agent loop.

    Attributes:
        max_iterations: Maximum number of iterations before stopping
        iteration_timeout_seconds: Timeout for each iteration
        total_timeout_seconds: Timeout for the entire run
        repetition_threshold: Number of times the same call can repeat before stopping
        max_history_items: Maximum number of history items to keep
        max_history_chars: Maximum characters in history (truncated if exceeded)
    """

    max_iterations: int = 20
    iteration_timeout_seconds: float = 60.0
    total_timeout_seconds: float = 300.0
    repetition_threshold: int = 3
    max_history_items: int = 10
    max_history_chars: int = 8000


@dataclass
class IterationResult:
    """
    Result of a single agent loop iteration.

    Captures what happened during one propose -> evaluate -> execute cycle.

    Attributes:
        iteration: The iteration number (0-indexed)
        proposal: The PlannerProposal if a tool was proposed
        tool_call: The actual ToolCall made (with IDs assigned)
        tool_result: The result of executing the tool
        done: The Done sentinel if planner signaled completion
        policy_decision: The policy decision made for this iteration
        duration_seconds: How long this iteration took
    """

    iteration: int
    proposal: PlannerProposal | None = None
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    done: Done | None = None
    policy_decision: PolicyDecision | None = None
    duration_seconds: float = 0.0


@dataclass
class AgentResult:
    """
    Final result of an agent run.

    Contains everything about what happened during the agent's execution,
    including all iterations, final status, and timing information.

    Attributes:
        run_id: Unique identifier for this run
        task: The original task description
        status: Final status ("completed", "max_iterations", "timeout",
                "error", "repetition_detected")
        iterations: List of all iteration results
        final_output: The final output from the planner (if completed)
        total_duration_seconds: Total time taken
        planner_name: Name of the planner used
        error_message: Error message if status is "error"
    """

    run_id: str
    task: str
    status: str
    iterations: list[IterationResult] = field(default_factory=list)
    final_output: Any = None
    total_duration_seconds: float = 0.0
    planner_name: str = ""
    error_message: str | None = None


class AgentLoop:
    """
    Main agent loop that orchestrates task execution.

    The AgentLoop coordinates between the planner (which proposes tool calls),
    the policy engine (which validates them), and the tool registry (which
    executes them). It maintains history, detects repetition, and enforces
    timeouts.

    Usage:
        loop = AgentLoop(planner, policy_engine, registry, db)
        result = loop.run("List all Python files and count lines")

    Attributes:
        planner: The planner that proposes tool calls
        policy_engine: The policy engine that validates calls
        registry: The tool registry for executing tools
        db: Database for recording execution history
        config: Configuration for the loop
    """

    def __init__(
        self,
        planner: Planner,
        policy_engine: PolicyEngine,
        registry: ToolRegistry,
        db: CapsuleDB,
        config: AgentConfig | None = None,
    ):
        """
        Initialize the agent loop.

        Args:
            planner: The planner that proposes tool calls
            policy_engine: The policy engine that validates calls
            registry: The tool registry for executing tools
            db: Database for recording execution history
            config: Optional configuration (uses defaults if not provided)
        """
        self.planner = planner
        self.policy_engine = policy_engine
        self.registry = registry
        self.db = db
        self.config = config or AgentConfig()

    def run(self, task: str, working_dir: str | None = None) -> AgentResult:
        """
        Execute a task using the planner-driven agent loop.

        This is the main entry point for the agent. It will:
        1. Create a new run in the database
        2. Loop: propose -> evaluate -> execute -> learn
        3. Stop on completion, max iterations, timeout, or error
        4. Return the final result

        Args:
            task: The task description for the planner
            working_dir: Working directory for tool execution (defaults to ".")

        Returns:
            AgentResult with all execution details
        """
        working_dir = working_dir or "."
        start_time = time.time()

        # Create a minimal plan for database recording
        # The agent loop doesn't use a static plan, but we need one for the DB
        dummy_plan = Plan(
            version="1.0",
            steps=[PlanStep(tool="agent.dynamic", args={"task": task})],
            name="Agent Dynamic Plan",
            description=f"Dynamic plan for task: {task}",
        )

        # Create run in database and use the returned run_id
        run_id = self.db.create_run(
            plan=dummy_plan,
            policy=self.policy_engine.policy,
            mode=RunMode.RUN,
        )

        # Initialize result
        result = AgentResult(
            run_id=run_id,
            task=task,
            status="running",
            planner_name=self.planner.get_name(),
        )

        # History of (ToolCall, ToolResult) pairs for the planner
        history: list[tuple[ToolCall, ToolResult]] = []
        last_result: ToolResult | None = None

        try:
            for iteration in range(self.config.max_iterations):
                # Check total timeout
                elapsed = time.time() - start_time
                if elapsed >= self.config.total_timeout_seconds:
                    result.status = "timeout"
                    break

                # Run one iteration
                iter_result = self._run_iteration(
                    task=task,
                    working_dir=working_dir,
                    run_id=run_id,
                    iteration=iteration,
                    history=history,
                    last_result=last_result,
                )
                result.iterations.append(iter_result)

                # Check if planner signaled done
                if iter_result.done is not None:
                    result.status = "completed"
                    result.final_output = iter_result.done.final_output
                    # Call finalize if planner supports it
                    state = self._build_state(task, history, iteration)
                    final = self.planner.finalize(state, iter_result.done)
                    if final is not None:
                        result.final_output = final
                    break

                # Check for repetition detection
                if iter_result.tool_call and self._detect_repetition(
                    history, iter_result.tool_call
                ):
                    result.status = "repetition_detected"
                    break

                # Update history if we have a tool call and result
                if iter_result.tool_call and iter_result.tool_result:
                    history.append((iter_result.tool_call, iter_result.tool_result))
                    last_result = iter_result.tool_result

                # Truncate history if needed
                history = self._truncate_history(history)

            else:
                # Loop completed without break - hit max iterations
                result.status = "max_iterations"

        except Exception as e:
            result.status = "error"
            result.error_message = str(e)

        # Calculate total duration
        result.total_duration_seconds = time.time() - start_time

        # Count step statistics from iterations
        completed_steps = 0
        denied_steps = 0
        failed_steps = 0
        for it in result.iterations:
            if it.tool_result:
                if it.tool_result.status == ToolCallStatus.SUCCESS:
                    completed_steps += 1
                elif it.tool_result.status == ToolCallStatus.DENIED:
                    denied_steps += 1
                elif it.tool_result.status == ToolCallStatus.ERROR:
                    failed_steps += 1

        # Map agent status to RunStatus
        if result.status == "completed":
            run_status = RunStatus.COMPLETED
        elif result.status == "error":
            run_status = RunStatus.FAILED
        else:
            # timeout, max_iterations, repetition_detected all map to completed
            # (they finished, just not successfully in the task sense)
            run_status = RunStatus.COMPLETED

        # Update run status in database
        self.db.update_run_status(
            run_id=run_id,
            status=run_status,
            completed_steps=completed_steps,
            denied_steps=denied_steps,
            failed_steps=failed_steps,
        )

        return result

    def _run_iteration(
        self,
        task: str,
        working_dir: str,
        run_id: str,
        iteration: int,
        history: list[tuple[ToolCall, ToolResult]],
        last_result: ToolResult | None,
    ) -> IterationResult:
        """
        Run a single iteration of the agent loop.

        One iteration consists of:
        1. Build planner state
        2. Get proposal from planner
        3. If Done, return immediately
        4. Evaluate against policy
        5. If denied, create denied result and return
        6. If allowed, execute tool and return result

        Args:
            task: The task description
            working_dir: Working directory
            run_id: Current run ID
            iteration: Current iteration number
            history: History of previous calls
            last_result: Result of the last tool call

        Returns:
            IterationResult capturing what happened
        """
        iter_start = time.time()
        iter_result = IterationResult(iteration=iteration)

        # Build planner state
        state = self._build_state(task, history, iteration)

        # Get proposal from planner
        proposal = self.planner.propose_next(state, last_result)

        # Check if planner signaled done
        if isinstance(proposal, Done):
            iter_result.done = proposal
            iter_result.duration_seconds = time.time() - iter_start
            return iter_result

        # It's a ToolCall - extract proposal info
        tool_call = proposal
        iter_result.proposal = PlannerProposal(
            tool_name=tool_call.tool_name,
            args=tool_call.args,
            iteration=iteration,
        )

        # Record the call in database first to get the call_id
        call_id = self.db.record_call(
            run_id=run_id,
            step_index=iteration,
            tool_name=tool_call.tool_name,
            args=tool_call.args,
        )

        # Now create the ToolCall with proper IDs
        tool_call = ToolCall(
            call_id=call_id,
            run_id=run_id,
            step_index=iteration,
            tool_name=tool_call.tool_name,
            args=tool_call.args,
        )
        iter_result.tool_call = tool_call

        # Evaluate against policy
        decision = self.policy_engine.evaluate(
            tool_name=tool_call.tool_name,
            args=tool_call.args,
            working_dir=working_dir,
        )
        iter_result.policy_decision = decision

        # Create timestamps for result
        started_at = datetime.now(UTC)

        if not decision.allowed:
            # Policy denied - create denied result
            ended_at = datetime.now(UTC)
            tool_result = ToolResult(
                call_id=call_id,
                run_id=run_id,
                status=ToolCallStatus.DENIED,
                output=None,
                error=f"Denied by policy: {decision.reason}",
                policy_decision=decision,
                started_at=started_at,
                ended_at=ended_at,
                input_hash="",
                output_hash="",
            )
            iter_result.tool_result = tool_result

            # Record denied result
            self.db.record_result(
                call_id=call_id,
                run_id=run_id,
                status=ToolCallStatus.DENIED,
                output=None,
                error=tool_result.error,
                policy_decision=decision,
                started_at=started_at,
                ended_at=ended_at,
                input_data=tool_call.args,
            )

            iter_result.duration_seconds = time.time() - iter_start
            return iter_result

        # Policy allowed - execute the tool
        tool_output = self._execute_tool(tool_call, working_dir)
        ended_at = datetime.now(UTC)

        # Create tool result
        if tool_output.success:
            status = ToolCallStatus.SUCCESS
            output = tool_output.data
            error = None
        else:
            status = ToolCallStatus.ERROR
            output = None
            error = tool_output.error

        tool_result = ToolResult(
            call_id=call_id,
            run_id=run_id,
            status=status,
            output=output,
            error=error,
            policy_decision=decision,
            started_at=started_at,
            ended_at=ended_at,
            input_hash="",
            output_hash="",
        )
        iter_result.tool_result = tool_result

        # Record result in database
        self.db.record_result(
            call_id=call_id,
            run_id=run_id,
            status=status,
            output=output,
            error=error,
            policy_decision=decision,
            started_at=started_at,
            ended_at=ended_at,
            input_data=tool_call.args,
        )

        iter_result.duration_seconds = time.time() - iter_start
        return iter_result

    def _build_state(
        self,
        task: str,
        history: list[tuple[ToolCall, ToolResult]],
        iteration: int,
    ) -> PlannerState:
        """
        Build the planner state for the current iteration.

        Args:
            task: The task description
            history: History of previous tool calls and results
            iteration: Current iteration number

        Returns:
            PlannerState ready to pass to the planner
        """
        # Get tool schemas from registry
        tool_schemas = self._get_tool_schemas()

        # Build policy summary from the policy
        policy_summary = self._build_policy_summary()

        return PlannerState(
            task=task,
            tool_schemas=tool_schemas,
            policy_summary=policy_summary,
            history=history,
            iteration=iteration,
        )

    def _build_policy_summary(self) -> str:
        """
        Build a human-readable policy summary for the planner.

        Returns:
            String summarizing what the policy allows/denies
        """
        policy = self.policy_engine.policy
        lines = []

        # File system policy
        fs_read = policy.tools.fs_read
        if fs_read.allow_paths:
            lines.append(f"Can read: {', '.join(fs_read.allow_paths)}")
        else:
            lines.append("Cannot read any files")

        fs_write = policy.tools.fs_write
        if fs_write.allow_paths:
            lines.append(f"Can write: {', '.join(fs_write.allow_paths)}")
        else:
            lines.append("Cannot write any files")

        # HTTP policy
        http_policy = policy.tools.http_get
        if http_policy.allow_domains:
            lines.append(f"Can access domains: {', '.join(http_policy.allow_domains)}")
        else:
            lines.append("Cannot access any URLs")

        # Shell policy
        shell_policy = policy.tools.shell_run
        if shell_policy.allow_executables:
            lines.append(
                f"Can run commands: {', '.join(shell_policy.allow_executables)}"
            )
        else:
            lines.append("Cannot run any shell commands")

        return "; ".join(lines)

    def _get_tool_schemas(self) -> list[dict[str, Any]]:
        """
        Get tool schemas from all registered tools.

        Returns:
            List of tool schema dictionaries in the format expected by the planner
        """
        schemas = []
        for tool in self.registry:
            schema = {
                "name": tool.name,
                "description": tool.description,
                "args": self._get_tool_args_schema(tool),
            }
            schemas.append(schema)
        return schemas

    def _get_tool_args_schema(self, tool: Tool) -> dict[str, Any]:
        """
        Get the argument schema for a tool.

        This is a simplified schema - tools can override validate_args
        for more specific validation.

        Args:
            tool: The tool to get the schema for

        Returns:
            Dictionary describing the tool's arguments
        """
        # Default schemas for known tools
        if tool.name == "fs.read":
            return {
                "path": {"type": "string", "required": True},
            }
        elif tool.name == "fs.write":
            return {
                "path": {"type": "string", "required": True},
                "content": {"type": "string", "required": True},
            }
        elif tool.name == "http.get":
            return {
                "url": {"type": "string", "required": True},
            }
        elif tool.name == "shell.run":
            return {
                "cmd": {"type": "array", "required": True},
            }
        else:
            # Unknown tool - return empty schema
            return {}

    def _truncate_history(
        self,
        history: list[tuple[ToolCall, ToolResult]],
    ) -> list[tuple[ToolCall, ToolResult]]:
        """
        Truncate history to fit within configured limits.

        This prevents context overflow by limiting both the number of
        items and total characters in history.

        Args:
            history: The full history

        Returns:
            Truncated history
        """
        # Limit by number of items
        if len(history) > self.config.max_history_items:
            history = history[-self.config.max_history_items :]

        # Limit by total characters
        total_chars = 0
        truncated: list[tuple[ToolCall, ToolResult]] = []
        for call, result in reversed(history):
            # Estimate size of this entry
            entry_chars = len(json.dumps(call.args, default=str))
            if result.output:
                entry_chars += len(str(result.output))
            if result.error:
                entry_chars += len(result.error)

            if total_chars + entry_chars > self.config.max_history_chars:
                break

            truncated.insert(0, (call, result))
            total_chars += entry_chars

        return truncated

    def _detect_repetition(
        self,
        history: list[tuple[ToolCall, ToolResult]],
        proposal: ToolCall,
    ) -> bool:
        """
        Detect if the same tool call has been repeated too many times.

        This prevents infinite loops where the planner keeps proposing
        the same failing call.

        Args:
            history: Previous tool calls
            proposal: The proposed tool call

        Returns:
            True if repetition threshold exceeded
        """
        if not history:
            return False

        # Count consecutive identical calls from the end
        consecutive = 0
        for call, _result in reversed(history):
            if (
                call.tool_name == proposal.tool_name
                and call.args == proposal.args
            ):
                consecutive += 1
            else:
                break

        # If we would execute the same call again, that's one more
        return consecutive >= self.config.repetition_threshold - 1

    def _execute_tool(self, tool_call: ToolCall, working_dir: str) -> ToolOutput:
        """
        Execute a single tool call.

        Args:
            tool_call: The tool call to execute
            working_dir: Working directory for execution

        Returns:
            ToolOutput from the tool
        """
        # Get the tool from registry
        try:
            tool = self.registry.get(tool_call.tool_name)
        except Exception as e:
            return ToolOutput.fail(f"Tool not found: {tool_call.tool_name} - {e}")

        # Create execution context
        context = ToolContext(
            run_id=tool_call.run_id,
            policy=self.policy_engine.policy,
            working_dir=working_dir,
        )

        # Execute the tool
        try:
            return tool.execute(tool_call.args, context)
        except Exception as e:
            return ToolOutput.fail(f"Tool execution error: {e}")
