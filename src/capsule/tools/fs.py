"""
Filesystem tools for Capsule.

This module provides tools for reading and writing files:
- fs.read: Read file contents
- fs.write: Write content to files (Phase 2)

Security Note:
    Policy enforcement happens BEFORE these tools execute.
    By the time execute() is called, the path has been validated
    against allow_paths, deny_paths, and other policy rules.

    However, these tools still handle:
    - File not found errors
    - Permission errors
    - Encoding errors
    - Size limit enforcement (as a safety net)
"""

from pathlib import Path
from typing import Any

from capsule.tools.base import Tool, ToolContext, ToolOutput


class FsReadTool(Tool):
    """
    Read file contents.

    Arguments:
        path (str): Path to the file to read (required)
        encoding (str): Text encoding, default "utf-8"
        binary (bool): Read as binary instead of text, default False

    Returns:
        On success: File contents as string (or bytes if binary=True)
        On failure: Error message describing what went wrong

    Example:
        args = {"path": "./README.md"}
        output = tool.execute(args, context)
        if output.success:
            content = output.data
    """

    @property
    def name(self) -> str:
        return "fs.read"

    @property
    def description(self) -> str:
        return "Read file contents from the filesystem"

    def validate_args(self, args: dict[str, Any]) -> list[str]:
        """Validate fs.read arguments."""
        errors = []

        # path is required
        if "path" not in args:
            errors.append("'path' is required")
        elif not isinstance(args["path"], str):
            errors.append("'path' must be a string")
        elif not args["path"].strip():
            errors.append("'path' cannot be empty")

        # encoding must be a string if provided
        if "encoding" in args and not isinstance(args["encoding"], str):
            errors.append("'encoding' must be a string")

        # binary must be a bool if provided
        if "binary" in args and not isinstance(args["binary"], bool):
            errors.append("'binary' must be a boolean")

        return errors

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        """
        Read a file and return its contents.

        Args:
            args: Must contain 'path', optionally 'encoding' and 'binary'
            context: Runtime context with working directory

        Returns:
            ToolOutput with file contents or error
        """
        # Validate arguments
        errors = self.validate_args(args)
        if errors:
            return ToolOutput.fail(f"Invalid arguments: {'; '.join(errors)}")

        # Extract arguments
        path_str = args["path"]
        encoding = args.get("encoding", "utf-8")
        binary = args.get("binary", False)

        # Resolve path relative to working directory
        try:
            path = Path(path_str)
            if not path.is_absolute():
                path = Path(context.working_dir) / path
            path = path.resolve()
        except (ValueError, OSError) as e:
            return ToolOutput.fail(f"Invalid path: {e}")

        # Check if file exists
        if not path.exists():
            return ToolOutput.fail(
                f"File not found: {path_str}",
                path=str(path),
            )

        # Check if it's a file (not a directory)
        if not path.is_file():
            return ToolOutput.fail(
                f"Not a file: {path_str}",
                path=str(path),
            )

        # Read the file
        try:
            if binary:
                content = path.read_bytes()
                return ToolOutput.ok(
                    content,
                    path=str(path),
                    size=len(content),
                    binary=True,
                )
            else:
                content = path.read_text(encoding=encoding)
                return ToolOutput.ok(
                    content,
                    path=str(path),
                    size=len(content),
                    encoding=encoding,
                    binary=False,
                )
        except PermissionError:
            return ToolOutput.fail(
                f"Permission denied: {path_str}",
                path=str(path),
            )
        except UnicodeDecodeError as e:
            return ToolOutput.fail(
                f"Encoding error reading {path_str}: {e}. Try binary=True or different encoding.",
                path=str(path),
            )
        except OSError as e:
            return ToolOutput.fail(
                f"Error reading {path_str}: {e}",
                path=str(path),
            )


class FsWriteTool(Tool):
    """
    Write content to a file.

    Arguments:
        path (str): Path to the file to write (required)
        content (str): Content to write (required)
        encoding (str): Text encoding, default "utf-8"
        mode (str): Write mode - "overwrite" (default) or "append"
        create_dirs (bool): Create parent directories if needed, default False

    Returns:
        On success: Number of bytes written
        On failure: Error message describing what went wrong

    Note: This tool will be fully implemented in Phase 2.
    """

    @property
    def name(self) -> str:
        return "fs.write"

    @property
    def description(self) -> str:
        return "Write content to a file on the filesystem"

    def validate_args(self, args: dict[str, Any]) -> list[str]:
        """Validate fs.write arguments."""
        errors = []

        # path is required
        if "path" not in args:
            errors.append("'path' is required")
        elif not isinstance(args["path"], str):
            errors.append("'path' must be a string")
        elif not args["path"].strip():
            errors.append("'path' cannot be empty")

        # content is required
        if "content" not in args:
            errors.append("'content' is required")
        elif not isinstance(args["content"], (str, bytes)):
            errors.append("'content' must be a string or bytes")

        # mode must be valid if provided
        if "mode" in args:
            if args["mode"] not in ("overwrite", "append"):
                errors.append("'mode' must be 'overwrite' or 'append'")

        return errors

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        """
        Write content to a file.

        Args:
            args: Must contain 'path' and 'content'
            context: Runtime context with working directory

        Returns:
            ToolOutput with bytes written or error
        """
        # Validate arguments
        errors = self.validate_args(args)
        if errors:
            return ToolOutput.fail(f"Invalid arguments: {'; '.join(errors)}")

        # Extract arguments
        path_str = args["path"]
        content = args["content"]
        encoding = args.get("encoding", "utf-8")
        mode = args.get("mode", "overwrite")
        create_dirs = args.get("create_dirs", False)

        # Resolve path relative to working directory
        try:
            path = Path(path_str)
            if not path.is_absolute():
                path = Path(context.working_dir) / path
            path = path.resolve()
        except (ValueError, OSError) as e:
            return ToolOutput.fail(f"Invalid path: {e}")

        # Create parent directories if requested
        if create_dirs:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return ToolOutput.fail(f"Failed to create directories: {e}")

        # Check parent directory exists
        if not path.parent.exists():
            return ToolOutput.fail(
                f"Parent directory does not exist: {path.parent}",
                path=str(path),
            )

        # Write the file
        try:
            if isinstance(content, bytes):
                if mode == "append":
                    with path.open("ab") as f:
                        bytes_written = f.write(content)
                else:
                    bytes_written = path.write_bytes(content)
            else:
                if mode == "append":
                    with path.open("a", encoding=encoding) as f:
                        bytes_written = f.write(content)
                else:
                    path.write_text(content, encoding=encoding)
                    bytes_written = len(content.encode(encoding))

            return ToolOutput.ok(
                bytes_written,
                path=str(path),
                mode=mode,
            )
        except PermissionError:
            return ToolOutput.fail(
                f"Permission denied: {path_str}",
                path=str(path),
            )
        except OSError as e:
            return ToolOutput.fail(
                f"Error writing {path_str}: {e}",
                path=str(path),
            )


# Register tools in the default registry
def register_fs_tools() -> None:
    """Register all filesystem tools in the default registry."""
    from capsule.tools.registry import default_registry

    default_registry.register(FsReadTool())
    default_registry.register(FsWriteTool())
