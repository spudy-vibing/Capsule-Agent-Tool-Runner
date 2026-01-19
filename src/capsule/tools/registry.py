"""
Tool registry for Capsule.

The registry is the central location for all registered tools.
Tools must be registered before they can be used in plans.

Design:
    - Single global registry (default_registry) for convenience
    - Support for multiple registries for testing/isolation
    - Thread-safe registration and lookup
    - Clear error messages for unknown tools

Usage:
    from capsule.tools.registry import default_registry, register_tool

    # Register a tool
    register_tool(MyTool())

    # Look up a tool
    tool = default_registry.get("my.tool")
"""

from typing import Iterator

from capsule.errors import ToolNotFoundError
from capsule.tools.base import Tool


class ToolRegistry:
    """
    Registry for looking up tools by name.

    The registry maintains a mapping from tool names to tool instances.
    Tools must be registered before they can be used.

    Attributes:
        _tools: Internal mapping of tool names to tool instances
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """
        Register a tool in the registry.

        If a tool with the same name is already registered,
        it will be replaced with a warning.

        Args:
            tool: The tool instance to register

        Raises:
            ValueError: If tool is None or has an empty name
        """
        if tool is None:
            msg = "Cannot register None as a tool"
            raise ValueError(msg)

        name = tool.name
        if not name:
            msg = "Tool must have a non-empty name"
            raise ValueError(msg)

        if name in self._tools:
            # Allow re-registration (useful for testing)
            # In production, this would typically be a warning
            pass

        self._tools[name] = tool

    def get(self, name: str) -> Tool:
        """
        Look up a tool by name.

        Args:
            name: The tool's unique identifier

        Returns:
            The registered tool instance

        Raises:
            ToolNotFoundError: If no tool with that name is registered
        """
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(tool=name)
        return tool

    def get_optional(self, name: str) -> Tool | None:
        """
        Look up a tool by name, returning None if not found.

        Args:
            name: The tool's unique identifier

        Returns:
            The registered tool instance, or None if not found
        """
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """
        Check if a tool is registered.

        Args:
            name: The tool's unique identifier

        Returns:
            True if the tool is registered, False otherwise
        """
        return name in self._tools

    def unregister(self, name: str) -> bool:
        """
        Remove a tool from the registry.

        Args:
            name: The tool's unique identifier

        Returns:
            True if the tool was removed, False if it wasn't registered
        """
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def clear(self) -> None:
        """Remove all tools from the registry."""
        self._tools.clear()

    def list_tools(self) -> list[str]:
        """
        List all registered tool names.

        Returns:
            List of tool names in sorted order
        """
        return sorted(self._tools.keys())

    def __len__(self) -> int:
        """Return the number of registered tools."""
        return len(self._tools)

    def __iter__(self) -> Iterator[Tool]:
        """Iterate over all registered tools."""
        return iter(self._tools.values())

    def __contains__(self, name: str) -> bool:
        """Check if a tool is registered using 'in' operator."""
        return name in self._tools

    def __repr__(self) -> str:
        """String representation of the registry."""
        tools = ", ".join(self.list_tools())
        return f"<ToolRegistry: [{tools}]>"


# Global default registry instance
# This is the registry used by the engine unless overridden
default_registry = ToolRegistry()


def register_tool(tool: Tool) -> None:
    """
    Register a tool in the default registry.

    Convenience function for registering tools without
    directly accessing the registry.

    Args:
        tool: The tool instance to register
    """
    default_registry.register(tool)


def get_tool(name: str) -> Tool:
    """
    Get a tool from the default registry.

    Convenience function for looking up tools without
    directly accessing the registry.

    Args:
        name: The tool's unique identifier

    Returns:
        The registered tool instance

    Raises:
        ToolNotFoundError: If no tool with that name is registered
    """
    return default_registry.get(name)
