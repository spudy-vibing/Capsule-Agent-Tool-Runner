"""
Unit tests for HTTP tools.

Tests for http.get tool functionality including:
- Argument validation
- URL parsing
- Response handling
- Error cases
"""

from unittest.mock import MagicMock, patch

import pytest

from capsule.schema import HttpPolicy, Policy, ToolPolicies
from capsule.tools.base import ToolContext
from capsule.tools.http import HttpGetTool, is_private_ip, resolve_hostname


class TestHttpGetToolValidation:
    """Tests for http.get argument validation."""

    def test_url_required(self) -> None:
        """Test that url is required."""
        tool = HttpGetTool()

        errors = tool.validate_args({})
        assert len(errors) > 0
        assert any("url" in e.lower() and "required" in e.lower() for e in errors)

    def test_url_must_be_string(self) -> None:
        """Test that url must be a string."""
        tool = HttpGetTool()

        errors = tool.validate_args({"url": 123})
        assert len(errors) > 0
        assert any("string" in e.lower() for e in errors)

    def test_url_cannot_be_empty(self) -> None:
        """Test that url cannot be empty."""
        tool = HttpGetTool()

        errors = tool.validate_args({"url": ""})
        assert len(errors) > 0
        assert any("empty" in e.lower() for e in errors)

    def test_url_must_have_scheme(self) -> None:
        """Test that url must have a scheme."""
        tool = HttpGetTool()

        errors = tool.validate_args({"url": "example.com/path"})
        assert len(errors) > 0
        assert any("scheme" in e.lower() for e in errors)

    def test_url_scheme_must_be_http(self) -> None:
        """Test that url scheme must be http or https."""
        tool = HttpGetTool()

        errors = tool.validate_args({"url": "ftp://example.com"})
        assert len(errors) > 0
        assert any("http" in e.lower() for e in errors)

    def test_url_must_have_host(self) -> None:
        """Test that url must have a host."""
        tool = HttpGetTool()

        errors = tool.validate_args({"url": "http://"})
        assert len(errors) > 0
        assert any("host" in e.lower() for e in errors)

    def test_valid_http_url(self) -> None:
        """Test that valid http url passes validation."""
        tool = HttpGetTool()

        assert tool.validate_args({"url": "http://example.com"}) == []
        assert tool.validate_args({"url": "https://example.com"}) == []
        assert tool.validate_args({"url": "https://example.com:8080/path"}) == []
        assert tool.validate_args({"url": "https://example.com/path?query=1"}) == []

    def test_headers_must_be_dict(self) -> None:
        """Test that headers must be a dictionary."""
        tool = HttpGetTool()

        errors = tool.validate_args({"url": "https://example.com", "headers": "not-a-dict"})
        assert len(errors) > 0
        assert any("dict" in e.lower() for e in errors)

    def test_headers_keys_must_be_strings(self) -> None:
        """Test that header keys must be strings."""
        tool = HttpGetTool()

        errors = tool.validate_args({"url": "https://example.com", "headers": {123: "value"}})
        assert len(errors) > 0
        assert any("string" in e.lower() for e in errors)

    def test_headers_values_must_be_strings(self) -> None:
        """Test that header values must be strings."""
        tool = HttpGetTool()

        errors = tool.validate_args({"url": "https://example.com", "headers": {"key": 123}})
        assert len(errors) > 0
        assert any("string" in e.lower() for e in errors)

    def test_valid_headers(self) -> None:
        """Test that valid headers pass validation."""
        tool = HttpGetTool()

        errors = tool.validate_args({
            "url": "https://example.com",
            "headers": {"Authorization": "Bearer token", "Accept": "application/json"},
        })
        assert errors == []

    def test_timeout_must_be_number(self) -> None:
        """Test that timeout must be a number."""
        tool = HttpGetTool()

        errors = tool.validate_args({"url": "https://example.com", "timeout": "30"})
        assert len(errors) > 0
        assert any("number" in e.lower() for e in errors)

    def test_timeout_must_be_positive(self) -> None:
        """Test that timeout must be positive."""
        tool = HttpGetTool()

        errors = tool.validate_args({"url": "https://example.com", "timeout": 0})
        assert len(errors) > 0
        assert any("positive" in e.lower() for e in errors)

        errors = tool.validate_args({"url": "https://example.com", "timeout": -5})
        assert len(errors) > 0


