"""
Security tests for HTTP tools.

These tests verify that the http.get tool properly:
1. Blocks requests to private IP ranges
2. Prevents DNS rebinding attacks
3. Enforces response size limits
4. Handles timeout properly

These are security-critical tests - failures here indicate
potential vulnerabilities in the HTTP tool.
"""

import socket
from unittest.mock import MagicMock, patch

import pytest

from capsule.policy.engine import PolicyEngine
from capsule.schema import HttpPolicy, Policy, ToolPolicies
from capsule.tools.base import ToolContext
from capsule.tools.http import HttpGetTool, is_private_ip, resolve_hostname


class TestPrivateIPBlocking:
    """Tests for private IP range blocking."""

    @pytest.mark.parametrize(
        "ip,expected",
        [
            # IPv4 private ranges
            ("10.0.0.1", True),
            ("10.255.255.255", True),
            ("172.16.0.1", True),
            ("172.31.255.255", True),
            ("192.168.0.1", True),
            ("192.168.255.255", True),
            # Loopback
            ("127.0.0.1", True),
            ("127.255.255.255", True),
            # Link-local
            ("169.254.0.1", True),
            ("169.254.255.255", True),
            # Public IPs (should not be blocked)
            ("8.8.8.8", False),
            ("1.1.1.1", False),
            ("142.250.185.46", False),  # google.com
            ("151.101.1.140", False),  # reddit.com
            # IPv6 loopback
            ("::1", True),
            # IPv6 private (ULA)
            ("fc00::1", True),
            ("fd00::1", True),
            # IPv6 link-local
            ("fe80::1", True),
            # IPv6 public (should not be blocked)
            ("2607:f8b0:4004:800::200e", False),  # google.com
        ],
    )
    def test_is_private_ip(self, ip: str, expected: bool) -> None:
        """Test that private IPs are correctly identified."""
        assert is_private_ip(ip) == expected, f"Expected {ip} to be {'private' if expected else 'public'}"

    def test_invalid_ip_not_private(self) -> None:
        """Test that invalid IPs are not considered private."""
        assert is_private_ip("not-an-ip") is False
        assert is_private_ip("") is False
        assert is_private_ip("999.999.999.999") is False


class TestDNSRebindingPrevention:
    """Tests for DNS rebinding attack prevention."""

    def test_resolve_public_hostname(self) -> None:
        """Test that public hostnames can be resolved."""
        # This test requires network access
        # Skip if no network
        try:
            ips = resolve_hostname("google.com")
            assert len(ips) > 0
            # All IPs should be public
            for ip in ips:
                assert not is_private_ip(ip), f"google.com resolved to private IP: {ip}"
        except socket.gaierror:
            pytest.skip("No network access")

    def test_resolve_localhost(self) -> None:
        """Test that localhost resolves to loopback."""
        ips = resolve_hostname("localhost")
        assert len(ips) > 0
        # All IPs should be loopback
        for ip in ips:
            assert is_private_ip(ip), f"localhost resolved to non-private IP: {ip}"

    def test_resolve_nonexistent_hostname(self) -> None:
        """Test that nonexistent hostnames raise an error."""
        with pytest.raises(socket.gaierror):
            resolve_hostname("this-domain-definitely-does-not-exist-12345.com")

    def test_tool_blocks_private_ip_resolution(self) -> None:
        """Test that the tool blocks requests when DNS resolves to private IP."""
        tool = HttpGetTool()
        context = ToolContext(run_id="test-run")

        # Mock DNS resolution to return a private IP
        with patch("capsule.tools.http.resolve_hostname") as mock_resolve:
            mock_resolve.return_value = ["192.168.1.1"]

            result = tool.execute({"url": "http://evil-site.com/data"}, context)

            assert result.success is False
            assert "DNS rebinding" in result.error
            assert "192.168.1.1" in result.error

    def test_tool_blocks_localhost_resolution(self) -> None:
        """Test that the tool blocks requests when DNS resolves to localhost."""
        tool = HttpGetTool()
        context = ToolContext(run_id="test-run")

        # Mock DNS resolution to return localhost
        with patch("capsule.tools.http.resolve_hostname") as mock_resolve:
            mock_resolve.return_value = ["127.0.0.1"]

            result = tool.execute({"url": "http://sneaky-site.com/admin"}, context)

            assert result.success is False
            assert "DNS rebinding" in result.error
            assert "127.0.0.1" in result.error


