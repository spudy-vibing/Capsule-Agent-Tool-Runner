"""
Storage module for Capsule.

This module provides SQLite-based persistence for runs, tool calls, and results.
All execution history is stored for audit and replay purposes.

Tables:
    - runs: Metadata about each execution (id, timestamps, status, hashes)
    - tool_calls: Record of each tool invocation (tool name, arguments)
    - tool_results: Outcomes of each call (output, errors, timing, policy decisions)

Design principles:
    - Append-only: Historical data is never modified
    - Integrity: Input/output hashes enable verification
    - Atomic: Transactions ensure consistency
    - Self-contained: Single .db file contains everything needed for replay

Why SQLite?
    - Zero configuration (no server needed)
    - ACID transactions built-in
    - Portable single-file format
    - Excellent Python support
    - Perfect for local-first tools
"""

from capsule.store.db import CapsuleDB, compute_hash, generate_id

__all__ = [
    "CapsuleDB",
    "compute_hash",
    "generate_id",
]
