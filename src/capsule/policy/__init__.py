"""
Policy Engine module for Capsule.

This module implements the core security model: deny-by-default policy enforcement.
All tool calls must pass through the policy engine before execution.

Key concepts:
    - Deny-by-default: Everything is blocked unless explicitly allowed
    - PolicyDecision: The result of evaluating a tool call (ALLOW/DENY + reason)
    - PolicyEngine: Central evaluator that checks tool calls against rules

The policy engine is the security boundary of Capsule. It must be:
    - Fail-closed: Any error results in denial
    - Predictable: Same inputs always produce same decisions
    - Auditable: All decisions are logged with reasons
"""

from capsule.policy.engine import PolicyEngine

__all__ = [
    "PolicyEngine",
]
