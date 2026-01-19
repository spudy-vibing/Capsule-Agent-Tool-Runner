"""
Base classes for the tool interface.

This module defines the core abstractions for tools in Capsule:
- Tool: Abstract base class that all tools must implement
- ToolContext: Runtime context passed to tools during execution
- ToolOutput: Standardized result format from tool execution

Design Principles:
    - Tools are stateless - all state comes from ToolContext
    - Tools receive validated arguments - validation happens before execution
    - Tools return ToolOutput - never raise exceptions for expected failures
    - Tools are registered by name - the registry handles lookup

Why ABC over Protocol?
    - ABCs provide clearer inheritance semantics
    - ABCs allow shared implementation in base class
    - ABCs work better with IDE tooling for autocomplete
    - Protocols are better for structural typing; we want nominal typing here
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from capsule.schema import Policy


@dataclass(frozen=True)
class ToolOutput:
    """
    Standardized output from tool execution.

    Every tool returns a ToolOutput, whether successful or failed.
    This provides a consistent interface for the engine to handle results.

    Attributes:
        success: Whether the tool executed successfully
        data: The output data from the tool (type varies by tool)
        error: Error message if success is False
        metadata: Additional metadata about the execution
    """

    success: bool
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, data: Any, **metadata: Any) -> "ToolOutput":
        """Create a successful output."""
        return cls(success=True, data=data, metadata=metadata)

    @classmethod
    def fail(cls, error: str, **metadata: Any) -> "ToolOutput":
        """Create a failed output."""
        return cls(success=False, error=error, metadata=metadata)


@dataclass
class ToolContext:
    """
    Runtime context passed to tools during execution.

    ToolContext provides tools with everything they need to execute,
    including the current run ID, policy reference, and any shared state.

    This is passed to every tool execution, allowing tools to:
    - Know which run they're part of
    - Access the current policy for self-validation
    - Store metadata about their execution

    Attributes:
        run_id: Unique identifier for the current run
        policy: The policy being enforced (for reference, not enforcement)
        working_dir: The working directory for relative paths
        metadata: Additional context-specific metadata
    """

    run_id: str
    policy: "Policy | None" = None
    working_dir: str = "."
    metadata: dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    """
    Abstract base class for all Capsule tools.

    Tools are the actions that Capsule can execute. Each tool:
    - Has a unique name (e.g., "fs.read", "shell.run")
    - Defines what arguments it accepts
    - Implements the execute() method
    - Returns a ToolOutput

    Subclasses must implement:
    - name property: Returns the tool's unique identifier
    - execute(): Performs the tool's action

    Example:
        class EchoTool(Tool):
            @property
            def name(self) -> str:
                return "echo"

            def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
                message = args.get("message", "")
                return ToolOutput.ok(message)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        The unique identifier for this tool.

        Tool names follow the convention: namespace.action
        Examples: "fs.read", "fs.write", "http.get", "shell.run"

        Returns:
            The tool's unique name
        """
        ...

    @property
    def description(self) -> str:
        """
        Human-readable description of what the tool does.

        Override this in subclasses to provide documentation.

        Returns:
            Description of the tool's purpose
        """
        return f"Tool: {self.name}"

    @abstractmethod
    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        """
        Execute the tool with the given arguments.

        This method is called after policy evaluation has passed.
        The tool should:
        1. Validate its specific arguments
        2. Perform its action
        3. Return a ToolOutput

        Args:
            args: The arguments for this tool call (tool-specific)
            context: Runtime context with run_id, policy, etc.

        Returns:
            ToolOutput indicating success or failure with data/error

        Note:
            - Do NOT raise exceptions for expected failures (file not found, etc.)
            - Use ToolOutput.fail() for expected errors
            - Only raise exceptions for unexpected/programming errors
        """
        ...

    def validate_args(self, args: dict[str, Any]) -> list[str]:
        """
        Validate the arguments for this tool.

        Override this method to provide custom argument validation.
        The default implementation accepts any arguments.

        Args:
            args: The arguments to validate

        Returns:
            List of validation error messages (empty if valid)
        """
        return []

    def __repr__(self) -> str:
        """String representation of the tool."""
        return f"<Tool: {self.name}>"
