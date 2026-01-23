"""
Exception hierarchy for Capsule.

All Capsule exceptions inherit from CapsuleError, allowing callers to catch
all Capsule-specific exceptions with a single except clause.

Exception Categories:
    - PolicyDeniedError: Tool call blocked by policy
    - ToolExecutionError: Tool failed during execution
    - PlanValidationError: Invalid plan format
    - ReplayMismatchError: Replay doesn't match original
    - StorageError: Database operation failed

Design Principles:
    - All errors have error codes for programmatic handling
    - All errors include context (tool, step, args where applicable)
    - All errors provide actionable suggestions where possible
    - Errors are designed to be both human-readable and machine-parseable
"""

from dataclasses import dataclass, field
from typing import Any


# =============================================================================
# Error Codes
# =============================================================================

# Policy errors: 1xxx
ERROR_POLICY_DENIED = 1001
ERROR_POLICY_PATH_BLOCKED = 1002
ERROR_POLICY_DOMAIN_BLOCKED = 1003
ERROR_POLICY_EXECUTABLE_BLOCKED = 1004
ERROR_POLICY_TOKEN_BLOCKED = 1005
ERROR_POLICY_SIZE_EXCEEDED = 1006
ERROR_POLICY_QUOTA_EXCEEDED = 1007
ERROR_POLICY_TIMEOUT = 1008

# Tool errors: 2xxx
ERROR_TOOL_NOT_FOUND = 2001
ERROR_TOOL_INVALID_ARGS = 2002
ERROR_TOOL_EXECUTION_FAILED = 2003
ERROR_TOOL_TIMEOUT = 2004
ERROR_TOOL_OUTPUT_EXCEEDED = 2005

# Plan errors: 3xxx
ERROR_PLAN_INVALID_FORMAT = 3001
ERROR_PLAN_EMPTY_STEPS = 3002
ERROR_PLAN_INVALID_TOOL = 3003
ERROR_PLAN_MISSING_ARGS = 3004

# Replay errors: 4xxx
ERROR_REPLAY_RUN_NOT_FOUND = 4001
ERROR_REPLAY_PLAN_MISMATCH = 4002
ERROR_REPLAY_STEP_MISMATCH = 4003
ERROR_REPLAY_HASH_MISMATCH = 4004

# Storage errors: 5xxx
ERROR_STORAGE_CONNECTION = 5001
ERROR_STORAGE_WRITE = 5002
ERROR_STORAGE_READ = 5003
ERROR_STORAGE_INTEGRITY = 5004

# Planner errors: 6xxx
ERROR_PLANNER_CONNECTION = 6001
ERROR_PLANNER_TIMEOUT = 6002
ERROR_PLANNER_PARSE = 6003
ERROR_PLANNER_INVALID_RESPONSE = 6004
ERROR_PLANNER_MODEL_NOT_FOUND = 6005

# Pack errors: 7xxx
ERROR_PACK_NOT_FOUND = 7001
ERROR_PACK_INVALID_MANIFEST = 7002
ERROR_PACK_MISSING_FILE = 7003
ERROR_PACK_INVALID_INPUT = 7004
ERROR_PACK_TOOL_NOT_AVAILABLE = 7005
ERROR_PACK_TEMPLATE_ERROR = 7006


# =============================================================================
# Base Exception
# =============================================================================


@dataclass
class CapsuleError(Exception):
    """
    Base exception for all Capsule errors.

    All Capsule exceptions inherit from this class, providing:
    - Consistent error code for programmatic handling
    - Human-readable message
    - Optional suggestion for resolution
    - Optional context dict for debugging

    Attributes:
        message: Human-readable error description
        code: Numeric error code for programmatic handling
        suggestion: Optional hint for how to resolve the error
        context: Optional dict with additional debugging info
    """

    message: str = ""
    code: int = 0
    suggestion: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """Format error for display."""
        parts = [f"[E{self.code}] {self.message}"]
        if self.suggestion:
            parts.append(f"\nSuggestion: {self.suggestion}")
        return "".join(parts)

    def __repr__(self) -> str:
        """Format error for debugging."""
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"code={self.code}, "
            f"context={self.context!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "code": self.code,
            "suggestion": self.suggestion,
            "context": self.context,
        }


# =============================================================================
# Policy Errors
# =============================================================================


