"""
Tests for shell.py coverage gaps:
- Output size truncation
- Non-UTF-8 output decoding
- PermissionError / OSError handlers
- Invalid working directory (file, not dir)
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

from capsule.schema import Policy, ShellPolicy, ToolPolicies
from capsule.tools.base import ToolContext
from capsule.tools.shell import ShellRunTool


@pytest.fixture
def shell():
    return ShellRunTool()


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def _context(working_dir="/tmp", max_output_bytes=None, timeout_seconds=60):
    """Helper to build a ToolContext with optional shell policy overrides."""
    if max_output_bytes is not None:
        policy = Policy(
            tools=ToolPolicies(
                shell_run=ShellPolicy(
                    allow_executables=["python3", "echo", "ls", "printenv", "sleep", "pwd"],
                    timeout_seconds=timeout_seconds,
                    max_output_bytes=max_output_bytes,
                )
            )
        )
    else:
        policy = None
    return ToolContext(run_id="test-run", working_dir=working_dir, policy=policy)


class TestOutputTruncation:
    def test_large_stdout_is_truncated(self, shell):
        """Output exceeding max_output_bytes is truncated."""
        ctx = _context(max_output_bytes=1000)
        result = shell.execute(
            {"cmd": ["python3", "-c", "print('A' * 200000)"]}, ctx
        )
        assert result.success
        stdout = result.data["stdout"]
        assert len(stdout) <= 1500  # Allow some overhead for truncation message
        assert "truncated" in stdout.lower() or len(stdout) < 200000

    def test_large_stderr_is_truncated(self, shell):
        """Stderr exceeding max_output_bytes is also truncated."""
        ctx = _context(max_output_bytes=1000)
        result = shell.execute(
            {"cmd": ["python3", "-c", "import sys; sys.stderr.write('E' * 200000)"]}, ctx
        )
        assert result.success
        stderr = result.data["stderr"]
        assert len(stderr) <= 1500

    def test_combined_output_truncation(self, shell):
        """Both stdout and stderr truncated proportionally."""
        ctx = _context(max_output_bytes=1000)
        result = shell.execute(
            {
                "cmd": [
                    "python3", "-c",
                    "import sys; print('O' * 100000); sys.stderr.write('E' * 100000)",
                ],
            },
            ctx,
        )
        assert result.success
        stdout = result.data["stdout"]
        stderr = result.data["stderr"]
        assert len(stdout) + len(stderr) < 200000


class TestNonUtf8Output:
    def test_binary_stdout_decoded_with_replacement(self, shell, temp_dir):
        """Binary output is decoded with replacement chars, not crash."""
        script = temp_dir / "binary_out.py"
        script.write_text(
            "import sys; sys.stdout.buffer.write(b'\\x80\\x81\\x82hello\\xff')"
        )
        ctx = _context()
        result = shell.execute({"cmd": ["python3", str(script)]}, ctx)
        assert result.success
        assert "hello" in result.data["stdout"]

    def test_binary_stderr_decoded_with_replacement(self, shell, temp_dir):
        """Binary stderr is decoded with replacement chars."""
        script = temp_dir / "binary_err.py"
        script.write_text(
            "import sys; sys.stderr.buffer.write(b'\\x80error\\xff')"
        )
        ctx = _context()
        result = shell.execute({"cmd": ["python3", str(script)]}, ctx)
        assert result.success
        assert "error" in result.data["stderr"]


class TestWorkingDirectoryErrors:
    def test_cwd_is_file_not_directory(self, shell, temp_dir):
        """Using a file as cwd returns a failure."""
        file_path = temp_dir / "afile.txt"
        file_path.write_text("not a directory")

        ctx = _context(working_dir=str(temp_dir))
        result = shell.execute(
            {"cmd": ["echo", "hello"], "cwd": str(file_path)}, ctx
        )
        assert not result.success
        assert "directory" in result.error.lower()


class TestExecutionErrors:
    def test_permission_error(self, shell, temp_dir):
        """Running a non-executable file returns a clean error."""
        script = temp_dir / "noexec.sh"
        script.write_text("#!/bin/sh\necho hi")
        script.chmod(0o644)  # Not executable

        ctx = _context(working_dir=str(temp_dir))
        result = shell.execute({"cmd": [str(script)]}, ctx)
        assert not result.success
        assert result.error  # Should have an error message

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix-only")
    def test_nonexistent_executable_os_error(self, shell):
        """Running a nonexistent binary returns a clean error."""
        ctx = _context()
        result = shell.execute(
            {"cmd": ["/nonexistent/binary/xyz"]}, ctx
        )
        assert not result.success
        assert result.error
