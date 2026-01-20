"""
Replay module for Capsule.

This module enables deterministic replay of past executions.
Replays return stored results instead of executing tools.

Use cases:
    - Reproduce exact behavior from a previous run
    - Debug issues by re-examining past executions
    - Verify that plans produce consistent results
    - Demo capabilities without actual tool execution

How it works:
    1. Load the original run from the database
    2. Verify the plan matches the original (by hash)
    3. For each step, return the stored result
    4. Detect and report any mismatches

Replays are stored as new runs with mode='replay', creating
a full audit trail of both original and replayed executions.

Example:
    from capsule.replay import ReplayEngine

    with ReplayEngine("capsule.db") as engine:
        result = engine.replay("abc123")
        print(f"Replayed {result.total_steps} steps")
        for step in result.steps:
            print(f"  {step.tool_name}: {step.status.value}")
"""

from capsule.replay.engine import ReplayEngine, ReplayResult, ReplayStepResult

__all__ = [
    "ReplayEngine",
    "ReplayResult",
    "ReplayStepResult",
]
