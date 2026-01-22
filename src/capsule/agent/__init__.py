"""
Capsule agent module.

This module provides the agent loop that integrates the planner with
policy evaluation and tool execution.

The agent loop implements a propose -> evaluate -> execute -> learn cycle:
1. Planner proposes the next tool call based on task and history
2. Policy engine evaluates if the call is allowed
3. If allowed, executor runs the tool
4. Result is recorded and fed back to planner

Usage:
    from capsule.agent import AgentConfig, AgentLoop, AgentResult

    loop = AgentLoop(planner, policy_engine, executor, db)
    result = loop.run("List all Python files in current directory")
"""

from capsule.agent.loop import AgentConfig, AgentLoop, AgentResult, IterationResult

__all__ = [
    "AgentConfig",
    "AgentLoop",
    "AgentResult",
    "IterationResult",
]
