"""
Unit tests for shell tools.

Tests for shell.run tool functionality including:
- Argument validation
- Command execution
- Error handling
- Output handling
"""

import pytest

from capsule.schema import Policy, ShellPolicy, ToolPolicies
from capsule.tools.base import ToolContext
from capsule.tools.shell import ShellRunTool


class TestShellRunToolValidation:
    """Tests for shell.run argument validation."""

    def test_cmd_required(self) -> None:
        """Test that cmd is required."""
        tool = ShellRunTool()

        errors = tool.validate_args({})
        assert len(errors) > 0
        assert any("cmd" in e.lower() and "required" in e.lower() for e in errors)

    def test_cmd_must_be_list(self) -> None:
        """Test that cmd must be a list."""
        tool = ShellRunTool()

        errors = tool.validate_args({"cmd": "echo hello"})
        assert len(errors) > 0
        assert any("list" in e.lower() for e in errors)

    def test_cmd_cannot_be_empty(self) -> None:
        """Test that cmd cannot be empty list."""
        tool = ShellRunTool()

        errors = tool.validate_args({"cmd": []})
        assert len(errors) > 0
        assert any("empty" in e.lower() for e in errors)

    def test_cmd_elements_must_be_strings(self) -> None:
        """Test that cmd elements must be strings."""
        tool = ShellRunTool()

        errors = tool.validate_args({"cmd": ["echo", 123]})
        assert len(errors) > 0
        assert any("string" in e.lower() for e in errors)

        errors = tool.validate_args({"cmd": ["echo", None]})
        assert len(errors) > 0

    def test_valid_cmd(self) -> None:
        """Test that valid cmd passes validation."""
        tool = ShellRunTool()

        assert tool.validate_args({"cmd": ["echo", "hello"]}) == []
        assert tool.validate_args({"cmd": ["ls", "-la", "/tmp"]}) == []
        assert tool.validate_args({"cmd": ["git", "status"]}) == []

    def test_cwd_must_be_string(self) -> None:
        """Test that cwd must be a string."""
        tool = ShellRunTool()

        errors = tool.validate_args({"cmd": ["echo"], "cwd": 123})
        assert len(errors) > 0
        assert any("string" in e.lower() for e in errors)

    def test_cwd_cannot_be_empty(self) -> None:
        """Test that cwd cannot be empty."""
        tool = ShellRunTool()

        errors = tool.validate_args({"cmd": ["echo"], "cwd": ""})
        assert len(errors) > 0
        assert any("empty" in e.lower() for e in errors)

    def test_valid_cwd(self) -> None:
        """Test that valid cwd passes validation."""
        tool = ShellRunTool()

        assert tool.validate_args({"cmd": ["echo"], "cwd": "/tmp"}) == []
        assert tool.validate_args({"cmd": ["echo"], "cwd": "."}) == []

    def test_env_must_be_dict(self) -> None:
        """Test that env must be a dictionary."""
        tool = ShellRunTool()

        errors = tool.validate_args({"cmd": ["echo"], "env": "not-a-dict"})
        assert len(errors) > 0
        assert any("dict" in e.lower() for e in errors)

    def test_env_keys_must_be_strings(self) -> None:
        """Test that env keys must be strings."""
        tool = ShellRunTool()

        errors = tool.validate_args({"cmd": ["echo"], "env": {123: "value"}})
        assert len(errors) > 0
        assert any("string" in e.lower() for e in errors)

    def test_env_values_must_be_strings(self) -> None:
        """Test that env values must be strings."""
        tool = ShellRunTool()

        errors = tool.validate_args({"cmd": ["echo"], "env": {"key": 123}})
        assert len(errors) > 0
        assert any("string" in e.lower() for e in errors)

    def test_valid_env(self) -> None:
        """Test that valid env passes validation."""
        tool = ShellRunTool()

        errors = tool.validate_args({
            "cmd": ["echo"],
            "env": {"PATH": "/usr/bin", "HOME": "/home/user"},
        })
        assert errors == []

    def test_timeout_must_be_number(self) -> None:
        """Test that timeout must be a number."""
        tool = ShellRunTool()

        errors = tool.validate_args({"cmd": ["echo"], "timeout": "30"})
        assert len(errors) > 0
        assert any("number" in e.lower() for e in errors)

    def test_timeout_must_be_positive(self) -> None:
        """Test that timeout must be positive."""
        tool = ShellRunTool()

        errors = tool.validate_args({"cmd": ["echo"], "timeout": 0})
        assert len(errors) > 0
        assert any("positive" in e.lower() for e in errors)

        errors = tool.validate_args({"cmd": ["echo"], "timeout": -5})
        assert len(errors) > 0


