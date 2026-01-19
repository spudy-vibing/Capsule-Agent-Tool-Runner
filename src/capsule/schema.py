"""
Schema definitions for Capsule.

This module defines all the Pydantic models used throughout Capsule:
- Plan/PlanStep: What actions to execute
- Policy/PolicyRule: What's allowed and what's denied
- ToolCall/ToolResult: Runtime representation of executions
- PolicyDecision: The result of policy evaluation

Design Decisions:
    - All models use strict validation (no type coercion)
    - Fields use descriptive names for self-documentation
    - Optional fields have sensible defaults
    - Models are immutable where possible (frozen=True)

Why Pydantic?
    - Type safety with runtime validation
    - Automatic JSON/YAML serialization
    - Clear error messages for invalid data
    - IDE support for autocomplete
"""

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# Enums
# =============================================================================


class PolicyBoundary(str, Enum):
    """
    The default policy behavior.

    DENY_BY_DEFAULT means all actions are blocked unless explicitly allowed.
    This is the only secure default - we don't support ALLOW_BY_DEFAULT.
    """

    DENY_BY_DEFAULT = "deny_by_default"


class ToolCallStatus(str, Enum):
    """Status of a tool call execution."""

    PENDING = "pending"
    SUCCESS = "success"
    ERROR = "error"
    DENIED = "denied"


class RunMode(str, Enum):
    """Mode of execution for a run."""

    RUN = "run"
    REPLAY = "replay"


class RunStatus(str, Enum):
    """Overall status of a run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# =============================================================================
# Plan Models
# =============================================================================


class PlanStep(BaseModel):
    """
    A single step in a plan.

    Each step represents one tool invocation with its arguments.
    Steps are executed sequentially in the order they appear.

    Attributes:
        tool: The tool identifier (e.g., "fs.read", "shell.run")
        args: Arguments to pass to the tool (tool-specific)
        id: Optional unique identifier for this step (auto-generated if not provided)
        name: Optional human-readable name for this step
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str = Field(
        ...,
        description="Tool identifier (e.g., 'fs.read', 'shell.run')",
        min_length=1,
    )
    args: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments to pass to the tool",
    )
    id: str | None = Field(
        default=None,
        description="Optional unique identifier for this step",
    )
    name: str | None = Field(
        default=None,
        description="Optional human-readable name for this step",
    )

    @field_validator("tool")
    @classmethod
    def validate_tool_format(cls, v: str) -> str:
        """Validate tool name format (namespace.action or just action)."""
        # Tool names should be alphanumeric with dots/underscores
        parts = v.split(".")
        for part in parts:
            if not part.replace("_", "").isalnum():
                msg = f"Invalid tool name format: {v}"
                raise ValueError(msg)
        return v


class Plan(BaseModel):
    """
    A complete execution plan.

    Plans define a sequence of tool calls to execute.
    They are validated before execution and hashed for replay verification.

    Attributes:
        version: Schema version for forward compatibility
        steps: Ordered list of steps to execute
        name: Optional name for this plan
        description: Optional description of what this plan does
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(
        default="1.0",
        description="Plan schema version",
    )
    steps: list[PlanStep] = Field(
        ...,
        description="Ordered list of steps to execute",
        min_length=1,
    )
    name: str | None = Field(
        default=None,
        description="Optional name for this plan",
    )
    description: str | None = Field(
        default=None,
        description="Optional description of what this plan does",
    )


# =============================================================================
# Policy Models
# =============================================================================


class FsPolicy(BaseModel):
    """
    Policy rules for filesystem tools (fs.read, fs.write).

    Attributes:
        allow_paths: Glob patterns for allowed paths (e.g., ["./**", "/tmp/**"])
        deny_paths: Glob patterns for denied paths (takes precedence over allow)
        max_size_bytes: Maximum file size in bytes
        allow_hidden: Whether to allow hidden files (dotfiles). Default: False
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    allow_paths: list[str] = Field(
        default_factory=list,
        description="Glob patterns for allowed paths",
    )
    deny_paths: list[str] = Field(
        default_factory=list,
        description="Glob patterns for denied paths (takes precedence)",
    )
    max_size_bytes: int = Field(
        default=10 * 1024 * 1024,  # 10 MB
        description="Maximum file size in bytes (0 = disabled/blocked)",
        ge=0,
    )
    allow_hidden: bool = Field(
        default=False,
        description="Whether to allow hidden files (dotfiles)",
    )


