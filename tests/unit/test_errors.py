"""
Unit tests for error hierarchy.

Tests cover:
- Base CapsuleError behavior
- Policy errors with context
- Tool errors with context
- Plan validation errors
- Replay and storage errors
- Error serialization
"""

import pytest

from capsule.errors import (
    ERROR_POLICY_DENIED,
    ERROR_POLICY_PATH_BLOCKED,
    ERROR_STORAGE_CONNECTION,
    ERROR_TOOL_NOT_FOUND,
    CapsuleError,
    DomainBlockedError,
    ExecutableBlockedError,
    PathBlockedError,
    PlanEmptyError,
    PlanValidationError,
    PolicyDeniedError,
    QuotaExceededError,
    ReplayHashMismatchError,
    ReplayMismatchError,
    ReplayRunNotFoundError,
    SizeExceededError,
    StorageConnectionError,
    StorageError,
    StorageWriteError,
    TokenBlockedError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolTimeoutError,
)


class TestCapsuleError:
    """Tests for base CapsuleError."""

    def test_basic_error(self) -> None:
        """Create a basic error with message."""
        err = CapsuleError(message="Something went wrong", code=9999)
        assert err.message == "Something went wrong"
        assert err.code == 9999
        assert err.suggestion is None
        assert err.context == {}

    def test_error_with_suggestion(self) -> None:
        """Error with suggestion text."""
        err = CapsuleError(
            message="Failed",
            code=1,
            suggestion="Try again",
        )
        assert err.suggestion == "Try again"
        assert "Suggestion: Try again" in str(err)

    def test_error_with_context(self) -> None:
        """Error with context dict."""
        err = CapsuleError(
            message="Failed",
            code=1,
            context={"key": "value"},
        )
        assert err.context["key"] == "value"

    def test_str_format(self) -> None:
        """String format includes code and message."""
        err = CapsuleError(message="Test error", code=1234)
        assert str(err) == "[E1234] Test error"

    def test_repr_format(self) -> None:
        """Repr includes class name and details."""
        err = CapsuleError(message="Test", code=1)
        assert "CapsuleError" in repr(err)
        assert "message='Test'" in repr(err)

    def test_to_dict(self) -> None:
        """Convert error to dictionary."""
        err = CapsuleError(
            message="Test",
            code=1,
            suggestion="Try again",
            context={"foo": "bar"},
        )
        d = err.to_dict()
        assert d["error_type"] == "CapsuleError"
        assert d["message"] == "Test"
        assert d["code"] == 1
        assert d["suggestion"] == "Try again"
        assert d["context"]["foo"] == "bar"

    def test_is_exception(self) -> None:
        """CapsuleError is a proper exception."""
        with pytest.raises(CapsuleError):
            raise CapsuleError(message="Test", code=1)


class TestPolicyDeniedError:
    """Tests for policy denial errors."""

    def test_basic_policy_denied(self) -> None:
        """Basic policy denied error."""
        err = PolicyDeniedError(
            tool="fs.read",
            tool_args={"path": "/etc/passwd"},
            reason="Path not in allowlist",
        )
        assert err.code == ERROR_POLICY_DENIED
        assert "fs.read" in str(err)
        assert "Path not in allowlist" in str(err)
        assert err.context["tool"] == "fs.read"
        assert err.context["tool_args"]["path"] == "/etc/passwd"

    def test_path_blocked(self) -> None:
        """Path blocked error with suggestion."""
        err = PathBlockedError(
            tool="fs.read",
            path="/etc/passwd",
        )
        assert err.code == ERROR_POLICY_PATH_BLOCKED
        assert "/etc/passwd" in str(err)
        assert "allow_paths" in err.suggestion

    def test_domain_blocked(self) -> None:
        """Domain blocked error."""
        err = DomainBlockedError(
            tool="http.get",
            domain="evil.com",
        )
        assert "evil.com" in str(err)
        assert "allow_domains" in err.suggestion

    def test_executable_blocked(self) -> None:
        """Executable blocked error."""
        err = ExecutableBlockedError(
            tool="shell.run",
            executable="rm",
        )
        assert "rm" in str(err)
        assert "allow_executables" in err.suggestion

    def test_token_blocked(self) -> None:
        """Token blocked error."""
        err = TokenBlockedError(
            tool="shell.run",
            token="sudo",
        )
        assert "sudo" in str(err)

    def test_size_exceeded(self) -> None:
        """Size exceeded error."""
        err = SizeExceededError(
            tool="fs.read",
            actual_size=2000000,
            max_size=1000000,
        )
        assert "2000000" in str(err)
        assert "1000000" in str(err)
        assert "max_size_bytes" in err.suggestion

    def test_quota_exceeded(self) -> None:
        """Quota exceeded error."""
        err = QuotaExceededError(
            tool="fs.read",
            current_count=100,
            max_count=100,
        )
        assert "100" in str(err)
        assert "max_calls_per_tool" in err.suggestion


