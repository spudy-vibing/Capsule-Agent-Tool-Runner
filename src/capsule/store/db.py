"""
SQLite storage for Capsule.

This module provides persistent storage for runs, tool calls, and results.
All execution history is stored in a single SQLite database file.

Design Principles:
    - Append-only: Historical data is never modified
    - Integrity: Input/output hashes enable verification
    - Atomic: Transactions ensure consistency
    - Self-contained: Single .db file contains everything

Tables:
    - runs: Metadata about each execution run
    - tool_calls: Record of each tool invocation
    - tool_results: Outcomes of each tool call

Why SQLite?
    - Zero configuration (no server needed)
    - ACID transactions built-in
    - Portable single-file format
    - Excellent Python support via sqlite3
"""

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generator

from capsule.errors import StorageConnectionError, StorageReadError, StorageWriteError
from capsule.schema import (
    Plan,
    Policy,
    PolicyDecision,
    Run,
    RunMode,
    RunStatus,
    ToolCall,
    ToolCallStatus,
    ToolResult,
)

# Schema version for migrations
SCHEMA_VERSION = 1

# SQL for creating tables
CREATE_TABLES_SQL = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- Runs table: metadata about each execution
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    plan_hash TEXT NOT NULL,
    policy_hash TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'run',
    status TEXT NOT NULL DEFAULT 'pending',
    total_steps INTEGER NOT NULL DEFAULT 0,
    completed_steps INTEGER NOT NULL DEFAULT 0,
    denied_steps INTEGER NOT NULL DEFAULT 0,
    failed_steps INTEGER NOT NULL DEFAULT 0
);

