"""
Capsule - Local-first runtime for executing agent tool calls under strict policy controls.

Capsule serves as the missing layer between "LLM agent frameworks" and "safe, reproducible execution."
It provides:
- Strict policy enforcement (deny-by-default)
- Full audit logging to SQLite
- Deterministic replay of past executions
- Extensible tool interface

Example usage:
    $ capsule run plan.yaml --policy policy.yaml
    $ capsule replay <run_id>
    $ capsule report <run_id>
"""

__version__ = "0.1.0"
__author__ = "Capsule Contributors"

# Public API will be exposed here as modules are implemented
__all__ = [
    "__version__",
    "__author__",
]