class TestToolErrors:
    """Tests for tool execution errors."""

    def test_tool_not_found(self) -> None:
        """Tool not found error."""
        err = ToolNotFoundError(tool="unknown.tool")
        assert err.code == ERROR_TOOL_NOT_FOUND
        assert "unknown.tool" in str(err)
        assert "register" in err.suggestion.lower()

    def test_tool_execution_error(self) -> None:
        """Tool execution failed error."""
        err = ToolExecutionError(
            tool="fs.read",
            tool_args={"path": "./file.txt"},
            underlying_error="File not found",
        )
        assert "fs.read" in str(err)
        assert "File not found" in str(err)

    def test_tool_timeout(self) -> None:
        """Tool timeout error."""
        err = ToolTimeoutError(
            tool="shell.run",
            timeout_seconds=30,
        )
        assert "30" in str(err)
        assert "timeout" in err.suggestion.lower()


class TestPlanErrors:
    """Tests for plan validation errors."""

    def test_plan_empty(self) -> None:
        """Empty plan error."""
        err = PlanEmptyError()
        assert "at least one step" in str(err)

    def test_plan_with_step_context(self) -> None:
        """Plan error with step context."""
        err = PlanValidationError(
            message="Invalid step",
            step_index=3,
            step_id="step-4",
        )
        assert err.context["step_index"] == 3
        assert err.context["step_id"] == "step-4"


class TestReplayErrors:
    """Tests for replay errors."""

    def test_run_not_found(self) -> None:
        """Run not found for replay."""
        err = ReplayRunNotFoundError(run_id="abc123")
        assert "abc123" in str(err)

    def test_replay_mismatch(self) -> None:
        """Replay mismatch error."""
        err = ReplayMismatchError(
            run_id="abc123",
            expected="fs.read",
            actual="fs.write",
            mismatch_type="tool",
        )
        assert "fs.read" in str(err)
        assert "fs.write" in str(err)
        assert "tool" in str(err)

    def test_hash_mismatch(self) -> None:
        """Hash mismatch error."""
        err = ReplayHashMismatchError(
            run_id="abc123",
            expected_hash="abcd1234567890",
            actual_hash="efgh0987654321",
        )
        assert "abcd1234" in str(err)
        assert "efgh0987" in str(err)


class TestStorageErrors:
    """Tests for storage errors."""

    def test_connection_error(self) -> None:
        """Storage connection error."""
        err = StorageConnectionError(
            db_path="/bad/path.db",
            operation="connect",
        )
        assert err.code == ERROR_STORAGE_CONNECTION
        assert "/bad/path.db" in str(err)
        assert "writable" in err.suggestion.lower()

    def test_write_error(self) -> None:
        """Storage write error."""
        err = StorageWriteError(
            operation="insert",
            underlying_error="Disk full",
        )
        assert "Disk full" in str(err)

    def test_storage_hierarchy(self) -> None:
        """Storage errors inherit properly."""
        err = StorageConnectionError(db_path="/test.db")
        assert isinstance(err, StorageError)
        assert isinstance(err, CapsuleError)


class TestErrorHierarchy:
    """Test that error hierarchy works correctly."""

    def test_catch_all_capsule_errors(self) -> None:
        """All errors catchable as CapsuleError."""
        errors = [
            PolicyDeniedError(tool="test", reason="test"),
            ToolNotFoundError(tool="test"),
            PlanEmptyError(),
            ReplayRunNotFoundError(run_id="test"),
            StorageConnectionError(db_path="/test.db"),
        ]
        for err in errors:
            assert isinstance(err, CapsuleError)
            with pytest.raises(CapsuleError):
                raise err

    def test_catch_specific_errors(self) -> None:
        """Specific errors catchable by their type."""
        with pytest.raises(PolicyDeniedError):
            raise PathBlockedError(path="/test")

        with pytest.raises(ToolError):
            raise ToolExecutionError(tool="test", underlying_error="fail")

        with pytest.raises(StorageError):
            raise StorageWriteError(operation="insert", underlying_error="fail")