class TestPolicyEnforcementHTTP:
    """Tests for policy enforcement on HTTP requests."""

    def test_policy_blocks_unknown_domain(self) -> None:
        """Test that policy blocks requests to non-allowed domains."""
        policy = Policy(
            tools=ToolPolicies(
                http_get=HttpPolicy(
                    allow_domains=["api.github.com"],
                    deny_private_ips=True,
                )
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate("http.get", {"url": "https://evil.com/data"})

        assert decision.allowed is False
        assert "allowlist" in decision.reason.lower()

    def test_policy_allows_listed_domain(self) -> None:
        """Test that policy allows requests to allowed domains."""
        policy = Policy(
            tools=ToolPolicies(
                http_get=HttpPolicy(
                    allow_domains=["api.github.com"],
                    deny_private_ips=True,
                )
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate("http.get", {"url": "https://api.github.com/users/test"})

        assert decision.allowed is True

    def test_policy_blocks_private_ip_url(self) -> None:
        """Test that policy blocks URLs with private IPs when domain matches."""
        policy = Policy(
            tools=ToolPolicies(
                http_get=HttpPolicy(
                    # Allow the IP as a "domain" to test private IP blocking
                    allow_domains=["192.168.1.1"],
                    deny_private_ips=True,
                )
            )
        )
        engine = PolicyEngine(policy)

        # Direct IP in URL - domain matches but private IP should be blocked
        decision = engine.evaluate("http.get", {"url": "http://192.168.1.1/admin"})

        assert decision.allowed is False
        assert "private" in decision.reason.lower()

    def test_policy_blocks_localhost_url(self) -> None:
        """Test that policy blocks URLs to localhost."""
        policy = Policy(
            tools=ToolPolicies(
                http_get=HttpPolicy(
                    allow_domains=["localhost"],
                    deny_private_ips=True,
                )
            )
        )
        engine = PolicyEngine(policy)

        decision = engine.evaluate("http.get", {"url": "http://localhost:8080/admin"})

        assert decision.allowed is False

    def test_wildcard_subdomain_matching(self) -> None:
        """Test that wildcard subdomain patterns work correctly."""
        policy = Policy(
            tools=ToolPolicies(
                http_get=HttpPolicy(
                    allow_domains=["*.github.com"],
                    deny_private_ips=True,
                )
            )
        )
        engine = PolicyEngine(policy)

        # Should allow subdomains
        assert engine.evaluate("http.get", {"url": "https://api.github.com/test"}).allowed
        assert engine.evaluate("http.get", {"url": "https://raw.github.com/test"}).allowed

        # Should also allow the root domain
        assert engine.evaluate("http.get", {"url": "https://github.com/test"}).allowed

        # Should not allow unrelated domains
        assert not engine.evaluate("http.get", {"url": "https://github.org/test"}).allowed


class TestResponseSizeLimits:
    """Tests for response size limit enforcement."""

    def test_tool_rejects_oversized_content_length(self) -> None:
        """Test that tool rejects responses with Content-Length exceeding limit."""
        tool = HttpGetTool()

        # Create policy with small size limit
        policy = Policy(
            tools=ToolPolicies(
                http_get=HttpPolicy(
                    allow_domains=["example.com"],
                    max_response_bytes=100,
                )
            )
        )
        context = ToolContext(run_id="test-run", policy=policy)

        # Mock the HTTP request to return large Content-Length
        with (
            patch("capsule.tools.http.resolve_hostname") as mock_resolve,
            patch("httpx.Client") as mock_client,
        ):
            mock_resolve.return_value = ["93.184.216.34"]  # example.com IP

            # Create mock response
            mock_response = MagicMock()
            mock_response.headers = {"content-length": "1000000"}
            mock_response.status_code = 200

            mock_client_instance = MagicMock()
            mock_client_instance.get.return_value = mock_response
            mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
            mock_client_instance.__exit__ = MagicMock(return_value=False)
            mock_client.return_value = mock_client_instance

            result = tool.execute({"url": "https://example.com/large-file"}, context)

            assert result.success is False
            assert "too large" in result.error.lower()


class TestURLValidation:
    """Tests for URL validation."""

    def test_rejects_missing_scheme(self) -> None:
        """Test that URLs without scheme are rejected."""
        tool = HttpGetTool()

        errors = tool.validate_args({"url": "example.com/path"})
        assert len(errors) > 0
        assert any("scheme" in e.lower() for e in errors)

    def test_rejects_invalid_scheme(self) -> None:
        """Test that non-HTTP schemes are rejected."""
        tool = HttpGetTool()

        errors = tool.validate_args({"url": "ftp://example.com/file"})
        assert len(errors) > 0
        assert any("http" in e.lower() for e in errors)

    def test_rejects_file_scheme(self) -> None:
        """Test that file:// scheme is rejected (SSRF prevention)."""
        tool = HttpGetTool()

        errors = tool.validate_args({"url": "file:///etc/passwd"})
        assert len(errors) > 0

    def test_accepts_valid_http_url(self) -> None:
        """Test that valid HTTP URLs are accepted."""
        tool = HttpGetTool()

        assert tool.validate_args({"url": "http://example.com"}) == []
        assert tool.validate_args({"url": "https://example.com/path"}) == []
        assert tool.validate_args({"url": "https://example.com:8080/path?query=1"}) == []


class TestTimeoutHandling:
    """Tests for timeout enforcement."""

    def test_tool_respects_timeout(self) -> None:
        """Test that tool enforces timeout from policy."""
        tool = HttpGetTool()

        policy = Policy(
            tools=ToolPolicies(
                http_get=HttpPolicy(
                    allow_domains=["example.com"],
                    timeout_seconds=1,
                )
            )
        )
        context = ToolContext(run_id="test-run", policy=policy)

        # Mock to simulate timeout
        with (
            patch("capsule.tools.http.resolve_hostname") as mock_resolve,
            patch("httpx.Client") as mock_client,
        ):
            mock_resolve.return_value = ["93.184.216.34"]

            import httpx

            mock_client_instance = MagicMock()
            mock_client_instance.get.side_effect = httpx.TimeoutException("Timeout")
            mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
            mock_client_instance.__exit__ = MagicMock(return_value=False)
            mock_client.return_value = mock_client_instance

            result = tool.execute({"url": "https://example.com/slow"}, context)

            assert result.success is False
            assert "timed out" in result.error.lower()