class HttpPolicy(BaseModel):
    """
    Policy rules for HTTP tools (http.get).

    Attributes:
        allow_domains: List of allowed domains (e.g., ["api.github.com"])
        deny_private_ips: Whether to block private IP ranges. Default: True
        max_response_bytes: Maximum response body size
        timeout_seconds: Request timeout in seconds
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    allow_domains: list[str] = Field(
        default_factory=list,
        description="List of allowed domains",
    )
    deny_private_ips: bool = Field(
        default=True,
        description="Whether to block private IP ranges",
    )
    max_response_bytes: int = Field(
        default=10 * 1024 * 1024,  # 10 MB
        description="Maximum response body size (0 = disabled/blocked)",
        ge=0,
    )
    timeout_seconds: int = Field(
        default=30,
        description="Request timeout in seconds",
        gt=0,
        le=300,
    )


class ShellPolicy(BaseModel):
    """
    Policy rules for shell tools (shell.run).

    Attributes:
        allow_executables: List of allowed executable names (e.g., ["git", "echo"])
        deny_tokens: List of blocked tokens in arguments (e.g., ["sudo", "rm -rf"])
        timeout_seconds: Command execution timeout
        max_output_bytes: Maximum combined stdout/stderr size
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    allow_executables: list[str] = Field(
        default_factory=list,
        description="List of allowed executable names",
    )
    deny_tokens: list[str] = Field(
        default_factory=lambda: [
            "sudo",
            "su",
            "rm -rf",
            "mkfs",
            "dd",
            "> /dev",
            "chmod 777",
            "curl | sh",
            "wget | sh",
        ],
        description="List of blocked tokens in arguments",
    )
    timeout_seconds: int = Field(
        default=60,
        description="Command execution timeout",
        gt=0,
        le=600,
    )
    max_output_bytes: int = Field(
        default=1024 * 1024,  # 1 MB
        description="Maximum combined stdout/stderr size",
        gt=0,
    )


class ToolPolicies(BaseModel):
    """
    Container for all tool-specific policies.

    Attributes:
        fs_read: Policy for fs.read tool
        fs_write: Policy for fs.write tool
        http_get: Policy for http.get tool
        shell_run: Policy for shell.run tool
    """

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    # Using aliases to match YAML format (fs.read -> fs_read)
    fs_read: FsPolicy = Field(
        default_factory=FsPolicy,
        alias="fs.read",
        description="Policy for fs.read tool",
    )
    fs_write: FsPolicy = Field(
        default_factory=FsPolicy,
        alias="fs.write",
        description="Policy for fs.write tool",
    )
    http_get: HttpPolicy = Field(
        default_factory=HttpPolicy,
        alias="http.get",
        description="Policy for http.get tool",
    )
    shell_run: ShellPolicy = Field(
        default_factory=ShellPolicy,
        alias="shell.run",
        description="Policy for shell.run tool",
    )


class Policy(BaseModel):
    """
    Complete policy configuration.

    Policies define what actions are allowed and denied.
    The boundary is always deny-by-default for security.

    Attributes:
        boundary: Default behavior (always deny_by_default)
        tools: Tool-specific policy configurations
        global_timeout_seconds: Maximum total run duration
        max_calls_per_tool: Maximum calls per tool type (quota)
    """

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    boundary: PolicyBoundary = Field(
        default=PolicyBoundary.DENY_BY_DEFAULT,
        description="Default policy behavior",
    )
    tools: ToolPolicies = Field(
        default_factory=ToolPolicies,
        description="Tool-specific policy configurations",
    )
    global_timeout_seconds: int = Field(
        default=300,  # 5 minutes
        description="Maximum total run duration",
        gt=0,
    )
    max_calls_per_tool: int = Field(
        default=100,
        description="Maximum calls per tool type (quota)",
        gt=0,
    )


# =============================================================================
# Runtime Models
# =============================================================================


class PolicyDecision(BaseModel):
    """
    Result of evaluating a tool call against the policy.

    Every tool call is checked against the policy before execution.
    This model captures the decision and the reason for it.

    Attributes:
        allowed: Whether the action is permitted
        reason: Human-readable explanation of the decision
        rule_matched: Which policy rule caused this decision
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool = Field(
        ...,
        description="Whether the action is permitted",
    )
    reason: str = Field(
        ...,
        description="Human-readable explanation of the decision",
    )
    rule_matched: str | None = Field(
        default=None,
        description="Which policy rule caused this decision",
    )

    @classmethod
    def allow(cls, reason: str, rule: str | None = None) -> "PolicyDecision":
        """Create an ALLOW decision."""
        return cls(allowed=True, reason=reason, rule_matched=rule)

    @classmethod
    def deny(cls, reason: str, rule: str | None = None) -> "PolicyDecision":
        """Create a DENY decision."""
        return cls(allowed=False, reason=reason, rule_matched=rule)


class ToolCall(BaseModel):
    """
    A recorded tool invocation.

    This captures all information about a tool call, including
    its position in the plan and the arguments used.

    Attributes:
        call_id: Unique identifier for this call
        run_id: ID of the run this call belongs to
        step_index: Position in the plan (0-indexed)
        tool_name: Name of the tool
        args: Arguments passed to the tool
        created_at: When this call was created
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: str = Field(..., description="Unique identifier for this call")
    run_id: str = Field(..., description="ID of the run this call belongs to")
    step_index: int = Field(..., description="Position in the plan (0-indexed)", ge=0)
    tool_name: str = Field(..., description="Name of the tool")
    args: dict[str, Any] = Field(default_factory=dict, description="Arguments passed")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this call was created",
    )


