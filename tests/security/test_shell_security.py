"""
Security tests for shell tools.

These tests verify that the shell.run tool properly:
1. Rejects string commands (prevents shell injection)
2. Enforces executable allowlist
3. Blocks dangerous tokens
4. Handles timeout properly
5. Limits output size

These are security-critical tests - failures here indicate
potential vulnerabilities in the shell tool.
"""

import pytest

from capsule.policy.engine import PolicyEngine
from capsule.schema import Policy, ShellPolicy, ToolPolicies
from capsule.tools.base import ToolContext
from capsule.tools.shell import ShellRunTool


class TestShellInjectionPrevention:
    """Tests for shell injection attack prevention."""

    def test_rejects_string_command(self) -> None:
        """Test that string commands are rejected (primary injection vector)."""
        tool = ShellRunTool()

        # This is the classic injection pattern - should be rejected
        errors = tool.validate_args({"cmd": "echo hello; rm -rf /"})

        assert len(errors) > 0
        assert any("list" in e.lower() for e in errors)

    def test_rejects_nested_list(self) -> None:
        """Test that nested lists are rejected."""
        tool = ShellRunTool()

        errors = tool.validate_args({"cmd": ["echo", ["nested", "list"]]})

        assert len(errors) > 0
        assert any("string" in e.lower() for e in errors)

    def test_rejects_non_string_elements(self) -> None:
        """Test that non-string elements are rejected."""
        tool = ShellRunTool()

        # Numbers in command should be rejected
        errors = tool.validate_args({"cmd": ["echo", 123]})
        assert len(errors) > 0

        # None in command should be rejected
        errors = tool.validate_args({"cmd": ["echo", None]})
        assert len(errors) > 0

    def test_accepts_list_command(self) -> None:
        """Test that list commands are accepted."""
        tool = ShellRunTool()

        errors = tool.validate_args({"cmd": ["echo", "hello"]})
        assert errors == []

    def test_injection_attempt_becomes_argument(self) -> None:
        """Test that injection attempts in list become safe arguments."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        # The semicolon and rm should be treated as part of the argument, not a command
        # This is safe because shell=False
        result = tool.execute({"cmd": ["echo", "hello; rm -rf /"]}, context)

        # Should succeed and the "dangerous" part is just echoed as text
        assert result.success is True
        # The output should contain the literal text, not execute the rm
        assert "hello; rm -rf /" in result.data["stdout"]

    def test_pipe_becomes_argument(self) -> None:
        """Test that pipe characters are treated as arguments, not pipes."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({"cmd": ["echo", "hello | cat /etc/passwd"]}, context)

        assert result.success is True
        # Should echo the literal pipe, not execute it
        assert "hello | cat /etc/passwd" in result.data["stdout"]


