"""
Replay Engine for Capsule.

The ReplayEngine enables deterministic replay of past executions.
Instead of executing tools, it returns the stored results from the original run.

Use cases:
    - Reproduce exact behavior from a previous run
    - Debug issues by re-examining past executions
    - Verify that plans produce consistent results
    - Demo capabilities without actual tool execution

Design Principles:
    - Bit-exact: Replays return exactly what was stored
    - Verifiable: Plan hashes are checked to detect modifications
    - Auditable: Replays are stored as new runs with mode='replay'
    - Fail-safe: Mismatches are clearly reported
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from capsule.errors import (
    ReplayMismatchError,
    ReplayRunNotFoundError,
)
from capsule.schema import (
    Plan,
    Policy,
    PolicyDecision,
    RunMode,
    RunStatus,
    ToolCallStatus,
)
from capsule.store import CapsuleDB
from capsule.store.db import compute_hash


@dataclass
class ReplayStepResult:
    """
    Result of replaying a single step.

    Attributes:
        step_index: Position in the plan
        tool_name: Name of the tool
        args: Arguments that were passed
        status: Outcome status from original run
        output: Output data from original run
        error: Error message from original run
        policy_decision: The policy decision from original run
        original_call_id: Call ID from the original run
        input_hash: Hash of the input
        output_hash: Hash of the output
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
    original_call_id: str = ""
    input_hash: str = ""
    output_hash: str = ""