class ToolResult(BaseModel):
    """
    The outcome of a tool execution.

    Captures everything about what happened when a tool was executed
    (or denied), including timing and hashes for verification.

    Attributes:
        call_id: ID of the tool call this result is for
        run_id: ID of the run
        status: Outcome status (success, error, denied)
        output: Output data from the tool (if successful)
        error: Error information (if failed)
        policy_decision: The policy decision that was made
        started_at: When execution started
        ended_at: When execution ended
        input_hash: SHA256 hash of input for verification
        output_hash: SHA256 hash of output for verification
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: str = Field(..., description="ID of the tool call")
    run_id: str = Field(..., description="ID of the run")
    status: ToolCallStatus = Field(..., description="Outcome status")
    output: Any | None = Field(default=None, description="Output data from the tool")
    error: str | None = Field(default=None, description="Error information if failed")
    policy_decision: PolicyDecision = Field(..., description="The policy decision made")
    started_at: datetime = Field(..., description="When execution started")
    ended_at: datetime = Field(..., description="When execution ended")
    input_hash: str = Field(..., description="SHA256 hash of input")
    output_hash: str = Field(..., description="SHA256 hash of output")


class Run(BaseModel):
    """
    Metadata about an execution run.

    A run represents a complete execution of a plan under a policy.
    It contains metadata but not the individual results (those are in ToolResult).

    Attributes:
        run_id: Unique identifier for this run
        created_at: When the run started
        completed_at: When the run finished (None if still running)
        plan_hash: SHA256 hash of the plan for verification
        policy_hash: SHA256 hash of the policy for verification
        mode: Whether this is a fresh run or a replay
        status: Current status of the run
        total_steps: Number of steps in the plan
        completed_steps: Number of steps completed
        denied_steps: Number of steps denied by policy
        failed_steps: Number of steps that failed
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="Unique identifier for this run")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the run started",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="When the run finished",
    )
    plan_hash: str = Field(..., description="SHA256 hash of the plan")
    policy_hash: str = Field(..., description="SHA256 hash of the policy")
    mode: RunMode = Field(default=RunMode.RUN, description="Execution mode")
    status: RunStatus = Field(default=RunStatus.PENDING, description="Run status")
    total_steps: int = Field(default=0, description="Number of steps in plan", ge=0)
    completed_steps: int = Field(default=0, description="Steps completed", ge=0)
    denied_steps: int = Field(default=0, description="Steps denied", ge=0)
    failed_steps: int = Field(default=0, description="Steps failed", ge=0)


# =============================================================================
# YAML Loading Helpers
# =============================================================================


def load_plan(path: Path | str) -> Plan:
    """
    Load a plan from a YAML file.

    Args:
        path: Path to the YAML file

    Returns:
        Validated Plan object

    Raises:
        FileNotFoundError: If the file doesn't exist
        ValidationError: If the YAML doesn't match the schema
    """
    path = Path(path)
    with path.open() as f:
        data = yaml.safe_load(f)

    return Plan.model_validate(data)


def load_policy(path: Path | str) -> Policy:
    """
    Load a policy from a YAML file.

    Args:
        path: Path to the YAML file

    Returns:
        Validated Policy object

    Raises:
        FileNotFoundError: If the file doesn't exist
        ValidationError: If the YAML doesn't match the schema
    """
    path = Path(path)
    with path.open() as f:
        data = yaml.safe_load(f)

    return Policy.model_validate(data)


def load_plan_from_string(content: str) -> Plan:
    """Load a plan from a YAML string."""
    data = yaml.safe_load(content)
    return Plan.model_validate(data)


def load_policy_from_string(content: str) -> Policy:
    """Load a policy from a YAML string."""
    data = yaml.safe_load(content)
    return Policy.model_validate(data)
