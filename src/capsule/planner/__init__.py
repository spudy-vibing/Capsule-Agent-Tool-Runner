"""
Planner module for Capsule.

This module provides the interface and implementations for SLM-based planning.
The planner generates tool call proposals based on a task description and
previous execution history.

Components:
    - Planner: Abstract base class for all planners
    - PlannerState: State passed to planner on each iteration
    - Done: Sentinel indicating the agent loop should terminate
    - OllamaPlanner: Planner implementation using Ollama

Usage:
    from capsule.planner import OllamaPlanner, PlannerState, Done

    planner = OllamaPlanner(config)
    state = PlannerState(task="...", tool_schemas=[...], ...)

    result = planner.propose_next(state, last_result=None)
    if isinstance(result, Done):
        print("Task complete:", result.reason)
    else:
        # result is a ToolCall to execute
        pass
"""

from capsule.planner.base import Done, Planner, PlannerState
from capsule.planner.ollama import OllamaPlanner

__all__ = [
    "Done",
    "OllamaPlanner",
    "Planner",
    "PlannerState",
]
