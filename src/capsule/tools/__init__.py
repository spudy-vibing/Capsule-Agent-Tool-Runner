"""
Tools module for Capsule.

This module provides the extensible tool interface and built-in tools.
Tools are the actions that Capsule can execute on behalf of agents.

Built-in tools (v0.1):
    - fs.read: Read file contents
    - fs.write: Write to files
    - http.get: Make HTTP GET requests
    - shell.run: Execute shell commands

Architecture:
    - Tool: Abstract base class defining the tool interface
    - ToolRegistry: Central registry for looking up tools by name
    - ToolContext: Runtime context passed to tools (run_id, policy, store)
    - ToolOutput: Standardized result format from tool execution

Each tool is responsible for:
    1. Validating its arguments
    2. Executing the operation
    3. Returning a standardized ToolOutput

Policy enforcement happens BEFORE tool execution, not within tools.
"""

from capsule.tools.base import Tool, ToolContext, ToolOutput
from capsule.tools.fs import FsReadTool, FsWriteTool, register_fs_tools
from capsule.tools.registry import (
    ToolRegistry,
    default_registry,
    get_tool,
    register_tool,
)

# Register built-in tools
register_fs_tools()

__all__ = [
    "Tool",
    "ToolContext",
    "ToolOutput",
    "ToolRegistry",
    "default_registry",
    "get_tool",
    "register_tool",
    "FsReadTool",
    "FsWriteTool",
]