@dataclass
class ReplayResult:
    """
    Result of replaying a complete run.

    Attributes:
        replay_run_id: ID of this replay run
        original_run_id: ID of the run being replayed
        status: Final status of the replay
        steps: Results for each step (from stored data)
        total_steps: Number of steps replayed
        completed_steps: Steps that were successful in original
        denied_steps: Steps that were denied in original
        failed_steps: Steps that failed in original
        plan_verified: Whether plan hash matched
        mismatches: List of any detected mismatches
    """

    replay_run_id: str
    original_run_id: str
    status: RunStatus
    steps: list[ReplayStepResult]
    total_steps: int = 0
    completed_steps: int = 0
    denied_steps: int = 0
    failed_steps: int = 0
    plan_verified: bool = True
    mismatches: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Whether the replay completed without mismatches."""
        return self.status == RunStatus.COMPLETED and len(self.mismatches) == 0


class ReplayEngine:
    """
    Engine for replaying previous Capsule runs.

    The ReplayEngine loads stored results from a previous run and
    returns them without re-executing any tools. This enables:
    - Deterministic reproduction of past behavior
    - Debugging without side effects
    - Verification of stored results

    Usage:
        engine = ReplayEngine(db_path="capsule.db")
        result = engine.replay("abc123")
        print(f"Replayed {result.total_steps} steps")

    Attributes:
        db: Database connection for loading/storing results
    """

    def __init__(self, db_path: str | Path = "capsule.db") -> None:
        """
        Initialize the replay engine.

        Args:
            db_path: Path to SQLite database
        """
        self.db = CapsuleDB(db_path)

    def close(self) -> None:
        """Close database connection."""
        self.db.close()

    def __enter__(self) -> "ReplayEngine":
        """Enter context manager."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Exit context manager."""
        self.close()

    def replay(
        self,
        run_id: str,
        verify_plan: bool = True,
        plan: Plan | None = None,
        policy: Policy | None = None,
    ) -> ReplayResult:
        """
        Replay a previous run.

        This loads the stored results from a previous run and returns
        them without re-executing any tools. Optionally verifies that
        the provided plan matches the original.

        Args:
            run_id: ID of the run to replay
            verify_plan: Whether to verify plan hash matches (default: True)
            plan: Optional plan to verify against (loads from DB if not provided)
            policy: Optional policy (loads from DB if not provided)

        Returns:
            ReplayResult with all stored results

        Raises:
            ReplayRunNotFoundError: If run doesn't exist
            ReplayMismatchError: If verify_plan=True and plan doesn't match
        """
        # Load the original run
        original_run = self.db.get_run(run_id)
        if original_run is None:
            raise ReplayRunNotFoundError(run_id=run_id)

        # Load original plan and policy from DB
        original_plan = self.db.get_run_plan(run_id)
        original_policy = self.db.get_run_policy(run_id)

        if original_plan is None or original_policy is None:
            raise ReplayRunNotFoundError(
                run_id=run_id,
                message=f"Run {run_id} exists but plan/policy data is missing",
            )

        # Use provided plan/policy or fall back to stored ones
        replay_plan = plan if plan is not None else original_plan
        replay_policy = policy if policy is not None else original_policy

        mismatches: list[str] = []
        plan_verified = True

        # Verify plan hash if requested
        if verify_plan and plan is not None:
            plan_json = plan.model_dump_json()
            plan_hash = compute_hash(plan_json)
            if plan_hash != original_run.plan_hash:
                plan_verified = False
                mismatches.append(
                    f"Plan hash mismatch: original={original_run.plan_hash[:8]}..., "
                    f"provided={plan_hash[:8]}..."
                )

        # Create a new run record for this replay
        replay_run_id = self.db.create_run(
            replay_plan,
            replay_policy,
            mode=RunMode.REPLAY,
        )

        # Load stored calls and results
        original_calls = self.db.get_calls_for_run(run_id)
        original_results = self.db.get_results_for_run(run_id)

        # Build results lookup by call_id
        results_by_call = {r.call_id: r for r in original_results}

        # Replay each step
        steps: list[ReplayStepResult] = []
        completed = 0
        denied = 0
        failed = 0

        for call in original_calls:
            result = results_by_call.get(call.call_id)

            if result is None:
                # Original run may have been interrupted
                mismatches.append(
                    f"Step {call.step_index} ({call.tool_name}): no result found"
                )
                continue

            # Record the replayed call
            replay_call_id = self.db.record_call(
                run_id=replay_run_id,
                step_index=call.step_index,
                tool_name=call.tool_name,
                args=call.args,
            )

            # Record the replayed result (using original data)
            self.db.record_result(
                call_id=replay_call_id,
                run_id=replay_run_id,
                status=result.status,
                output=result.output,
                error=result.error,
                policy_decision=result.policy_decision,
                started_at=result.started_at,
                ended_at=result.ended_at,
                input_data=call.args,
            )

            # Create step result
            step_result = ReplayStepResult(
                step_index=call.step_index,
                tool_name=call.tool_name,
                args=call.args,
                status=result.status,
                output=result.output,
                error=result.error,
                policy_decision=result.policy_decision,
                original_call_id=call.call_id,
                input_hash=result.input_hash,
                output_hash=result.output_hash,
            )
            steps.append(step_result)

            # Update counters
            if result.status == ToolCallStatus.SUCCESS:
                completed += 1
            elif result.status == ToolCallStatus.DENIED:
                denied += 1
            elif result.status == ToolCallStatus.ERROR:
                failed += 1

        # Determine final status
        if mismatches:
            final_status = RunStatus.FAILED
        elif denied > 0 or failed > 0:
            # Match original run's outcome
            final_status = RunStatus.FAILED
        else:
            final_status = RunStatus.COMPLETED

        # Update replay run record
        self.db.update_run_status(
            run_id=replay_run_id,
            status=final_status,
            completed_steps=completed,
            denied_steps=denied,
            failed_steps=failed,
        )

        return ReplayResult(
            replay_run_id=replay_run_id,
            original_run_id=run_id,
            status=final_status,
            steps=steps,
            total_steps=len(steps),
            completed_steps=completed,
            denied_steps=denied,
            failed_steps=failed,
            plan_verified=plan_verified,
            mismatches=mismatches,
        )

    def verify_run(self, run_id: str) -> dict[str, Any]:
        """
        Verify integrity of a stored run.

        Checks that all hashes are consistent and no data is missing.

        Args:
            run_id: ID of the run to verify

        Returns:
            Dictionary with verification results:
                - valid: Whether all checks passed
                - errors: List of any issues found
                - stats: Summary statistics
        """
        errors: list[str] = []

        # Load the run
        run = self.db.get_run(run_id)
        if run is None:
            return {
                "valid": False,
                "errors": [f"Run {run_id} not found"],
                "stats": {},
            }

        # Load calls and results
        calls = self.db.get_calls_for_run(run_id)
        results = self.db.get_results_for_run(run_id)

        # Check call/result counts match
        if len(calls) != len(results):
            errors.append(
                f"Call/result count mismatch: {len(calls)} calls, {len(results)} results"
            )

        # Verify step indices are sequential
        expected_indices = list(range(len(calls)))
        actual_indices = [c.step_index for c in calls]
        if actual_indices != expected_indices:
            errors.append(f"Non-sequential step indices: {actual_indices}")

        # Verify hashes
        results_by_call = {r.call_id: r for r in results}
        for call in calls:
            result = results_by_call.get(call.call_id)
            if result is None:
                errors.append(f"Missing result for call {call.call_id}")
                continue

            # Recompute input hash
            recomputed_input_hash = compute_hash(call.args)
            if recomputed_input_hash != result.input_hash:
                errors.append(
                    f"Step {call.step_index}: input hash mismatch "
                    f"(stored={result.input_hash[:8]}..., "
                    f"computed={recomputed_input_hash[:8]}...)"
                )

            # Recompute output hash
            recomputed_output_hash = compute_hash(result.output)
            if recomputed_output_hash != result.output_hash:
                errors.append(
                    f"Step {call.step_index}: output hash mismatch "
                    f"(stored={result.output_hash[:8]}..., "
                    f"computed={recomputed_output_hash[:8]}...)"
                )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "stats": {
                "run_id": run_id,
                "total_calls": len(calls),
                "total_results": len(results),
                "status": run.status.value,
                "mode": run.mode.value,
            },
        }

    def get_original_run_id(self, replay_run_id: str) -> str | None:
        """
        Get the original run ID for a replay.

        Note: This requires looking at the plan/policy hashes
        to find matching original runs. For now, returns None
        as we don't store explicit parent references.

        Args:
            replay_run_id: ID of the replay run

        Returns:
            Original run ID or None if not determinable
        """
        # Future enhancement: store original_run_id in replay runs
        return None