@dataclass
class PolicyDeniedError(CapsuleError):
    """
    Raised when a tool call is blocked by the policy.

    This is the most common error - it means the policy did its job
    and prevented an unauthorized action.

    Attributes:
        tool: Name of the tool that was blocked
        tool_args: Arguments that were provided
        reason: Why the policy denied this action
        rule: Which policy rule caused the denial
    """

    tool: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    rule: str | None = None

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Policy denied {self.tool}: {self.reason}"
        if self.code == 0:
            self.code = ERROR_POLICY_DENIED
        self.context.update({
            "tool": self.tool,
            "tool_args": self.tool_args,
            "reason": self.reason,
            "rule": self.rule,
        })


@dataclass
class PathBlockedError(PolicyDeniedError):
    """Raised when a filesystem path is blocked by policy."""

    path: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Path blocked: {self.path}"
        if self.code == 0:
            self.code = ERROR_POLICY_PATH_BLOCKED
        if not self.suggestion:
            self.suggestion = "Add the path pattern to allow_paths in policy"
        super().__post_init__()
        self.context["path"] = self.path


@dataclass
class DomainBlockedError(PolicyDeniedError):
    """Raised when a domain is blocked by policy."""

    domain: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Domain blocked: {self.domain}"
        if self.code == 0:
            self.code = ERROR_POLICY_DOMAIN_BLOCKED
        if not self.suggestion:
            self.suggestion = "Add the domain to allow_domains in policy"
        super().__post_init__()
        self.context["domain"] = self.domain


@dataclass
class ExecutableBlockedError(PolicyDeniedError):
    """Raised when a shell executable is blocked by policy."""

    executable: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Executable blocked: {self.executable}"
        if self.code == 0:
            self.code = ERROR_POLICY_EXECUTABLE_BLOCKED
        if not self.suggestion:
            self.suggestion = "Add the executable to allow_executables in policy"
        super().__post_init__()
        self.context["executable"] = self.executable


@dataclass
class TokenBlockedError(PolicyDeniedError):
    """Raised when a blocked token is found in shell arguments."""

    token: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Blocked token in arguments: {self.token}"
        if self.code == 0:
            self.code = ERROR_POLICY_TOKEN_BLOCKED
        super().__post_init__()
        self.context["token"] = self.token


@dataclass
class SizeExceededError(PolicyDeniedError):
    """Raised when a size limit is exceeded."""

    actual_size: int = 0
    max_size: int = 0

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Size exceeded: {self.actual_size} > {self.max_size} bytes"
        if self.code == 0:
            self.code = ERROR_POLICY_SIZE_EXCEEDED
        if not self.suggestion:
            self.suggestion = "Increase max_size_bytes in policy or reduce content size"
        super().__post_init__()
        self.context.update({
            "actual_size": self.actual_size,
            "max_size": self.max_size,
        })


@dataclass
class QuotaExceededError(PolicyDeniedError):
    """Raised when tool call quota is exceeded."""

    current_count: int = 0
    max_count: int = 0

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Quota exceeded: {self.current_count} >= {self.max_count} calls"
        if self.code == 0:
            self.code = ERROR_POLICY_QUOTA_EXCEEDED
        if not self.suggestion:
            self.suggestion = "Increase max_calls_per_tool in policy"
        super().__post_init__()
        self.context.update({
            "current_count": self.current_count,
            "max_count": self.max_count,
        })


# =============================================================================
# Tool Errors
# =============================================================================


@dataclass
class ToolError(CapsuleError):
    """
    Base class for tool execution errors.

    These errors occur when a tool fails during execution,
    after passing policy checks.

    Attributes:
        tool: Name of the tool that failed
        tool_args: Arguments that were provided
    """

    tool: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        self.context.update({
            "tool": self.tool,
            "tool_args": self.tool_args,
        })


@dataclass
class ToolNotFoundError(ToolError):
    """Raised when a tool is not registered."""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Tool not found: {self.tool}"
        if self.code == 0:
            self.code = ERROR_TOOL_NOT_FOUND
        if not self.suggestion:
            self.suggestion = "Check tool name spelling or register the tool"
        super().__post_init__()


@dataclass
class ToolInvalidArgsError(ToolError):
    """Raised when tool arguments are invalid."""

    validation_error: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Invalid arguments for {self.tool}: {self.validation_error}"
        if self.code == 0:
            self.code = ERROR_TOOL_INVALID_ARGS
        super().__post_init__()
        self.context["validation_error"] = self.validation_error


