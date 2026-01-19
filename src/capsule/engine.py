"""
Execution Engine for Capsule.

The Engine is the main orchestration layer that executes plans under
policy constraints. It coordinates between:
- Policy Engine: Decides if tool calls are allowed
- Tools: Execute the actual operations
- Storage: Records all calls and results

Execution Flow:
    1. Load plan and policy
    2. For each step in the plan:
        a. Evaluate policy for the tool call
        b. If denied: record denial and stop (fail-closed)
        c. If allowed: execute tool
        d. Record result (success or error)
    3. Update run status and return summary

Design Principles:
    - Fail-closed: Policy denials stop execution
    - Full audit: Every call and result is recorded
    - Reproducible: Same plan + policy = same decisions
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from capsule.errors import (
    CapsuleError,
    PolicyDeniedError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolTimeoutError,
)
from capsule.policy import PolicyEngine
from capsule.schema import (
    Plan,
    Policy,
    PolicyDecision,
    RunMode,
    RunStatus,
    ToolCallStatus,
)
from capsule.store import CapsuleDB
from capsule.tools import ToolContext, ToolOutput, default_registry
from capsule.tools.registry import ToolRegistry


@dataclass
class StepResult:
    """
    Result of executing a single step.

    Attributes:
        step_index: Position in the plan
        tool_name: Name of the tool
        args: Arguments passed to the tool
        status: Outcome status
        output: Output data if successful
        error: Error message if failed
        policy_decision: The policy decision made
        duration_ms: Execution time in milliseconds
    """

    step_index: int
    tool_name: str
    args: dict[str, Any]
    status: ToolCallStatus
    output: Any = None
    error: str | None = None
    policy_decision: PolicyDecision = field(
        default_factory=lambda: PolicyDecision.deny("not evaluated")
    )
    duration_ms: float = 0.0


@dataclass
class RunResult:
    """
    Result of executing a complete plan.

    Attributes:
        run_id: Unique identifier for this run
        status: Final status (completed, failed)
        steps: Results for each step
        total_steps: Number of steps in plan
        completed_steps: Number of steps that completed successfully
        denied_steps: Number of steps denied by policy
        failed_steps: Number of steps that failed during execution
        duration_ms: Total execution time in milliseconds
    """

    run_id: str
    status: RunStatus
    steps: list[StepResult]
    total_steps: int = 0
    completed_steps: int = 0
    denied_steps: int = 0
    failed_steps: int = 0
    duration_ms: float = 0.0

    @property
    def success(self) -> bool:
        """Whether the run completed successfully."""
        return self.status == RunStatus.COMPLETED and self.failed_steps == 0


class Engine:
    """
    Main execution engine for Capsule.

    The Engine orchestrates plan execution, coordinating policy evaluation,
    tool execution, and result storage.

    Usage:
        engine = Engine(db_path="capsule.db")
        result = engine.run(plan, policy)
        print(f"Run {result.run_id}: {result.status}")

    Attributes:
        db: Database connection for storing results
        registry: Tool registry for looking up tools
        working_dir: Working directory for relative paths
    """

    def __init__(
        self,
        db_path: str | Path = "capsule.db",
        registry: ToolRegistry | None = None,
        working_dir: str | Path = ".",
    ) -> None:
        """
        Initialize the engine.

        Args:
            db_path: Path to SQLite database
            registry: Tool registry (defaults to global registry)
            working_dir: Working directory for relative paths
        """
        self.db = CapsuleDB(db_path)
        self.registry = registry or default_registry
        self.working_dir = str(Path(working_dir).resolve())

    def close(self) -> None:
        """Close database connection."""
        self.db.close()

    def __enter__(self) -> "Engine":
        """Enter context manager."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Exit context manager."""
        self.close()

    def run(
        self,
        plan: Plan,
        policy: Policy,
        fail_fast: bool = True,
    ) -> RunResult:
        """
        Execute a plan under policy constraints.

        This is the main entry point for plan execution. It:
        1. Creates a run record
        2. Executes each step with policy checks
        3. Records all results
        4. Returns a summary

        Args:
            plan: The plan to execute
            policy: The policy to enforce
            fail_fast: Stop on first denial or error (default: True)

        Returns:
            RunResult with execution summary
        """
        start_time = datetime.now(UTC)
        global_timeout_seconds = policy.global_timeout_seconds

        # Create policy engine
        policy_engine = PolicyEngine(policy)

        # Create run record
        run_id = self.db.create_run(plan, policy, mode=RunMode.RUN)

        # Execute steps
        steps: list[StepResult] = []
        completed = 0
        denied = 0
        failed = 0
        timed_out = False

        for step_index, step in enumerate(plan.steps):
            # Check global timeout before each step
            elapsed_seconds = (datetime.now(UTC) - start_time).total_seconds()
            if elapsed_seconds >= global_timeout_seconds:
                timed_out = True
                # Record a timeout result for this step
                timeout_result = StepResult(
                    step_index=step_index,
                    tool_name=step.tool,
                    args=step.args,
                    status=ToolCallStatus.ERROR,
                    error=f"Global timeout exceeded: {elapsed_seconds:.1f}s >= {global_timeout_seconds}s",
                    policy_decision=PolicyDecision.deny(
                        f"Global timeout exceeded after {elapsed_seconds:.1f}s",
                        rule="global_timeout_seconds",
                    ),
                )
                steps.append(timeout_result)
                failed += 1
                break

            step_result = self._execute_step(
                run_id=run_id,
                step_index=step_index,
                tool_name=step.tool,
                args=step.args,
                policy_engine=policy_engine,
            )
            steps.append(step_result)

            # Update counters
            if step_result.status == ToolCallStatus.SUCCESS:
                completed += 1
            elif step_result.status == ToolCallStatus.DENIED:
                denied += 1
                if fail_fast:
                    break
            elif step_result.status == ToolCallStatus.ERROR:
                failed += 1
                if fail_fast:
                    break

        # Determine final status
        if denied > 0 or failed > 0 or timed_out:
            final_status = RunStatus.FAILED
        else:
            final_status = RunStatus.COMPLETED

        # Update run record
        self.db.update_run_status(
            run_id=run_id,
            status=final_status,
            completed_steps=completed,
            denied_steps=denied,
            failed_steps=failed,
        )

        end_time = datetime.now(UTC)
        duration_ms = (end_time - start_time).total_seconds() * 1000

        return RunResult(
            run_id=run_id,
            status=final_status,
            steps=steps,
            total_steps=len(plan.steps),
            completed_steps=completed,
            denied_steps=denied,
            failed_steps=failed,
            duration_ms=duration_ms,
        )

    def _execute_step(
        self,
        run_id: str,
        step_index: int,
        tool_name: str,
        args: dict[str, Any],
        policy_engine: PolicyEngine,
    ) -> StepResult:
        """
        Execute a single step with policy check.

        Args:
            run_id: The run this step belongs to
            step_index: Position in the plan
            tool_name: Name of the tool to execute
            args: Arguments for the tool
            policy_engine: Policy engine for evaluation

        Returns:
            StepResult with execution outcome
        """
        start_time = datetime.now(UTC)

        # Record the call
        call_id = self.db.record_call(run_id, step_index, tool_name, args)

        # Check policy
        decision = policy_engine.evaluate(tool_name, args, self.working_dir)

        if not decision.allowed:
            # Policy denied - record and return
            end_time = datetime.now(UTC)
            self.db.record_result(
                call_id=call_id,
                run_id=run_id,
                status=ToolCallStatus.DENIED,
                output=None,
                error=None,
                policy_decision=decision,
                started_at=start_time,
                ended_at=end_time,
                input_data=args,
            )
            duration_ms = (end_time - start_time).total_seconds() * 1000
            return StepResult(
                step_index=step_index,
                tool_name=tool_name,
                args=args,
                status=ToolCallStatus.DENIED,
                policy_decision=decision,
                duration_ms=duration_ms,
            )

        # Get the tool
        try:
            tool = self.registry.get(tool_name)
        except ToolNotFoundError:
            end_time = datetime.now(UTC)
            error_msg = f"Tool not found: {tool_name}"
            self.db.record_result(
                call_id=call_id,
                run_id=run_id,
                status=ToolCallStatus.ERROR,
                output=None,
                error=error_msg,
                policy_decision=decision,
                started_at=start_time,
                ended_at=end_time,
                input_data=args,
            )
            duration_ms = (end_time - start_time).total_seconds() * 1000
            return StepResult(
                step_index=step_index,
                tool_name=tool_name,
                args=args,
                status=ToolCallStatus.ERROR,
                error=error_msg,
                policy_decision=decision,
                duration_ms=duration_ms,
            )

        # Execute the tool
        context = ToolContext(
            run_id=run_id,
            policy=policy_engine.policy,
            working_dir=self.working_dir,
        )

        try:
            output = tool.execute(args, context)
        except Exception as e:
            # Unexpected error during execution
            end_time = datetime.now(UTC)
            error_msg = f"Tool execution failed: {e}"
            self.db.record_result(
                call_id=call_id,
                run_id=run_id,
                status=ToolCallStatus.ERROR,
                output=None,
                error=error_msg,
                policy_decision=decision,
                started_at=start_time,
                ended_at=end_time,
                input_data=args,
            )
            duration_ms = (end_time - start_time).total_seconds() * 1000
            return StepResult(
                step_index=step_index,
                tool_name=tool_name,
                args=args,
                status=ToolCallStatus.ERROR,
                error=error_msg,
                policy_decision=decision,
                duration_ms=duration_ms,
            )

        end_time = datetime.now(UTC)
        duration_ms = (end_time - start_time).total_seconds() * 1000

        # Determine status based on tool output
        if output.success:
            status = ToolCallStatus.SUCCESS
            self.db.record_result(
                call_id=call_id,
                run_id=run_id,
                status=status,
                output=output.data,
                error=None,
                policy_decision=decision,
                started_at=start_time,
                ended_at=end_time,
                input_data=args,
            )
            return StepResult(
                step_index=step_index,
                tool_name=tool_name,
                args=args,
                status=status,
                output=output.data,
                policy_decision=decision,
                duration_ms=duration_ms,
            )
        else:
            status = ToolCallStatus.ERROR
            self.db.record_result(
                call_id=call_id,
                run_id=run_id,
                status=status,
                output=None,
                error=output.error,
                policy_decision=decision,
                started_at=start_time,
                ended_at=end_time,
                input_data=args,
            )
            return StepResult(
                step_index=step_index,
                tool_name=tool_name,
                args=args,
                status=status,
                error=output.error,
                policy_decision=decision,
                duration_ms=duration_ms,
            )

    def get_run_summary(self, run_id: str) -> dict[str, Any] | None:
        """
        Get a summary of a previous run.

        Args:
            run_id: The run to summarize

        Returns:
            Dictionary with run metadata, calls, and results
        """
        return self.db.get_run_summary(run_id)

    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        List recent runs.

        Args:
            limit: Maximum number of runs to return

        Returns:
            List of run summaries
        """
        runs = self.db.list_runs(limit)
        return [
            {
                "run_id": r.run_id,
                "created_at": r.created_at.isoformat(),
                "status": r.status.value,
                "mode": r.mode.value,
                "total_steps": r.total_steps,
                "completed_steps": r.completed_steps,
                "denied_steps": r.denied_steps,
                "failed_steps": r.failed_steps,
            }
            for r in runs
        ]
