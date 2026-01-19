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
"""

# Public API will be exposed here as replay module is implemented
__all__: list[str] = []