@dataclass
class ToolExecutionError(ToolError):
    """Raised when a tool fails during execution."""

    underlying_error: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Tool {self.tool} failed: {self.underlying_error}"
        if self.code == 0:
            self.code = ERROR_TOOL_EXECUTION_FAILED
        super().__post_init__()
        self.context["underlying_error"] = self.underlying_error


@dataclass
class ToolTimeoutError(ToolError):
    """Raised when a tool exceeds its timeout."""

    timeout_seconds: int = 0

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Tool {self.tool} timed out after {self.timeout_seconds}s"
        if self.code == 0:
            self.code = ERROR_TOOL_TIMEOUT
        if not self.suggestion:
            self.suggestion = "Increase timeout_seconds in policy or optimize the operation"
        super().__post_init__()
        self.context["timeout_seconds"] = self.timeout_seconds


# =============================================================================
# Plan Errors
# =============================================================================


@dataclass
class PlanValidationError(CapsuleError):
    """
    Raised when a plan fails validation.

    These errors occur before execution, during plan loading.

    Attributes:
        step_index: Index of the invalid step (if applicable)
        step_id: ID of the invalid step (if applicable)
    """

    step_index: int | None = None
    step_id: str | None = None

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if self.code == 0:
            self.code = ERROR_PLAN_INVALID_FORMAT
        self.context.update({
            "step_index": self.step_index,
            "step_id": self.step_id,
        })


@dataclass
class PlanEmptyError(PlanValidationError):
    """Raised when a plan has no steps."""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = "Plan must have at least one step"
        if self.code == 0:
            self.code = ERROR_PLAN_EMPTY_STEPS
        super().__post_init__()


@dataclass
class PlanInvalidToolError(PlanValidationError):
    """Raised when a plan references an unknown tool."""

    tool: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Unknown tool in plan: {self.tool}"
        if self.code == 0:
            self.code = ERROR_PLAN_INVALID_TOOL
        super().__post_init__()
        self.context["tool"] = self.tool


# =============================================================================
# Replay Errors
# =============================================================================


@dataclass
class ReplayError(CapsuleError):
    """
    Base class for replay errors.

    These errors occur during replay when the current state
    doesn't match the recorded state.

    Attributes:
        run_id: ID of the run being replayed
    """

    run_id: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        self.context["run_id"] = self.run_id


@dataclass
class ReplayRunNotFoundError(ReplayError):
    """Raised when the run to replay doesn't exist."""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Run not found: {self.run_id}"
        if self.code == 0:
            self.code = ERROR_REPLAY_RUN_NOT_FOUND
        super().__post_init__()


@dataclass
class ReplayMismatchError(ReplayError):
    """Raised when replay doesn't match the original run."""

    expected: str = ""
    actual: str = ""
    mismatch_type: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Replay mismatch ({self.mismatch_type}): expected {self.expected}, got {self.actual}"
        if self.code == 0:
            self.code = ERROR_REPLAY_PLAN_MISMATCH
        super().__post_init__()
        self.context.update({
            "expected": self.expected,
            "actual": self.actual,
            "mismatch_type": self.mismatch_type,
        })


@dataclass
class ReplayHashMismatchError(ReplayError):
    """Raised when replay hashes don't match."""

    expected_hash: str = ""
    actual_hash: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Hash mismatch: expected {self.expected_hash[:8]}..., got {self.actual_hash[:8]}..."
        if self.code == 0:
            self.code = ERROR_REPLAY_HASH_MISMATCH
        super().__post_init__()
        self.context.update({
            "expected_hash": self.expected_hash,
            "actual_hash": self.actual_hash,
        })


# =============================================================================
# Storage Errors
# =============================================================================


@dataclass
class StorageError(CapsuleError):
    """
    Base class for storage/database errors.

    These errors occur during database operations.

    Attributes:
        operation: The operation that failed (e.g., "insert", "query")
    """

    operation: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        self.context["operation"] = self.operation


@dataclass
class StorageConnectionError(StorageError):
    """Raised when database connection fails."""

    db_path: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Failed to connect to database: {self.db_path}"
        if self.code == 0:
            self.code = ERROR_STORAGE_CONNECTION
        if not self.suggestion:
            self.suggestion = "Check that the database path is valid and writable"
        super().__post_init__()
        self.context["db_path"] = self.db_path


@dataclass
class StorageWriteError(StorageError):
    """Raised when a write operation fails."""

    underlying_error: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Database write failed: {self.underlying_error}"
        if self.code == 0:
            self.code = ERROR_STORAGE_WRITE
        super().__post_init__()
        self.context["underlying_error"] = self.underlying_error


