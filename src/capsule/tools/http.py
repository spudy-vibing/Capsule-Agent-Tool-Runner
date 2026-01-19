"""
HTTP tools for Capsule.

This module provides tools for making HTTP requests:
- http.get: Make GET requests to fetch data from URLs

Security Note:
    Policy enforcement happens BEFORE these tools execute.
    By the time execute() is called, the domain has been validated
    against allow_domains and other policy rules.

    However, these tools implement additional security measures:
    - DNS rebinding prevention: Resolve DNS and verify IP before request
    - Private IP blocking: Double-check resolved IP is not private
    - Response size limits: Stop reading if response exceeds limit
    - Timeout enforcement: Abort requests that take too long
"""

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from capsule.tools.base import Tool, ToolContext, ToolOutput


# Private IP ranges to block
PRIVATE_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 private
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]


def is_private_ip(ip_str: str) -> bool:
    """
    Check if an IP address is in a private range.

    Args:
        ip_str: IP address as a string

    Returns:
        True if the IP is private, False otherwise
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_reserved
            or ip.is_link_local
            or any(ip in network for network in PRIVATE_IP_RANGES)
        )
    except ValueError:
        # Invalid IP address
        return False


def resolve_hostname(hostname: str) -> list[str]:
    """
    Resolve a hostname to IP addresses.

    This is used for DNS rebinding prevention - we resolve the hostname
    BEFORE making the request and verify the IP is not private.

    Args:
        hostname: The hostname to resolve

    Returns:
        List of IP addresses

    Raises:
        socket.gaierror: If DNS resolution fails
    """
    try:
        # Get all address info (both IPv4 and IPv6)
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        # Extract unique IP addresses
        ips = list({info[4][0] for info in addr_info})
        return ips
    except socket.gaierror:
        raise


class HttpGetTool(Tool):
    """
    Make HTTP GET requests.

    Arguments:
        url (str): The URL to fetch (required)
        headers (dict): Optional headers to include in the request
        timeout (int): Request timeout in seconds (default: from policy)

    Returns:
        On success: Dict with status_code, headers, and body
        On failure: Error message describing what went wrong

    Security Features:
        - DNS rebinding prevention: Resolves DNS before request
        - Private IP blocking: Blocks requests to private IP ranges
        - Response size limits: Stops reading if response exceeds limit
        - Timeout enforcement: Aborts requests that take too long

    Example:
        args = {"url": "https://api.github.com/users/octocat"}
        output = tool.execute(args, context)
        if output.success:
            data = output.data["body"]
    """

    @property
    def name(self) -> str:
        return "http.get"

    @property
    def description(self) -> str:
        return "Make HTTP GET request to fetch data from a URL"

    def validate_args(self, args: dict[str, Any]) -> list[str]:
        """Validate http.get arguments."""
        errors = []

        # url is required
        if "url" not in args:
            errors.append("'url' is required")
        elif not isinstance(args["url"], str):
            errors.append("'url' must be a string")
        elif not args["url"].strip():
            errors.append("'url' cannot be empty")
        else:
            # Validate URL format
            try:
                parsed = urlparse(args["url"])
                if not parsed.scheme:
                    errors.append("'url' must have a scheme (http:// or https://)")
                elif parsed.scheme not in ("http", "https"):
                    errors.append("'url' scheme must be http or https")
                if not parsed.netloc:
                    errors.append("'url' must have a host")
            except Exception as e:
                errors.append(f"'url' is invalid: {e}")

        # headers must be a dict if provided
        if "headers" in args:
            if not isinstance(args["headers"], dict):
                errors.append("'headers' must be a dictionary")
            else:
                for key, value in args["headers"].items():
                    if not isinstance(key, str):
                        errors.append("Header keys must be strings")
                        break
                    if not isinstance(value, str):
                        errors.append("Header values must be strings")
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
        Execute an HTTP GET request.

        Args:
            args: Must contain 'url', optionally 'headers' and 'timeout'
            context: Runtime context with policy reference

        Returns:
            ToolOutput with response data or error
        """
        # Validate arguments
        errors = self.validate_args(args)
        if errors:
            return ToolOutput.fail(f"Invalid arguments: {'; '.join(errors)}")

        # Extract arguments
        url = args["url"]
        headers = args.get("headers", {})

        # Get timeout and max size from policy if available
        timeout_seconds = args.get("timeout", 30)
        max_response_bytes = 10 * 1024 * 1024  # Default 10 MB

        if context.policy:
            timeout_seconds = args.get("timeout", context.policy.tools.http_get.timeout_seconds)
            max_response_bytes = context.policy.tools.http_get.max_response_bytes

        # Parse URL to get hostname
        parsed = urlparse(url)
        hostname = parsed.hostname

        if not hostname:
            return ToolOutput.fail("Could not extract hostname from URL")

        # DNS rebinding prevention: Resolve hostname and check IPs
        try:
            resolved_ips = resolve_hostname(hostname)
        except socket.gaierror as e:
            return ToolOutput.fail(
                f"DNS resolution failed for {hostname}: {e}",
                hostname=hostname,
            )

        if not resolved_ips:
            return ToolOutput.fail(
                f"No IP addresses found for {hostname}",
                hostname=hostname,
            )

        # Check all resolved IPs for private ranges
        for ip in resolved_ips:
            if is_private_ip(ip):
                return ToolOutput.fail(
                    f"DNS rebinding blocked: {hostname} resolves to private IP {ip}",
                    hostname=hostname,
                    resolved_ip=ip,
                )

        # Make the request
        try:
            with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
                response = client.get(url, headers=headers)

                # Check response size before reading body
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > max_response_bytes:
                            return ToolOutput.fail(
                                f"Response too large: {content_length} bytes (max: {max_response_bytes})",
                                content_length=int(content_length),
                                max_bytes=max_response_bytes,
                            )
                    except ValueError:
                        pass  # Invalid content-length header, continue

                # Read body with size limit
                body_chunks = []
                total_size = 0

                for chunk in response.iter_bytes(chunk_size=8192):
                    total_size += len(chunk)
                    if total_size > max_response_bytes:
                        return ToolOutput.fail(
                            f"Response exceeded size limit: {total_size} bytes (max: {max_response_bytes})",
                            bytes_read=total_size,
                            max_bytes=max_response_bytes,
                        )
                    body_chunks.append(chunk)

                body_bytes = b"".join(body_chunks)

                # Try to decode as text
                try:
                    body = body_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    # Return as base64 for binary content
                    import base64
                    body = base64.b64encode(body_bytes).decode("ascii")

                # Build response headers dict
                response_headers = dict(response.headers)

                return ToolOutput.ok(
                    {
                        "status_code": response.status_code,
                        "headers": response_headers,
                        "body": body,
                        "url": str(response.url),  # Final URL after redirects
                    },
                    url=url,
                    final_url=str(response.url),
                    status_code=response.status_code,
                    body_size=len(body_bytes),
                )

        except httpx.TimeoutException:
            return ToolOutput.fail(
                f"Request timed out after {timeout_seconds} seconds",
                url=url,
                timeout=timeout_seconds,
            )
        except httpx.TooManyRedirects:
            return ToolOutput.fail(
                "Too many redirects",
                url=url,
            )
        except httpx.RequestError as e:
            return ToolOutput.fail(
                f"Request failed: {e}",
                url=url,
                error_type=type(e).__name__,
            )
        except Exception as e:
            return ToolOutput.fail(
                f"Unexpected error: {e}",
                url=url,
                error_type=type(e).__name__,
            )


# Register tools in the default registry
def register_http_tools() -> None:
    """Register all HTTP tools in the default registry."""
    from capsule.tools.registry import default_registry

    default_registry.register(HttpGetTool())
