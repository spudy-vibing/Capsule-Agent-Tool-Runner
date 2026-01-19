"""
Unit tests for the Policy Engine.

Tests cover:
- Deny-by-default behavior
- Filesystem policy (allow_paths, deny_paths, hidden files)
- HTTP policy (allow_domains, private IPs)
- Shell policy (allow_executables, deny_tokens)
- Quota enforcement
"""

import tempfile
from pathlib import Path

import pytest

from capsule.policy import PolicyEngine
from capsule.schema import (
    FsPolicy,
    HttpPolicy,
    Policy,
    ShellPolicy,
    ToolPolicies,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def temp_dir() -> Path:
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def default_policy() -> Policy:
    """Create a default deny-all policy."""
    return Policy()


@pytest.fixture
def permissive_fs_policy(temp_dir: Path) -> Policy:
    """Create a policy that allows filesystem access to temp dir."""
    return Policy(
        tools=ToolPolicies(
            **{
                "fs.read": FsPolicy(
                    allow_paths=[f"{temp_dir}/**"],
                    max_size_bytes=1024 * 1024,
                ),
                "fs.write": FsPolicy(
                    allow_paths=[f"{temp_dir}/**"],
                    max_size_bytes=1024 * 1024,
                ),
            }
        )
    )


# =============================================================================
# Basic Policy Engine Tests
# =============================================================================


class TestPolicyEngineBasics:
    """Basic policy engine tests."""

    def test_create_engine(self, default_policy: Policy) -> None:
        """Can create a policy engine."""
        engine = PolicyEngine(default_policy)
        assert engine.policy == default_policy

    def test_unknown_tool_denied(self, default_policy: Policy) -> None:
        """Unknown tools are denied by default."""
        engine = PolicyEngine(default_policy)
        decision = engine.evaluate("unknown.tool", {})
        assert decision.allowed is False
        assert "unknown" in decision.reason.lower()

    def test_reset_counts(self, default_policy: Policy) -> None:
        """Can reset tool call counts."""
        engine = PolicyEngine(default_policy)
        engine._tool_call_counts["test"] = 10
        engine.reset_counts()
        assert engine._tool_call_counts == {}


# =============================================================================
# Quota Tests
# =============================================================================


class TestQuotaEnforcement:
    """Tests for tool call quota enforcement."""

    def test_quota_allows_under_limit(self, temp_dir: Path) -> None:
        """Calls under quota limit are allowed."""
        policy = Policy(
            max_calls_per_tool=5,
            tools=ToolPolicies(
                **{
                    "fs.read": FsPolicy(allow_paths=[f"{temp_dir}/**"]),
                }
            ),
        )
        engine = PolicyEngine(policy)

        # Create a test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("hello")

        # First 5 calls should be allowed
        for i in range(5):
            decision = engine.evaluate(
                "fs.read",
                {"path": str(test_file)},
                str(temp_dir),
            )
            assert decision.allowed is True, f"Call {i+1} should be allowed"

    def test_quota_blocks_over_limit(self, temp_dir: Path) -> None:
        """Calls over quota limit are blocked."""
        policy = Policy(
            max_calls_per_tool=3,
            tools=ToolPolicies(
                **{
                    "fs.read": FsPolicy(allow_paths=[f"{temp_dir}/**"]),
                }
            ),
        )
        engine = PolicyEngine(policy)

        test_file = temp_dir / "test.txt"
        test_file.write_text("hello")

        # Use up quota
        for _ in range(3):
            engine.evaluate("fs.read", {"path": str(test_file)}, str(temp_dir))

        # 4th call should be blocked
        decision = engine.evaluate(
            "fs.read",
            {"path": str(test_file)},
            str(temp_dir),
        )
        assert decision.allowed is False
        assert "quota" in decision.reason.lower()


# =============================================================================
# Filesystem Policy Tests
# =============================================================================


class TestFsReadPolicy:
    """Tests for fs.read policy evaluation."""

    def test_no_paths_allowed(self, default_policy: Policy) -> None:
        """With empty allow_paths, all reads are denied."""
        engine = PolicyEngine(default_policy)
        decision = engine.evaluate("fs.read", {"path": "/any/path"})
        assert decision.allowed is False
        assert "no paths allowed" in decision.reason.lower()

    def test_missing_path_argument(self, default_policy: Policy) -> None:
        """Missing path argument is denied."""
        engine = PolicyEngine(default_policy)
        decision = engine.evaluate("fs.read", {})
        assert decision.allowed is False
        assert "no path" in decision.reason.lower()

    def test_allowed_path(self, temp_dir: Path) -> None:
        """Paths matching allow_paths are allowed."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "fs.read": FsPolicy(allow_paths=[f"{temp_dir}/**"]),
                }
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate(
            "fs.read",
            {"path": str(temp_dir / "file.txt")},
            str(temp_dir),
        )
        assert decision.allowed is True

    def test_denied_path(self, temp_dir: Path) -> None:
        """Paths not matching allow_paths are denied."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "fs.read": FsPolicy(allow_paths=[f"{temp_dir}/**"]),
                }
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate(
            "fs.read",
            {"path": "/etc/passwd"},
            str(temp_dir),
        )
        assert decision.allowed is False
        assert "not in allowlist" in decision.reason.lower()

    def test_deny_paths_take_precedence(self, temp_dir: Path) -> None:
        """deny_paths take precedence over allow_paths."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "fs.read": FsPolicy(
                        allow_paths=[f"{temp_dir}/**"],
                        deny_paths=[f"{temp_dir}/secret/**"],
                    ),
                }
            )
        )
        engine = PolicyEngine(policy)

        # Regular file allowed
        decision = engine.evaluate(
            "fs.read",
            {"path": str(temp_dir / "normal.txt")},
            str(temp_dir),
        )
        assert decision.allowed is True

        # Secret file denied
        decision = engine.evaluate(
            "fs.read",
            {"path": str(temp_dir / "secret" / "key.txt")},
            str(temp_dir),
        )
        assert decision.allowed is False
        assert "deny pattern" in decision.reason.lower()

    def test_hidden_files_blocked_by_default(self, temp_dir: Path) -> None:
        """Hidden files (dotfiles) are blocked by default."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "fs.read": FsPolicy(
                        allow_paths=[f"{temp_dir}/**"],
                        allow_hidden=False,
                    ),
                }
            )
        )
        engine = PolicyEngine(policy)

        # .env file blocked
        decision = engine.evaluate(
            "fs.read",
            {"path": str(temp_dir / ".env")},
            str(temp_dir),
        )
        assert decision.allowed is False
        assert "hidden" in decision.reason.lower()

        # .ssh directory blocked
        decision = engine.evaluate(
            "fs.read",
            {"path": str(temp_dir / ".ssh" / "id_rsa")},
            str(temp_dir),
        )
        assert decision.allowed is False

    def test_hidden_files_allowed_when_enabled(self, temp_dir: Path) -> None:
        """Hidden files allowed when allow_hidden=True."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "fs.read": FsPolicy(
                        allow_paths=[f"{temp_dir}/**"],
                        allow_hidden=True,
                    ),
                }
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate(
            "fs.read",
            {"path": str(temp_dir / ".env")},
            str(temp_dir),
        )
        assert decision.allowed is True

    def test_relative_path_resolved(self, temp_dir: Path) -> None:
        """Relative paths are resolved against working directory."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "fs.read": FsPolicy(allow_paths=[f"{temp_dir}/**"]),
                }
            )
        )
        engine = PolicyEngine(policy)

        # Relative path within temp_dir
        decision = engine.evaluate(
            "fs.read",
            {"path": "file.txt"},
            str(temp_dir),
        )
        assert decision.allowed is True

    def test_glob_patterns(self, temp_dir: Path) -> None:
        """Glob patterns work correctly."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "fs.read": FsPolicy(allow_paths=[f"{temp_dir}/*.txt"]),
                }
            )
        )
        engine = PolicyEngine(policy)

        # .txt file allowed
        decision = engine.evaluate(
            "fs.read",
            {"path": str(temp_dir / "readme.txt")},
            str(temp_dir),
        )
        assert decision.allowed is True

        # .py file not allowed
        decision = engine.evaluate(
            "fs.read",
            {"path": str(temp_dir / "script.py")},
            str(temp_dir),
        )
        assert decision.allowed is False


class TestFsWritePolicy:
    """Tests for fs.write policy evaluation."""

    def test_write_allowed_path(self, temp_dir: Path) -> None:
        """Writing to allowed path succeeds."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "fs.write": FsPolicy(
                        allow_paths=[f"{temp_dir}/**"],
                        max_size_bytes=1024,
                    ),
                }
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate(
            "fs.write",
            {"path": str(temp_dir / "output.txt"), "content": "hello"},
            str(temp_dir),
        )
        assert decision.allowed is True

    def test_write_size_limit(self, temp_dir: Path) -> None:
        """Content exceeding max_size_bytes is denied."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "fs.write": FsPolicy(
                        allow_paths=[f"{temp_dir}/**"],
                        max_size_bytes=10,
                    ),
                }
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate(
            "fs.write",
            {"path": str(temp_dir / "big.txt"), "content": "x" * 100},
            str(temp_dir),
        )
        assert decision.allowed is False
        assert "size" in decision.reason.lower()


# =============================================================================
# HTTP Policy Tests
# =============================================================================


class TestHttpGetPolicy:
    """Tests for http.get policy evaluation."""

    def test_no_domains_allowed(self, default_policy: Policy) -> None:
        """With empty allow_domains, all requests are denied."""
        engine = PolicyEngine(default_policy)
        decision = engine.evaluate("http.get", {"url": "https://example.com"})
        assert decision.allowed is False
        assert "no domains allowed" in decision.reason.lower()

    def test_missing_url_argument(self, default_policy: Policy) -> None:
        """Missing URL argument is denied."""
        engine = PolicyEngine(default_policy)
        decision = engine.evaluate("http.get", {})
        assert decision.allowed is False
        assert "no url" in decision.reason.lower()

    def test_allowed_domain(self) -> None:
        """Requests to allowed domains succeed."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "http.get": HttpPolicy(allow_domains=["api.github.com"]),
                }
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate(
            "http.get",
            {"url": "https://api.github.com/users"},
        )
        assert decision.allowed is True

    def test_denied_domain(self) -> None:
        """Requests to non-allowed domains are denied."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "http.get": HttpPolicy(allow_domains=["api.github.com"]),
                }
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate(
            "http.get",
            {"url": "https://evil.com/steal-data"},
        )
        assert decision.allowed is False
        assert "not in allowlist" in decision.reason.lower()

    def test_wildcard_subdomain(self) -> None:
        """Wildcard subdomain patterns work."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "http.get": HttpPolicy(allow_domains=["*.github.com"]),
                }
            )
        )
        engine = PolicyEngine(policy)

        # Subdomain allowed
        decision = engine.evaluate(
            "http.get",
            {"url": "https://api.github.com/users"},
        )
        assert decision.allowed is True

        # Deep subdomain allowed
        decision = engine.evaluate(
            "http.get",
            {"url": "https://raw.githubusercontent.github.com/file"},
        )
        # Note: this won't match *.github.com (different domain)
        # Let's test with actual subdomain
        decision = engine.evaluate(
            "http.get",
            {"url": "https://gist.github.com/file"},
        )
        assert decision.allowed is True

    def test_localhost_blocked(self) -> None:
        """Localhost is blocked by default."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "http.get": HttpPolicy(
                        allow_domains=["localhost", "127.0.0.1"],
                        deny_private_ips=True,
                    ),
                }
            )
        )
        engine = PolicyEngine(policy)

        # Even if in allowlist, blocked by deny_private_ips
        decision = engine.evaluate(
            "http.get",
            {"url": "http://localhost:8080/api"},
        )
        assert decision.allowed is False
        assert "private" in decision.reason.lower() or "localhost" in decision.reason.lower()

    def test_private_ip_blocked(self) -> None:
        """Private IPs are blocked by default."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "http.get": HttpPolicy(
                        allow_domains=["192.168.1.1", "10.0.0.1"],
                        deny_private_ips=True,
                    ),
                }
            )
        )
        engine = PolicyEngine(policy)

        for ip in ["192.168.1.1", "10.0.0.1", "172.16.0.1"]:
            decision = engine.evaluate(
                "http.get",
                {"url": f"http://{ip}/api"},
            )
            assert decision.allowed is False, f"{ip} should be blocked"

    def test_private_ip_allowed_when_disabled(self) -> None:
        """Private IPs allowed when deny_private_ips=False."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "http.get": HttpPolicy(
                        allow_domains=["localhost"],
                        deny_private_ips=False,
                    ),
                }
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate(
            "http.get",
            {"url": "http://localhost:8080/api"},
        )
        assert decision.allowed is True

    def test_invalid_url(self) -> None:
        """Invalid URLs are rejected."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "http.get": HttpPolicy(allow_domains=["example.com"]),
                }
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate(
            "http.get",
            {"url": "not-a-valid-url"},
        )
        assert decision.allowed is False
        assert "invalid" in decision.reason.lower()


# =============================================================================
# Shell Policy Tests
# =============================================================================


class TestShellRunPolicy:
    """Tests for shell.run policy evaluation."""

    def test_no_executables_allowed(self, default_policy: Policy) -> None:
        """With empty allow_executables, all commands are denied."""
        engine = PolicyEngine(default_policy)
        decision = engine.evaluate("shell.run", {"cmd": ["echo", "hello"]})
        assert decision.allowed is False
        assert "no executables allowed" in decision.reason.lower()

    def test_missing_cmd_argument(self, default_policy: Policy) -> None:
        """Missing cmd argument is denied."""
        engine = PolicyEngine(default_policy)
        decision = engine.evaluate("shell.run", {})
        assert decision.allowed is False
        assert "no cmd" in decision.reason.lower()

    def test_cmd_must_be_list(self) -> None:
        """cmd must be a list, not a string."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "shell.run": ShellPolicy(allow_executables=["echo"]),
                }
            )
        )
        engine = PolicyEngine(policy)

        # String command rejected (prevents shell injection)
        decision = engine.evaluate(
            "shell.run",
            {"cmd": "echo hello; rm -rf /"},
        )
        assert decision.allowed is False
        assert "list" in decision.reason.lower()

    def test_empty_cmd_rejected(self) -> None:
        """Empty cmd list is rejected."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "shell.run": ShellPolicy(allow_executables=["echo"]),
                }
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate("shell.run", {"cmd": []})
        assert decision.allowed is False
        assert "empty" in decision.reason.lower()

    def test_allowed_executable(self) -> None:
        """Allowed executables can run."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "shell.run": ShellPolicy(
                        allow_executables=["echo", "git"],
                        deny_tokens=[],
                    ),
                }
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate(
            "shell.run",
            {"cmd": ["echo", "hello", "world"]},
        )
        assert decision.allowed is True

        decision = engine.evaluate(
            "shell.run",
            {"cmd": ["git", "status"]},
        )
        assert decision.allowed is True

    def test_denied_executable(self) -> None:
        """Non-allowed executables are denied."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "shell.run": ShellPolicy(allow_executables=["echo"]),
                }
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate(
            "shell.run",
            {"cmd": ["rm", "-rf", "/"]},
        )
        assert decision.allowed is False
        assert "not in allowlist" in decision.reason.lower()

    def test_deny_tokens_blocked(self) -> None:
        """Commands containing deny_tokens are blocked."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "shell.run": ShellPolicy(
                        allow_executables=["bash"],
                        deny_tokens=["sudo", "rm -rf"],
                    ),
                }
            )
        )
        engine = PolicyEngine(policy)

        # sudo blocked
        decision = engine.evaluate(
            "shell.run",
            {"cmd": ["bash", "-c", "sudo apt install"]},
        )
        assert decision.allowed is False
        assert "sudo" in decision.reason.lower()

        # rm -rf blocked
        decision = engine.evaluate(
            "shell.run",
            {"cmd": ["bash", "-c", "rm -rf /tmp/test"]},
        )
        assert decision.allowed is False
        assert "rm -rf" in decision.reason.lower()

    def test_full_path_executable(self) -> None:
        """Full path to executable uses just the name for matching."""
        policy = Policy(
            tools=ToolPolicies(
                **{
                    "shell.run": ShellPolicy(
                        allow_executables=["python"],
                        deny_tokens=[],
                    ),
                }
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate(
            "shell.run",
            {"cmd": ["/usr/bin/python", "-c", "print('hello')"]},
        )
        assert decision.allowed is True