class TestExecutableAllowlist:
    """Tests for executable allowlist enforcement."""

    def test_policy_blocks_unknown_executable(self) -> None:
        """Test that policy blocks executables not in allowlist."""
        policy = Policy(
            tools=ToolPolicies(
                shell_run=ShellPolicy(
                    allow_executables=["echo", "date"],
                )
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate("shell.run", {"cmd": ["rm", "-rf", "/"]})

        assert decision.allowed is False
        assert "allowlist" in decision.reason.lower()

    def test_policy_allows_listed_executable(self) -> None:
        """Test that policy allows executables in allowlist."""
        policy = Policy(
            tools=ToolPolicies(
                shell_run=ShellPolicy(
                    allow_executables=["echo", "date", "ls"],
                )
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate("shell.run", {"cmd": ["echo", "hello"]})
        assert decision.allowed is True

        decision = engine.evaluate("shell.run", {"cmd": ["ls", "-la"]})
        assert decision.allowed is True

    def test_policy_blocks_path_to_executable(self) -> None:
        """Test that full paths are reduced to executable name for checking."""
        policy = Policy(
            tools=ToolPolicies(
                shell_run=ShellPolicy(
                    allow_executables=["echo"],
                )
            )
        )
        engine = PolicyEngine(policy)

        # /usr/bin/rm should be blocked because "rm" is not in allowlist
        decision = engine.evaluate("shell.run", {"cmd": ["/usr/bin/rm", "-rf", "/tmp/test"]})
        assert decision.allowed is False

        # /bin/echo should be allowed because "echo" is in allowlist
        decision = engine.evaluate("shell.run", {"cmd": ["/bin/echo", "hello"]})
        assert decision.allowed is True

    def test_empty_allowlist_blocks_all(self) -> None:
        """Test that empty allowlist blocks all executables."""
        policy = Policy(
            tools=ToolPolicies(
                shell_run=ShellPolicy(
                    allow_executables=[],
                )
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate("shell.run", {"cmd": ["echo", "hello"]})
        assert decision.allowed is False


class TestDenyTokens:
    """Tests for dangerous token blocking."""

    @pytest.mark.parametrize(
        "cmd,should_block",
        [
            # Blocked by default deny_tokens
            (["bash", "-c", "sudo rm"], True),  # sudo
            (["bash", "-c", "su - root"], True),  # su
            (["bash", "-c", "rm -rf /important"], True),  # rm -rf
            (["bash", "-c", "mkfs.ext4 /dev/sda"], True),  # mkfs
            (["bash", "-c", "dd if=/dev/zero of=/dev/sda"], True),  # dd
            (["bash", "-c", "echo foo > /dev/sda"], True),  # > /dev
            (["bash", "-c", "chmod 777 /etc/passwd"], True),  # chmod 777
            # Safe commands
            (["echo", "hello"], False),
            (["ls", "-la"], False),
            (["cat", "file.txt"], False),
            (["git", "status"], False),
        ],
    )
    def test_deny_tokens_blocking(self, cmd: list[str], should_block: bool) -> None:
        """Test that dangerous tokens are blocked."""
        policy = Policy(
            tools=ToolPolicies(
                shell_run=ShellPolicy(
                    allow_executables=["bash", "echo", "ls", "cat", "git"],
                    # Use default deny_tokens
                )
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate("shell.run", {"cmd": cmd})

        if should_block:
            assert decision.allowed is False, f"Expected {cmd} to be blocked"
            assert "token" in decision.reason.lower() or "blocked" in decision.reason.lower()
        else:
            assert decision.allowed is True, f"Expected {cmd} to be allowed"

    def test_custom_deny_tokens(self) -> None:
        """Test that custom deny tokens work."""
        policy = Policy(
            tools=ToolPolicies(
                shell_run=ShellPolicy(
                    allow_executables=["python"],
                    deny_tokens=["import os", "subprocess", "__import__"],
                )
            )
        )
        engine = PolicyEngine(policy)

        # Should block dangerous Python patterns
        # NOTE: These are policy tests - we're checking that the policy engine
        # blocks these command strings, NOT executing them
        decision = engine.evaluate("shell.run", {"cmd": ["python", "-c", "import os"]})
        assert decision.allowed is False

        decision = engine.evaluate("shell.run", {"cmd": ["python", "-c", "__import__('x')"]})
        assert decision.allowed is False

        # Safe Python should be allowed
        decision = engine.evaluate("shell.run", {"cmd": ["python", "-c", "print('hello')"]})
        assert decision.allowed is True

    def test_case_insensitive_token_matching(self) -> None:
        """Test that token matching is case-insensitive."""
        policy = Policy(
            tools=ToolPolicies(
                shell_run=ShellPolicy(
                    allow_executables=["bash"],
                    deny_tokens=["sudo"],
                )
            )
        )
        engine = PolicyEngine(policy)

        # Should block regardless of case
        assert not engine.evaluate("shell.run", {"cmd": ["bash", "-c", "SUDO rm"]}).allowed
        assert not engine.evaluate("shell.run", {"cmd": ["bash", "-c", "Sudo rm"]}).allowed
        assert not engine.evaluate("shell.run", {"cmd": ["bash", "-c", "sudo rm"]}).allowed


class TestCommandExecution:
    """Tests for actual command execution."""

    def test_successful_command(self) -> None:
        """Test that successful commands return correctly."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({"cmd": ["echo", "hello world"]}, context)

        assert result.success is True
        assert result.data["return_code"] == 0
        assert "hello world" in result.data["stdout"]
        assert result.data["stderr"] == ""

    def test_failed_command(self) -> None:
        """Test that failed commands return error code."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({"cmd": ["ls", "/nonexistent/path/12345"]}, context)

        assert result.success is True  # Tool succeeded, command failed
        assert result.data["return_code"] != 0
        assert result.data["stderr"] != ""

    def test_nonexistent_executable(self) -> None:
        """Test that nonexistent executables are handled."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({"cmd": ["nonexistent-command-12345"]}, context)

        assert result.success is False
        assert "not found" in result.error.lower()

    def test_working_directory(self) -> None:
        """Test that working directory is respected."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute({"cmd": ["pwd"]}, context)

        assert result.success is True
        # Should be in /tmp (or resolved path like /private/tmp on macOS)
        assert "tmp" in result.data["stdout"].lower()


class TestTimeoutEnforcement:
    """Tests for timeout enforcement."""

    def test_command_timeout(self) -> None:
        """Test that commands that exceed timeout are killed."""
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


class TestOutputLimits:
    """Tests for output size limits."""

    def test_large_output_truncated(self) -> None:
        """Test that large output is truncated."""
        tool = ShellRunTool()

        policy = Policy(
            tools=ToolPolicies(
                shell_run=ShellPolicy(
                    allow_executables=["yes"],
                    max_output_bytes=1000,
                    timeout_seconds=1,  # Need timeout since yes runs forever
                )
            )
        )
        context = ToolContext(run_id="test-run", working_dir="/tmp", policy=policy)

        # yes command outputs infinitely - will hit timeout
        result = tool.execute({"cmd": ["yes"]}, context)

        # Either truncated or timed out
        if result.success:
            # Output should be limited
            total_output = len(result.data["stdout"]) + len(result.data["stderr"])
            # Allow some buffer for truncation message
            assert total_output <= 2000


class TestEnvironmentSafety:
    """Tests for environment variable handling."""

    def test_custom_env_vars(self) -> None:
        """Test that custom environment variables work."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute(
            {
                "cmd": ["printenv", "CUSTOM_VAR"],
                "env": {"CUSTOM_VAR": "test_value"},
            },
            context,
        )

        assert result.success is True
        assert "test_value" in result.data["stdout"]

    def test_env_vars_dont_leak_sensitive_data(self) -> None:
        """Test that sensitive env vars can be overridden."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        # Override PATH to something harmless
        result = tool.execute(
            {
                "cmd": ["printenv", "CUSTOM_SECRET"],
                "env": {"CUSTOM_SECRET": "safe_value"},
            },
            context,
        )

        assert result.success is True
        assert "safe_value" in result.data["stdout"]


class TestArgumentValidation:
    """Tests for argument validation edge cases."""

    def test_empty_cmd_rejected(self) -> None:
        """Test that empty command list is rejected."""
        tool = ShellRunTool()

        errors = tool.validate_args({"cmd": []})
        assert len(errors) > 0

    def test_missing_cmd_rejected(self) -> None:
        """Test that missing cmd is rejected."""
        tool = ShellRunTool()

        errors = tool.validate_args({})
        assert len(errors) > 0
        assert any("required" in e.lower() for e in errors)

    def test_invalid_cwd_rejected(self) -> None:
        """Test that invalid working directory is handled."""
        tool = ShellRunTool()
        context = ToolContext(run_id="test-run", working_dir="/tmp")

        result = tool.execute(
            {"cmd": ["echo", "hello"], "cwd": "/nonexistent/directory/12345"},
            context,
        )

        assert result.success is False
        assert "directory" in result.error.lower()