@dataclass
class StorageReadError(StorageError):
    """Raised when a read operation fails."""

    underlying_error: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Database read failed: {self.underlying_error}"
        if self.code == 0:
            self.code = ERROR_STORAGE_READ
        super().__post_init__()
        self.context["underlying_error"] = self.underlying_error


@dataclass
class StorageIntegrityError(StorageError):
    """Raised when data integrity check fails."""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = "Database integrity check failed"
        if self.code == 0:
            self.code = ERROR_STORAGE_INTEGRITY
        if not self.suggestion:
            self.suggestion = "The database may be corrupted. Try using a backup."
        super().__post_init__()


# =============================================================================
# Planner Errors
# =============================================================================


@dataclass
class PlannerError(CapsuleError):
    """
    Base class for all planner-related errors.

    Planner errors occur when communicating with the planner backend
    (e.g., Ollama) or processing its responses.

    Attributes:
        planner: Name of the planner that failed
        model: Model being used (if applicable)
    """

    planner: str = ""
    model: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        self.context.update({
            "planner": self.planner,
            "model": self.model,
        })


@dataclass
class PlannerConnectionError(PlannerError):
    """
    Raised when unable to connect to the planner backend.

    Common causes:
    - Ollama is not running
    - Network issues
    - Invalid URL
    """

    url: str = ""
    underlying_error: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Cannot connect to planner at {self.url}"
        if self.code == 0:
            self.code = ERROR_PLANNER_CONNECTION
        if not self.suggestion:
            self.suggestion = (
                "Ensure Ollama is running: `ollama serve`\n"
                "Check the URL is correct and accessible."
            )
        self.context["url"] = self.url
        self.context["underlying_error"] = self.underlying_error
        super().__post_init__()


@dataclass
class PlannerTimeoutError(PlannerError):
    """
    Raised when the planner takes too long to respond.

    Common causes:
    - Model is too large for hardware
    - Complex prompt requiring extended processing
    - System under heavy load
    """

    timeout_seconds: float = 0.0

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Planner timed out after {self.timeout_seconds}s"
        if self.code == 0:
            self.code = ERROR_PLANNER_TIMEOUT
        if not self.suggestion:
            self.suggestion = (
                "Try a smaller model or increase timeout.\n"
                "Check system resources (CPU/RAM usage)."
            )
        self.context["timeout_seconds"] = self.timeout_seconds
        super().__post_init__()


@dataclass
class PlannerParseError(PlannerError):
    """
    Raised when the planner response cannot be parsed.

    This typically means the SLM generated malformed JSON or
    unexpected output format.

    Attributes:
        raw_response: The unparseable response
        parse_error: Description of what went wrong
    """

    raw_response: str = ""
    parse_error: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Cannot parse planner response: {self.parse_error}"
        if self.code == 0:
            self.code = ERROR_PLANNER_PARSE
        if not self.suggestion:
            self.suggestion = (
                "The model may need a different prompt format.\n"
                "Try lowering temperature for more consistent output."
            )
        self.context["raw_response"] = self.raw_response[:500]  # Truncate for safety
        self.context["parse_error"] = self.parse_error
        super().__post_init__()


@dataclass
class PlannerInvalidResponseError(PlannerError):
    """
    Raised when the planner response is valid JSON but has invalid content.

    For example:
    - Missing required fields (tool_name)
    - Invalid tool name
    - Invalid argument types
    """

    raw_response: str = ""
    validation_error: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Invalid planner response: {self.validation_error}"
        if self.code == 0:
            self.code = ERROR_PLANNER_INVALID_RESPONSE
        if not self.suggestion:
            self.suggestion = "The model may need clearer instructions about response format."
        self.context["raw_response"] = self.raw_response[:500]
        self.context["validation_error"] = self.validation_error
        super().__post_init__()


@dataclass
class PlannerModelNotFoundError(PlannerError):
    """
    Raised when the specified model is not available.

    Common causes:
    - Model not pulled yet
    - Typo in model name
    """

    available_models: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Model not found: {self.model}"
        if self.code == 0:
            self.code = ERROR_PLANNER_MODEL_NOT_FOUND
        if not self.suggestion:
            if self.available_models:
                models_str = ", ".join(self.available_models[:5])
                self.suggestion = f"Pull the model: `ollama pull {self.model}`\nAvailable: {models_str}"
            else:
                self.suggestion = f"Pull the model: `ollama pull {self.model}`"
        self.context["available_models"] = self.available_models
        super().__post_init__()