class TestShellRunToolExecution:
    """Tests for shell.run execution."""

    def test_simple_echo(self) -> None:
        """Test simple echo command."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({"cmd": ["echo", "hello world"]}, context)

        assert result.success is True
        assert result.data["return_code"] == 0
        assert "hello world" in result.data["stdout"]
        assert result.data["stderr"] == ""

    def test_command_with_arguments(self) -> None:
        """Test command with multiple arguments."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({"cmd": ["echo", "arg1", "arg2", "arg3"]}, context)

        assert result.success is True
        assert "arg1 arg2 arg3" in result.data["stdout"]

    def test_command_failure(self) -> None:
        """Test command that fails."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({"cmd": ["ls", "/nonexistent/path/12345"]}, context)

        # Tool execution succeeds, command fails
        assert result.success is True
        assert result.data["return_code"] != 0
        assert result.data["stderr"] != ""

    def test_nonexistent_executable(self) -> None:
        """Test nonexistent executable."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({"cmd": ["nonexistent-command-xyz-123"]}, context)

        assert result.success is False
        assert "not found" in result.error.lower()

    def test_working_directory(self) -> None:
        """Test working directory is respected."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/")

        result = tool.execute({"cmd": ["pwd"], "cwd": "/tmp"}, context)

        assert result.success is True
        # On macOS, /tmp may resolve to /private/tmp
        assert "tmp" in result.data["stdout"].lower()

    def test_invalid_working_directory(self) -> None:
        """Test invalid working directory."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({
            "cmd": ["echo", "hello"],
            "cwd": "/nonexistent/directory/xyz",
        }, context)

        assert result.success is False
        assert "directory" in result.error.lower()

    def test_custom_environment_variable(self) -> None:
        """Test custom environment variables."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({
            "cmd": ["printenv", "MY_CUSTOM_VAR"],
            "env": {"MY_CUSTOM_VAR": "custom_value_123"},
        }, context)

        assert result.success is True
        assert "custom_value_123" in result.data["stdout"]

    def test_stderr_capture(self) -> None:
        """Test that stderr is captured."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        # ls on nonexistent path writes to stderr
        result = tool.execute({"cmd": ["ls", "/nonexistent/xyz"]}, context)

        assert result.success is True
        assert result.data["return_code"] != 0
        assert len(result.data["stderr"]) > 0

    def test_timeout_enforcement(self) -> None:
        """Test timeout is enforced."""
        tool = ShellRunTool()

        policy = Policy(
            tools=ToolPolicies(
                shell_run=ShellPolicy(
                    allow_executables=["sleep"],
                    timeout_seconds=1,
                )
            )
        )
        context = ToolContext(run_id="test-run", working_dir="/tmp", policy=policy)

        result = tool.execute({"cmd": ["sleep", "10"]}, context)

        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_explicit_timeout_override(self) -> None:
        """Test explicit timeout in args."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({
            "cmd": ["sleep", "10"],
            "timeout": 1,
        }, context)

        assert result.success is False
        assert "timed out" in result.error.lower()


class TestShellSafetyFeatures:
    """Tests for shell safety features."""

    def test_semicolon_not_interpreted(self) -> None:
        """Test that semicolons are not interpreted as command separators."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        # This should echo the literal string, not run multiple commands
        result = tool.execute({"cmd": ["echo", "hello; echo world"]}, context)

        assert result.success is True
        # Should contain the literal semicolon
        assert "hello; echo world" in result.data["stdout"]

    def test_pipe_not_interpreted(self) -> None:
        """Test that pipes are not interpreted."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({"cmd": ["echo", "hello | cat"]}, context)

        assert result.success is True
        assert "hello | cat" in result.data["stdout"]

    def test_backticks_not_interpreted(self) -> None:
        """Test that backticks are not interpreted."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({"cmd": ["echo", "`whoami`"]}, context)

        assert result.success is True
        # Should echo literal backticks, not execute whoami
        assert "`whoami`" in result.data["stdout"]

    def test_dollar_not_expanded(self) -> None:
        """Test that $() is not expanded."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({"cmd": ["echo", "$(whoami)"]}, context)

        assert result.success is True
        # Should echo literal, not execute
        assert "$(whoami)" in result.data["stdout"]


class TestToolProperties:
    """Tests for tool properties."""

    def test_tool_name(self) -> None:
        """Test that tool has correct name."""
        tool = ShellRunTool()
        assert tool.name == "shell.run"

    def test_tool_description(self) -> None:
        """Test that tool has a description."""
        tool = ShellRunTool()
        assert len(tool.description) > 0
        assert "shell" in tool.description.lower() or "command" in tool.description.lower()


class TestOutputMetadata:
    """Tests for output metadata."""

    def test_metadata_includes_cmd(self) -> None:
        """Test that output includes cmd in metadata."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({"cmd": ["echo", "hello"]}, context)

        assert result.success is True
        assert result.metadata.get("cmd") == ["echo", "hello"]

    def test_metadata_includes_return_code(self) -> None:
        """Test that output includes return code in metadata."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({"cmd": ["echo", "hello"]}, context)

        assert result.success is True
        assert result.metadata.get("return_code") == 0

    def test_metadata_includes_output_sizes(self) -> None:
        """Test that output includes stdout/stderr sizes."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({"cmd": ["echo", "hello"]}, context)

        assert result.success is True
        assert "stdout_size" in result.metadata
        assert "stderr_size" in result.metadata
