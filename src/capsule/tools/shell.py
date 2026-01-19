"""
Shell tools for Capsule.

This module provides tools for executing shell commands:
- shell.run: Execute a command with arguments

Security Note:
    Policy enforcement happens BEFORE these tools execute.
    By the time execute() is called, the command has been validated
    against allow_executables, deny_tokens, and other policy rules.

    CRITICAL SECURITY MEASURES:
    - Commands must be passed as a list (NO shell=True)
    - This prevents shell injection attacks
    - Each element in the list is passed as a separate argument
    - The executable is looked up in PATH, not via shell expansion

    Additional protections:
    - Timeout enforcement to prevent runaway processes
    - Output size limits to prevent memory exhaustion
    - No environment variable expansion in arguments
"""

import subprocess
from pathlib import Path
from typing import Any

from capsule.tools.base import Tool, ToolContext, ToolOutput


class ShellRunTool(Tool):
    """
    Execute shell commands safely.

    Arguments:
        cmd (list): Command as a list of strings (required)
                   First element is the executable, rest are arguments
        cwd (str): Working directory for the command (optional)
        env (dict): Environment variables to set (optional, merged with current)
        timeout (int): Timeout in seconds (optional, default from policy)

    Returns:
        On success: Dict with return_code, stdout, and stderr
        On failure: Error message describing what went wrong

    Security Features:
        - Commands MUST be a list (no shell string parsing)
        - Executable must be in policy allowlist
        - Arguments checked against deny_tokens
        - Timeout enforcement
        - Output size limits

    Example:
        args = {"cmd": ["echo", "hello", "world"]}
        output = tool.execute(args, context)
        if output.success:
            print(output.data["stdout"])  # "hello world\n"

    Why cmd must be a list:
        Using shell=True with a string command allows shell injection:
            "echo hello; rm -rf /"  # DANGEROUS!

        Using a list prevents this:
            ["echo", "hello; rm -rf /"]  # Safe: "hello; rm -rf /" is one argument
    """

    @property
    def name(self) -> str:
        return "shell.run"

    @property
    def description(self) -> str:
        return "Execute a shell command safely with arguments as a list"

    def validate_args(self, args: dict[str, Any]) -> list[str]:
        """Validate shell.run arguments."""
        errors = []

        # cmd is required and must be a list
        if "cmd" not in args:
            errors.append("'cmd' is required")
        elif not isinstance(args["cmd"], list):
            errors.append("'cmd' must be a list of strings (shell=True is not allowed)")
        elif len(args["cmd"]) == 0:
            errors.append("'cmd' list cannot be empty")
        else:
            # All elements must be strings
            for i, element in enumerate(args["cmd"]):
                if not isinstance(element, str):
                    errors.append(f"'cmd[{i}]' must be a string, got {type(element).__name__}")
                    break

        # cwd must be a string if provided
        if "cwd" in args:
            if not isinstance(args["cwd"], str):
                errors.append("'cwd' must be a string")
            elif not args["cwd"].strip():
                errors.append("'cwd' cannot be empty")

        # env must be a dict of strings if provided
        if "env" in args:
            if not isinstance(args["env"], dict):
                errors.append("'env' must be a dictionary")
            else:
                for key, value in args["env"].items():
                    if not isinstance(key, str):
                        errors.append("Environment variable names must be strings")
                        break
                    if not isinstance(value, str):
                        errors.append("Environment variable values must be strings")
                        break

        # timeout must be a positive number if provided
        if "timeout" in args:
            if not isinstance(args["timeout"], (int, float)):
                errors.append("'timeout' must be a number")
            elif args["timeout"] <= 0:
                errors.append("'timeout' must be positive")

        return errors

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        """
        Execute a shell command.

        Args:
            args: Must contain 'cmd' as a list
            context: Runtime context with working directory and policy

        Returns:
            ToolOutput with command results or error
        """
        # Validate arguments
        errors = self.validate_args(args)
        if errors:
            return ToolOutput.fail(f"Invalid arguments: {'; '.join(errors)}")

        # Extract arguments
        cmd = args["cmd"]
        cwd = args.get("cwd", context.working_dir)
        env_override = args.get("env", {})

        # Get timeout and max output from policy if available
        timeout_seconds = args.get("timeout", 60)
        max_output_bytes = 1024 * 1024  # Default 1 MB

        if context.policy:
            timeout_seconds = args.get("timeout", context.policy.tools.shell_run.timeout_seconds)
            max_output_bytes = context.policy.tools.shell_run.max_output_bytes

        # Resolve working directory
        try:
            cwd_path = Path(cwd)
            if not cwd_path.is_absolute():
                cwd_path = Path(context.working_dir) / cwd_path
            cwd_path = cwd_path.resolve()

            if not cwd_path.exists():
                return ToolOutput.fail(
                    f"Working directory does not exist: {cwd}",
                    cwd=str(cwd_path),
                )
            if not cwd_path.is_dir():
                return ToolOutput.fail(
                    f"Working directory is not a directory: {cwd}",
                    cwd=str(cwd_path),
                )
        except (ValueError, OSError) as e:
            return ToolOutput.fail(f"Invalid working directory: {e}")

        # Build environment (start with current, then overlay)
        import os

        env = os.environ.copy()
        env.update(env_override)

        # Execute the command
        # CRITICAL: shell=False (the default) - this is what makes it safe
        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd_path),
                env=env,
                capture_output=True,
                timeout=timeout_seconds,
                # Never use shell=True!
                shell=False,
            )

            stdout = result.stdout
            stderr = result.stderr

            # Check output size limits
            total_output = len(stdout) + len(stderr)
            if total_output > max_output_bytes:
                # Truncate the output
                truncate_msg = f"\n... [truncated, exceeded {max_output_bytes} bytes]"
                truncate_bytes = truncate_msg.encode()

                # Split the limit between stdout and stderr proportionally
                if len(stdout) > max_output_bytes // 2:
                    stdout = stdout[: max_output_bytes // 2 - len(truncate_bytes)] + truncate_bytes
                if len(stderr) > max_output_bytes // 2:
                    stderr = stderr[: max_output_bytes // 2 - len(truncate_bytes)] + truncate_bytes

            # Decode output (best effort)
            try:
                stdout_str = stdout.decode("utf-8")
            except UnicodeDecodeError:
                stdout_str = stdout.decode("utf-8", errors="replace")

            try:
                stderr_str = stderr.decode("utf-8")
            except UnicodeDecodeError:
                stderr_str = stderr.decode("utf-8", errors="replace")

            return ToolOutput.ok(
                {
                    "return_code": result.returncode,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                },
                cmd=cmd,
                cwd=str(cwd_path),
                return_code=result.returncode,
                stdout_size=len(stdout),
                stderr_size=len(stderr),
            )

        except subprocess.TimeoutExpired:
            return ToolOutput.fail(
                f"Command timed out after {timeout_seconds} seconds",
                cmd=cmd,
                timeout=timeout_seconds,
            )
        except FileNotFoundError:
            return ToolOutput.fail(
                f"Executable not found: {cmd[0]}",
                executable=cmd[0],
            )
        except PermissionError:
            return ToolOutput.fail(
                f"Permission denied executing: {cmd[0]}",
                executable=cmd[0],
            )
        except OSError as e:
            return ToolOutput.fail(
                f"OS error executing command: {e}",
                cmd=cmd,
                error_type=type(e).__name__,
            )
        except Exception as e:
            return ToolOutput.fail(
                f"Unexpected error: {e}",
                cmd=cmd,
                error_type=type(e).__name__,
            )


# Register tools in the default registry
def register_shell_tools() -> None:
    """Register all shell tools in the default registry."""
    from capsule.tools.registry import default_registry

    default_registry.register(ShellRunTool())