-- Tool calls table: record of each invocation
CREATE TABLE IF NOT EXISTS tool_calls (
    call_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    args_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

-- Tool results table: outcomes of each call
CREATE TABLE IF NOT EXISTS tool_results (
    call_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    output_json TEXT,
    error TEXT,
    policy_decision_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    output_hash TEXT NOT NULL,
    FOREIGN KEY (call_id) REFERENCES tool_calls(call_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_tool_calls_run_id ON tool_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_tool_results_run_id ON tool_results(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at);
"""


def generate_id() -> str:
    """Generate a unique ID for runs and calls."""
    return str(uuid.uuid4())[:8]


def compute_hash(data: Any) -> str:
    """Compute SHA256 hash of data."""
    if data is None:
        return ""
    if isinstance(data, str):
        content = data.encode("utf-8")
    elif isinstance(data, bytes):
        content = data
    else:
        content = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def now_iso() -> str:
    """Get current UTC time in ISO format."""
    return datetime.now(UTC).isoformat()


class CapsuleDB:
    """
    SQLite database for Capsule storage.

    This class manages all database operations for storing and retrieving
    runs, tool calls, and results.

    Usage:
        db = CapsuleDB("capsule.db")
        run_id = db.create_run(plan, policy)
        db.record_call(run_id, 0, "fs.read", {"path": "./file"})
        db.record_result(call_id, ...)
        db.close()

    Or use as context manager:
        with CapsuleDB("capsule.db") as db:
            ...
    """

    def __init__(self, db_path: str | Path) -> None:
        """
        Initialize the database connection.

        Args:
            db_path: Path to the SQLite database file.
                     Will be created if it doesn't exist.
        """
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._connect()
        self._init_schema()

    def _connect(self) -> None:
        """Establish database connection."""
        try:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            # Enable foreign keys
            self._conn.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error as e:
            raise StorageConnectionError(
                db_path=str(self.db_path),
                operation="connect",
                message=f"Failed to connect to database: {e}",
            ) from e

    def _init_schema(self) -> None:
        """Initialize database schema if needed."""
        try:
            cursor = self._conn.executescript(CREATE_TABLES_SQL)
            cursor.close()

            # Check/set schema version
            cursor = self._conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, now_iso()),
                )
            self._conn.commit()
        except sqlite3.Error as e:
            raise StorageWriteError(
                operation="init_schema",
                underlying_error=str(e),
            ) from e

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """Context manager for database transactions."""
        try:
            yield
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "CapsuleDB":
        """Enter context manager."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Exit context manager."""
        self.close()

    # =========================================================================
    # Run Operations
    # =========================================================================

    def create_run(
        self,
        plan: Plan,
        policy: Policy,
        mode: RunMode = RunMode.RUN,
    ) -> str:
        """
        Create a new run record.

        Args:
            plan: The plan being executed
            policy: The policy being enforced
            mode: Run mode (run or replay)

        Returns:
            The generated run_id
        """
        run_id = generate_id()
        plan_json = plan.model_dump_json()
        policy_json = policy.model_dump_json()
        plan_hash = compute_hash(plan_json)
        policy_hash = compute_hash(policy_json)

        try:
            self._conn.execute(
                """
                INSERT INTO runs (
                    run_id, created_at, plan_hash, policy_hash,
                    plan_json, policy_json, mode, status, total_steps
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    now_iso(),
                    plan_hash,
                    policy_hash,
                    plan_json,
                    policy_json,
                    mode.value,
                    RunStatus.RUNNING.value,
                    len(plan.steps),
                ),
            )
            self._conn.commit()
            return run_id
        except sqlite3.Error as e:
            raise StorageWriteError(
                operation="create_run",
                underlying_error=str(e),
            ) from e

    def get_run(self, run_id: str) -> Run | None:
        """
        Get a run by ID.

        Args:
            run_id: The run ID to look up

        Returns:
            Run object or None if not found
        """
        try:
            cursor = self._conn.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            return Run(
                run_id=row["run_id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                completed_at=(
                    datetime.fromisoformat(row["completed_at"])
                    if row["completed_at"]
                    else None
                ),
                plan_hash=row["plan_hash"],
                policy_hash=row["policy_hash"],
                mode=RunMode(row["mode"]),
                status=RunStatus(row["status"]),
                total_steps=row["total_steps"],
                completed_steps=row["completed_steps"],
                denied_steps=row["denied_steps"],
                failed_steps=row["failed_steps"],
            )
        except sqlite3.Error as e:
            raise StorageReadError(
                operation="get_run",
                underlying_error=str(e),
            ) from e

    def list_runs(self, limit: int = 100) -> list[Run]:
        """
        List recent runs.

        Args:
            limit: Maximum number of runs to return

        Returns:
            List of Run objects, most recent first
        """
        try:
            cursor = self._conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            runs = []
            for row in cursor:
                runs.append(
                    Run(
                        run_id=row["run_id"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        completed_at=(
                            datetime.fromisoformat(row["completed_at"])
                            if row["completed_at"]
                            else None
                        ),
                        plan_hash=row["plan_hash"],
                        policy_hash=row["policy_hash"],
                        mode=RunMode(row["mode"]),
                        status=RunStatus(row["status"]),
                        total_steps=row["total_steps"],
                        completed_steps=row["completed_steps"],
                        denied_steps=row["denied_steps"],
                        failed_steps=row["failed_steps"],
                    )
                )
            return runs
        except sqlite3.Error as e:
            raise StorageReadError(
                operation="list_runs",
                underlying_error=str(e),
            ) from e

    def update_run_status(
        self,
        run_id: str,
        status: RunStatus,
        completed_steps: int | None = None,
        denied_steps: int | None = None,
        failed_steps: int | None = None,
    ) -> None:
        """
        Update run status and counters.

        Args:
            run_id: The run to update
            status: New status
            completed_steps: Number of completed steps (optional)
            denied_steps: Number of denied steps (optional)
            failed_steps: Number of failed steps (optional)
        """
        try:
            updates = ["status = ?"]
            params: list[Any] = [status.value]

            if status in (RunStatus.COMPLETED, RunStatus.FAILED):
                updates.append("completed_at = ?")
                params.append(now_iso())

            if completed_steps is not None:
                updates.append("completed_steps = ?")
                params.append(completed_steps)

            if denied_steps is not None:
                updates.append("denied_steps = ?")
                params.append(denied_steps)

            if failed_steps is not None:
                updates.append("failed_steps = ?")
                params.append(failed_steps)

            params.append(run_id)

            self._conn.execute(
                f"UPDATE runs SET {', '.join(updates)} WHERE run_id = ?",
                params,
            )
            self._conn.commit()
        except sqlite3.Error as e:
            raise StorageWriteError(
                operation="update_run_status",
                underlying_error=str(e),
            ) from e

    def get_run_plan(self, run_id: str) -> Plan | None:
        """Get the plan for a run."""
        try:
            cursor = self._conn.execute(
                "SELECT plan_json FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return Plan.model_validate_json(row["plan_json"])
        except sqlite3.Error as e:
            raise StorageReadError(
                operation="get_run_plan",
                underlying_error=str(e),
            ) from e

    def get_run_policy(self, run_id: str) -> Policy | None:
        """Get the policy for a run."""
        try:
            cursor = self._conn.execute(
                "SELECT policy_json FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return Policy.model_validate_json(row["policy_json"])
        except sqlite3.Error as e:
            raise StorageReadError(
                operation="get_run_policy",
                underlying_error=str(e),
            ) from e

    # =========================================================================
    # Tool Call Operations
    # =========================================================================

    def record_call(
        self,
        run_id: str,
        step_index: int,
        tool_name: str,
        args: dict[str, Any],
    ) -> str:
        """
        Record a tool call.

        Args:
            run_id: The run this call belongs to
            step_index: Position in the plan
            tool_name: Name of the tool
            args: Arguments passed to the tool

        Returns:
            The generated call_id
        """
        call_id = generate_id()
        args_json = json.dumps(args, default=str)

        try:
            self._conn.execute(
                """
                INSERT INTO tool_calls (
                    call_id, run_id, step_index, tool_name, args_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (call_id, run_id, step_index, tool_name, args_json, now_iso()),
            )
            self._conn.commit()
            return call_id
        except sqlite3.Error as e:
            raise StorageWriteError(
                operation="record_call",
                underlying_error=str(e),
            ) from e

    def get_calls_for_run(self, run_id: str) -> list[ToolCall]:
        """
        Get all tool calls for a run.

        Args:
            run_id: The run to get calls for

        Returns:
            List of ToolCall objects, ordered by step_index
        """
        try:
            cursor = self._conn.execute(
                """
                SELECT * FROM tool_calls
                WHERE run_id = ?
                ORDER BY step_index
                """,
                (run_id,),
            )
            calls = []
            for row in cursor:
                calls.append(
                    ToolCall(
                        call_id=row["call_id"],
                        run_id=row["run_id"],
                        step_index=row["step_index"],
                        tool_name=row["tool_name"],
                        args=json.loads(row["args_json"]),
                        created_at=datetime.fromisoformat(row["created_at"]),
                    )
                )
            return calls
        except sqlite3.Error as e:
            raise StorageReadError(
                operation="get_calls_for_run",
                underlying_error=str(e),
            ) from e

    # =========================================================================
    # Tool Result Operations
    # =========================================================================

    def record_result(
        self,
        call_id: str,
        run_id: str,
        status: ToolCallStatus,
        output: Any,
        error: str | None,
        policy_decision: PolicyDecision,
        started_at: datetime,
        ended_at: datetime,
        input_data: Any,
    ) -> None:
        """
        Record a tool result.

        Args:
            call_id: The call this result is for
            run_id: The run ID
            status: Outcome status
            output: Output data (will be JSON serialized)
            error: Error message if failed
            policy_decision: The policy decision made
            started_at: When execution started
            ended_at: When execution ended
            input_data: Input data for hash computation
        """
        output_json = json.dumps(output, default=str) if output is not None else None
        policy_decision_json = policy_decision.model_dump_json()
        input_hash = compute_hash(input_data)
        output_hash = compute_hash(output)

        try:
            self._conn.execute(
                """
                INSERT INTO tool_results (
                    call_id, run_id, status, output_json, error,
                    policy_decision_json, started_at, ended_at,
                    input_hash, output_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call_id,
                    run_id,
                    status.value,
                    output_json,
                    error,
                    policy_decision_json,
                    started_at.isoformat(),
                    ended_at.isoformat(),
                    input_hash,
                    output_hash,
                ),
            )
            self._conn.commit()
        except sqlite3.Error as e:
            raise StorageWriteError(
                operation="record_result",
                underlying_error=str(e),
            ) from e

    def get_results_for_run(self, run_id: str) -> list[ToolResult]:
        """
        Get all tool results for a run.

        Args:
            run_id: The run to get results for

        Returns:
            List of ToolResult objects
        """
        try:
            cursor = self._conn.execute(
                """
                SELECT tr.*, tc.step_index
                FROM tool_results tr
                JOIN tool_calls tc ON tr.call_id = tc.call_id
                WHERE tr.run_id = ?
                ORDER BY tc.step_index
                """,
                (run_id,),
            )
            results = []
            for row in cursor:
                policy_decision = PolicyDecision.model_validate_json(
                    row["policy_decision_json"]
                )
                results.append(
                    ToolResult(
                        call_id=row["call_id"],
                        run_id=row["run_id"],
                        status=ToolCallStatus(row["status"]),
                        output=(
                            json.loads(row["output_json"])
                            if row["output_json"]
                            else None
                        ),
                        error=row["error"],
                        policy_decision=policy_decision,
                        started_at=datetime.fromisoformat(row["started_at"]),
                        ended_at=datetime.fromisoformat(row["ended_at"]),
                        input_hash=row["input_hash"],
                        output_hash=row["output_hash"],
                    )
                )
            return results
        except sqlite3.Error as e:
            raise StorageReadError(
                operation="get_results_for_run",
                underlying_error=str(e),
            ) from e

    def get_result_for_call(self, call_id: str) -> ToolResult | None:
        """Get the result for a specific call."""
        try:
            cursor = self._conn.execute(
                "SELECT * FROM tool_results WHERE call_id = ?",
                (call_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            policy_decision = PolicyDecision.model_validate_json(
                row["policy_decision_json"]
            )
            return ToolResult(
                call_id=row["call_id"],
                run_id=row["run_id"],
                status=ToolCallStatus(row["status"]),
                output=(
                    json.loads(row["output_json"]) if row["output_json"] else None
                ),
                error=row["error"],
                policy_decision=policy_decision,
                started_at=datetime.fromisoformat(row["started_at"]),
                ended_at=datetime.fromisoformat(row["ended_at"]),
                input_hash=row["input_hash"],
                output_hash=row["output_hash"],
            )
        except sqlite3.Error as e:
            raise StorageReadError(
                operation="get_result_for_call",
                underlying_error=str(e),
            ) from e

    # =========================================================================
    # Utility Operations
    # =========================================================================

    def get_run_summary(self, run_id: str) -> dict[str, Any] | None:
        """
        Get a summary of a run including all calls and results.

        Args:
            run_id: The run to summarize

        Returns:
            Dictionary with run metadata, calls, and results
        """
        run = self.get_run(run_id)
        if run is None:
            return None

        calls = self.get_calls_for_run(run_id)
        results = self.get_results_for_run(run_id)

        # Build results lookup by call_id
        results_by_call = {r.call_id: r for r in results}

        # Combine calls with their results
        steps = []
        for call in calls:
            result = results_by_call.get(call.call_id)
            steps.append({
                "step_index": call.step_index,
                "tool": call.tool_name,
                "args": call.args,
                "status": result.status.value if result else "pending",
                "output": result.output if result else None,
                "error": result.error if result else None,
                "allowed": result.policy_decision.allowed if result else None,
                "policy_reason": result.policy_decision.reason if result else None,
            })

        return {
            "run_id": run.run_id,
            "created_at": run.created_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "status": run.status.value,
            "mode": run.mode.value,
            "total_steps": run.total_steps,
            "completed_steps": run.completed_steps,
            "denied_steps": run.denied_steps,
            "failed_steps": run.failed_steps,
            "steps": steps,
        }