# =============================================================================
# Pack Errors
# =============================================================================


@dataclass
class PackError(CapsuleError):
    """
    Base class for all pack-related errors.

    Pack errors occur when loading, validating, or executing packs.

    Attributes:
        pack_name: Name of the pack that caused the error
        pack_path: Path to the pack directory (if known)
    """

    pack_name: str = ""
    pack_path: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        self.context.update({
            "pack_name": self.pack_name,
            "pack_path": self.pack_path,
        })


@dataclass
class PackNotFoundError(PackError):
    """
    Raised when a pack cannot be found.

    Common causes:
    - Typo in pack name
    - Pack not installed
    - Pack directory missing
    """

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Pack not found: {self.pack_name}"
        if self.code == 0:
            self.code = ERROR_PACK_NOT_FOUND
        if not self.suggestion:
            self.suggestion = (
                "Check the pack name spelling.\n"
                "Use `capsule pack list` to see available packs."
            )
        super().__post_init__()


@dataclass
class PackManifestError(PackError):
    """
    Raised when a pack manifest is invalid.

    Common causes:
    - Invalid YAML syntax
    - Missing required fields
    - Invalid field values
    """

    validation_error: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Invalid manifest in pack '{self.pack_name}': {self.validation_error}"
        if self.code == 0:
            self.code = ERROR_PACK_INVALID_MANIFEST
        if not self.suggestion:
            self.suggestion = "Check manifest.yaml for syntax errors and required fields."
        self.context["validation_error"] = self.validation_error
        super().__post_init__()


@dataclass
class PackMissingFileError(PackError):
    """
    Raised when a required pack file is missing.

    Common causes:
    - Incomplete pack installation
    - File deleted or moved
    """

    missing_file: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Missing file in pack '{self.pack_name}': {self.missing_file}"
        if self.code == 0:
            self.code = ERROR_PACK_MISSING_FILE
        if not self.suggestion:
            self.suggestion = f"Create the missing file: {self.missing_file}"
        self.context["missing_file"] = self.missing_file
        super().__post_init__()


@dataclass
class PackInputError(PackError):
    """
    Raised when pack inputs are invalid.

    Common causes:
    - Missing required input
    - Invalid input type
    - Value not in allowed enum
    - Pattern validation failed
    """

    input_name: str = ""
    input_value: Any = None
    validation_error: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Invalid input '{self.input_name}' for pack '{self.pack_name}': {self.validation_error}"
        if self.code == 0:
            self.code = ERROR_PACK_INVALID_INPUT
        self.context.update({
            "input_name": self.input_name,
            "input_value": str(self.input_value)[:100],  # Truncate for safety
            "validation_error": self.validation_error,
        })
        super().__post_init__()


@dataclass
class PackToolNotAvailableError(PackError):
    """
    Raised when a pack requires a tool that is not available.

    Common causes:
    - Tool not registered in Capsule
    - Tool disabled by policy
    """

    tool_name: str = ""
    available_tools: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Pack '{self.pack_name}' requires unavailable tool: {self.tool_name}"
        if self.code == 0:
            self.code = ERROR_PACK_TOOL_NOT_AVAILABLE
        if not self.suggestion:
            if self.available_tools:
                tools_str = ", ".join(self.available_tools[:5])
                self.suggestion = f"Available tools: {tools_str}"
            else:
                self.suggestion = "Check that the required tools are registered."
        self.context.update({
            "tool_name": self.tool_name,
            "available_tools": self.available_tools,
        })
        super().__post_init__()


@dataclass
class PackTemplateError(PackError):
    """
    Raised when a pack template fails to render.

    Common causes:
    - Invalid Jinja2 syntax
    - Missing template variables
    - Template file not found
    """

    template_path: str = ""
    template_error: str = ""

    def __post_init__(self) -> None:
        """Set defaults after dataclass init."""
        if not self.message:
            self.message = f"Template error in pack '{self.pack_name}': {self.template_error}"
        if self.code == 0:
            self.code = ERROR_PACK_TEMPLATE_ERROR
        if not self.suggestion:
            self.suggestion = "Check the Jinja2 template syntax and ensure all variables are defined."
        self.context.update({
            "template_path": self.template_path,
            "template_error": self.template_error,
        })
        super().__post_init__()