class TestHttpGetToolExecution:
    """Tests for http.get execution."""

    def test_dns_resolution_failure(self) -> None:
        """Test handling of DNS resolution failure."""
        tool = HttpGetTool()
        context = ToolContext(run_id="test-run")

        with patch("capsule.tools.http.resolve_hostname") as mock_resolve:
            import socket
            mock_resolve.side_effect = socket.gaierror("DNS failed")

            result = tool.execute({"url": "https://nonexistent.example.com"}, context)

            assert result.success is False
            assert "dns" in result.error.lower()

    def test_private_ip_blocked(self) -> None:
        """Test that private IPs are blocked after DNS resolution."""
        tool = HttpGetTool()
        context = ToolContext(run_id="test-run")

        with patch("capsule.tools.http.resolve_hostname") as mock_resolve:
            mock_resolve.return_value = ["192.168.1.100"]

            result = tool.execute({"url": "https://example.com"}, context)

            assert result.success is False
            assert "rebinding" in result.error.lower() or "private" in result.error.lower()

    def test_successful_request(self) -> None:
        """Test successful HTTP request."""
        tool = HttpGetTool()
        context = ToolContext(run_id="test-run")

        with (
            patch("capsule.tools.http.resolve_hostname") as mock_resolve,
            patch("httpx.Client") as mock_client,
        ):
            mock_resolve.return_value = ["93.184.216.34"]  # example.com

            # Mock response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/html"}
            mock_response.iter_bytes.return_value = [b"Hello World"]
            mock_response.url = "https://example.com/"

            mock_client_instance = MagicMock()
            mock_client_instance.get.return_value = mock_response
            mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
            mock_client_instance.__exit__ = MagicMock(return_value=False)
            mock_client.return_value = mock_client_instance

            result = tool.execute({"url": "https://example.com"}, context)

            assert result.success is True
            assert result.data["status_code"] == 200
            assert result.data["body"] == "Hello World"

    def test_request_with_custom_headers(self) -> None:
        """Test request with custom headers."""
        tool = HttpGetTool()
        context = ToolContext(run_id="test-run")

        with (
            patch("capsule.tools.http.resolve_hostname") as mock_resolve,
            patch("httpx.Client") as mock_client,
        ):
            mock_resolve.return_value = ["93.184.216.34"]

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.iter_bytes.return_value = [b"OK"]
            mock_response.url = "https://example.com/"

            mock_client_instance = MagicMock()
            mock_client_instance.get.return_value = mock_response
            mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
            mock_client_instance.__exit__ = MagicMock(return_value=False)
            mock_client.return_value = mock_client_instance

            result = tool.execute({
                "url": "https://example.com",
                "headers": {"Authorization": "Bearer token"},
            }, context)

            # Verify headers were passed
            mock_client_instance.get.assert_called_once()
            call_kwargs = mock_client_instance.get.call_args
            assert call_kwargs[1]["headers"] == {"Authorization": "Bearer token"}


class TestIsPrivateIP:
    """Tests for is_private_ip helper function."""

    def test_loopback_ipv4(self) -> None:
        """Test IPv4 loopback detection."""
        assert is_private_ip("127.0.0.1") is True
        assert is_private_ip("127.255.255.255") is True

    def test_private_class_a(self) -> None:
        """Test Class A private IP detection."""
        assert is_private_ip("10.0.0.1") is True
        assert is_private_ip("10.255.255.255") is True

    def test_private_class_b(self) -> None:
        """Test Class B private IP detection."""
        assert is_private_ip("172.16.0.1") is True
        assert is_private_ip("172.31.255.255") is True
        # Not in range
        assert is_private_ip("172.15.0.1") is False
        assert is_private_ip("172.32.0.1") is False

    def test_private_class_c(self) -> None:
        """Test Class C private IP detection."""
        assert is_private_ip("192.168.0.1") is True
        assert is_private_ip("192.168.255.255") is True

    def test_link_local(self) -> None:
        """Test link-local IP detection."""
        assert is_private_ip("169.254.0.1") is True
        assert is_private_ip("169.254.255.255") is True

    def test_public_ips(self) -> None:
        """Test that public IPs are not marked as private."""
        assert is_private_ip("8.8.8.8") is False
        assert is_private_ip("1.1.1.1") is False
        assert is_private_ip("142.250.185.46") is False

    def test_ipv6_loopback(self) -> None:
        """Test IPv6 loopback detection."""
        assert is_private_ip("::1") is True

    def test_invalid_ip(self) -> None:
        """Test that invalid IPs return False."""
        assert is_private_ip("not-an-ip") is False
        assert is_private_ip("") is False


class TestToolProperties:
    """Tests for tool properties."""

    def test_tool_name(self) -> None:
        """Test that tool has correct name."""
        tool = HttpGetTool()
        assert tool.name == "http.get"

    def test_tool_description(self) -> None:
        """Test that tool has a description."""
        tool = HttpGetTool()
        assert len(tool.description) > 0
        assert "http" in tool.description.lower() or "get" in tool.description.lower()
