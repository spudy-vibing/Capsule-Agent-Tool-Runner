"""
Policy Engine for Capsule.

The Policy Engine is the security boundary of Capsule. Every tool call
must pass through the policy engine before execution.

Design Principles:
    - Deny-by-default: Everything is blocked unless explicitly allowed
    - Fail-closed: Any error in policy evaluation results in denial
    - Predictable: Same inputs always produce same decisions
    - Auditable: All decisions include clear reasons

How it works:
    1. Engine receives (tool_name, args, policy)
    2. Looks up tool-specific rules in policy
    3. Evaluates each rule in order
    4. Returns PolicyDecision (allow/deny with reason)

Security Note:
    This module is security-critical. Changes should be reviewed carefully.
    All paths are normalized and resolved before matching to prevent
    path traversal attacks.
"""

import os
import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from capsule.schema import (
    FsPolicy,
    HttpPolicy,
    Policy,
    PolicyDecision,
    ShellPolicy,
)


class PolicyEngine:
    """
    Central policy evaluator for Capsule.

    The PolicyEngine evaluates tool calls against the configured policy
    and returns allow/deny decisions with reasons.

    Usage:
        engine = PolicyEngine(policy)
        decision = engine.evaluate("fs.read", {"path": "./file.txt"})
        if decision.allowed:
            # proceed with tool execution
        else:
            # handle denial

    Attributes:
        policy: The Policy configuration to enforce
        _tool_call_counts: Tracks calls per tool for quota enforcement
    """

    def __init__(self, policy: Policy) -> None:
        """
        Initialize the policy engine.

        Args:
            policy: The policy configuration to enforce
        """
        self.policy = policy
        self._tool_call_counts: dict[str, int] = {}

    def evaluate(
        self,
        tool_name: str,
        args: dict[str, Any],
        working_dir: str = ".",
    ) -> PolicyDecision:
        """
        Evaluate a tool call against the policy.

        This is the main entry point for policy evaluation. It dispatches
        to tool-specific evaluators based on the tool name.

        Args:
            tool_name: The tool being called (e.g., "fs.read")
            args: The arguments to the tool
            working_dir: Working directory for resolving relative paths

        Returns:
            PolicyDecision indicating allow/deny with reason
        """
        # Check quota first
        quota_decision = self._check_quota(tool_name)
        if not quota_decision.allowed:
            return quota_decision

        # Dispatch to tool-specific evaluator
        if tool_name == "fs.read":
            decision = self._evaluate_fs_read(args, working_dir)
        elif tool_name == "fs.write":
            decision = self._evaluate_fs_write(args, working_dir)
        elif tool_name == "http.get":
            decision = self._evaluate_http_get(args)
        elif tool_name == "shell.run":
            decision = self._evaluate_shell_run(args)
        else:
            # Unknown tool - deny by default
            decision = PolicyDecision.deny(
                f"Unknown tool: {tool_name}",
                rule="deny_by_default",
            )

        # If allowed, increment call count
        if decision.allowed:
            self._tool_call_counts[tool_name] = (
                self._tool_call_counts.get(tool_name, 0) + 1
            )

        return decision

    def reset_counts(self) -> None:
        """Reset tool call counts (for new runs)."""
        self._tool_call_counts.clear()

    def _check_quota(self, tool_name: str) -> PolicyDecision:
        """Check if tool call quota is exceeded."""
        current = self._tool_call_counts.get(tool_name, 0)
        max_calls = self.policy.max_calls_per_tool

        if current >= max_calls:
            return PolicyDecision.deny(
                f"Quota exceeded: {tool_name} called {current} times (max: {max_calls})",
                rule="max_calls_per_tool",
            )

        return PolicyDecision.allow("Quota not exceeded")

    # =========================================================================
    # Filesystem Policy Evaluation
    # =========================================================================

    def _evaluate_fs_read(
        self,
        args: dict[str, Any],
        working_dir: str,
    ) -> PolicyDecision:
        """Evaluate fs.read against policy."""
        fs_policy = self.policy.tools.fs_read
        return self._evaluate_fs_access(args, working_dir, fs_policy, "read")

    def _evaluate_fs_write(
        self,
        args: dict[str, Any],
        working_dir: str,
    ) -> PolicyDecision:
        """Evaluate fs.write against policy."""
        fs_policy = self.policy.tools.fs_write
        return self._evaluate_fs_access(args, working_dir, fs_policy, "write")

    def _evaluate_fs_access(
        self,
        args: dict[str, Any],
        working_dir: str,
        fs_policy: FsPolicy,
        operation: str,
    ) -> PolicyDecision:
        """
        Common evaluation logic for filesystem operations.

        Security checks performed:
        1. Path must be provided
        2. Path is normalized and resolved (prevents traversal)
        3. Hidden files blocked unless allow_hidden=True
        4. Path must match at least one allow_paths pattern
        5. Path must not match any deny_paths pattern
        6. Content size checked against max_size_bytes (for write)
        """
        # Check path argument
        path_str = args.get("path")
        if not path_str:
            return PolicyDecision.deny(
                "No path provided",
                rule="missing_argument",
            )

        # Resolve the path (this normalizes and resolves symlinks)
        try:
            path = Path(path_str)
            if not path.is_absolute():
                path = Path(working_dir) / path

            # Resolve to absolute path (handles .., symlinks, etc.)
            # Use resolve(strict=False) to allow paths that don't exist yet (for write)
            resolved_path = path.resolve()
            resolved_str = str(resolved_path)
        except (ValueError, OSError) as e:
            return PolicyDecision.deny(
                f"Invalid path: {e}",
                rule="invalid_path",
            )

        # Check for hidden files (dotfiles)
        if not fs_policy.allow_hidden:
            if self._is_hidden_path(resolved_path):
                return PolicyDecision.deny(
                    f"Hidden files not allowed: {path_str}",
                    rule="allow_hidden=false",
                )

        # Check deny_paths first (deny takes precedence)
        for pattern in fs_policy.deny_paths:
            if self._path_matches_pattern(resolved_str, pattern, working_dir):
                return PolicyDecision.deny(
                    f"Path matches deny pattern: {pattern}",
                    rule=f"deny_paths[{pattern}]",
                )

        # Check allow_paths
        if not fs_policy.allow_paths:
            return PolicyDecision.deny(
                f"No paths allowed for fs.{operation}",
                rule="allow_paths=[]",
            )

        allowed = False
        matched_pattern = None
        symlink_escape_reason = None
        for pattern in fs_policy.allow_paths:
            if self._path_matches_pattern(resolved_str, pattern, working_dir):
                # Additional symlink containment check
                pattern_base = self._extract_pattern_base(pattern, working_dir)
                contained, reason = self._check_symlink_containment(
                    original_path=path,
                    resolved_path=resolved_path,
                    pattern_base=pattern_base,
                )
                if contained:
                    allowed = True
                    matched_pattern = pattern
                    break
                else:
                    # Pattern matched but symlink escapes - try other patterns
                    # (the symlink might legitimately point to another allowed area)
                    symlink_escape_reason = reason

        if not allowed:
            if symlink_escape_reason:
                return PolicyDecision.deny(
                    symlink_escape_reason,
                    rule="symlink_escape",
                )
            return PolicyDecision.deny(
                f"Path not in allowlist: {path_str}",
                rule="allow_paths",
            )

        # For write operations, check content size
        if operation == "write":
            content = args.get("content", "")
            if isinstance(content, str):
                content_size = len(content.encode("utf-8"))
            else:
                content_size = len(content)

            if fs_policy.max_size_bytes > 0 and content_size > fs_policy.max_size_bytes:
                return PolicyDecision.deny(
                    f"Content size {content_size} exceeds limit {fs_policy.max_size_bytes}",
                    rule="max_size_bytes",
                )

        return PolicyDecision.allow(
            f"Path allowed by pattern: {matched_pattern}",
            rule=f"allow_paths[{matched_pattern}]",
        )

    def _is_hidden_path(self, path: Path) -> bool:
        """
        Check if any component of the path is hidden (starts with dot).

        Examples:
            /home/user/.ssh/id_rsa -> True (contains .ssh)
            /home/user/project/.env -> True (contains .env)
            /home/user/project/file.txt -> False
        """
        for part in path.parts:
            if part.startswith(".") and part not in (".", ".."):
                return True
        return False

    def _extract_pattern_base(self, pattern: str, working_dir: str) -> Path:
        """
        Extract the non-glob base path from a pattern.

        Examples:
            "/home/user/**" -> Path("/home/user")
            "/tmp/*.txt" -> Path("/tmp")
            "./**" -> Path(working_dir)

        Args:
            pattern: The glob pattern
            working_dir: Working directory for relative patterns

        Returns:
            The base path without glob components
        """
        if "**" in pattern:
            base_str, _ = pattern.split("**", 1)
        elif "*" in pattern:
            base_str = str(Path(pattern).parent)
        else:
            base_str = pattern

        base_path = Path(base_str) if base_str else Path(".")
        if not base_path.is_absolute():
            base_path = Path(working_dir) / base_path

        return base_path

    def _check_symlink_containment(
        self,
        original_path: Path,
        resolved_path: Path,
        pattern_base: Path,
    ) -> tuple[bool, str]:
        """
        Verify that symlink resolution doesn't escape the pattern boundary.

        This prevents symlink escape attacks where a symlink inside an allowed
        directory points to a location outside the intended scope.

        Security checks:
        1. The pattern base itself should not be a symlink (prevents pattern base attacks)
        2. The resolved path must be under the resolved pattern base

        This allows system symlinks (like /var -> /private/var on macOS) in
        ancestor directories while blocking explicit symlink attacks.

        Args:
            original_path: Path as provided (may contain symlinks)
            resolved_path: Path after resolve() (symlinks followed)
            pattern_base: The non-glob prefix of the allow pattern

        Returns:
            Tuple of (contained: bool, reason: str)
        """
        # Security check 1: Pattern base itself should not be a symlink
        # This catches attacks where the pattern base is a symlink to a sensitive area
        # e.g., /allowed/data -> /etc, pattern is /allowed/data/**
        try:
            if pattern_base.is_symlink():
                return (
                    False,
                    f"Pattern base is a symlink: {pattern_base} -> {pattern_base.resolve()}",
                )
        except OSError:
            # If we can't check, allow (fail-open for this specific check)
            pass

        # Security check 2: Resolved path must be under resolved pattern base
        # We resolve the base to handle system symlinks like /var -> /private/var
        try:
            resolved_base = pattern_base.resolve()
        except OSError as e:
            return (False, f"Cannot resolve pattern base: {e}")

        try:
            resolved_path.relative_to(resolved_base)
            return (True, "Path is within boundary")
        except ValueError:
            pass

        # Resolved path is NOT under the resolved base
        # This means a symlink in the path escaped the boundary
        return (
            False,
            f"Symlink escape detected: {original_path} resolves to {resolved_path} "
            f"which is outside {resolved_base}",
        )

    def _path_matches_pattern(
        self,
        resolved_path: str,
        pattern: str,
        working_dir: str,
    ) -> bool:
        """
        Check if a resolved path matches a glob pattern.

        Patterns can be:
        - Absolute: /home/user/projects/**
        - Relative: ./** (resolved relative to working_dir)
        - Glob patterns: *.txt, **/*.py, etc.

        Args:
            resolved_path: The fully resolved absolute path
            pattern: The glob pattern to match against
            working_dir: Working directory for resolving relative patterns

        Returns:
            True if the path matches the pattern
        """
        # Handle glob patterns by extracting the base path
        # We need to resolve symlinks in the pattern's base path
        # to match the resolved path (which has symlinks resolved)

        if "**" in pattern:
            # Split pattern into base and glob parts
            base_pattern, glob_suffix = pattern.split("**", 1)
        elif "*" in pattern:
            # For single * patterns, get the directory part
            base_pattern = str(Path(pattern).parent)
            glob_suffix = "/" + Path(pattern).name
        else:
            base_pattern = pattern
            glob_suffix = ""

        # Resolve the base pattern path (handles symlinks like /var -> /private/var)
        base_path = Path(base_pattern) if base_pattern else Path(".")
        if not base_path.is_absolute():
            base_path = Path(working_dir) / base_path

        try:
            # Resolve symlinks in the base path
            resolved_base = str(base_path.resolve()).rstrip("/")
        except OSError:
            # If resolution fails, use the original
            resolved_base = str(base_path).rstrip("/")

        # Reconstruct the pattern with resolved base
        pattern_str = resolved_base + "**" + glob_suffix if "**" in pattern else resolved_base + glob_suffix

        # Handle ** for recursive matching
        if "**" in pattern_str:
            # Split on ** and check each segment
            parts = pattern_str.split("**")
            if len(parts) == 2:
                prefix, suffix = parts
                # Remove trailing/leading slashes
                prefix = prefix.rstrip("/")
                suffix = suffix.lstrip("/")

                # Path must start with prefix
                if not resolved_path.startswith(prefix):
                    return False

                # If there's a suffix pattern, the remainder must match it
                if suffix:
                    remainder = resolved_path[len(prefix):].lstrip("/")
                    # For patterns like **/*.txt, match the filename
                    if "/" in suffix:
                        return fnmatch(remainder, suffix.lstrip("/"))
                    else:
                        # Match just the filename
                        filename = Path(resolved_path).name
                        return fnmatch(filename, suffix)

                return True

        # Simple glob matching
        return fnmatch(resolved_path, pattern_str)

    # =========================================================================
    # HTTP Policy Evaluation
    # =========================================================================

    def _evaluate_http_get(self, args: dict[str, Any]) -> PolicyDecision:
        """
        Evaluate http.get against policy.

        Security checks:
        1. URL must be provided and valid
        2. Domain must be in allow_domains
        3. Private IPs blocked if deny_private_ips=True
        """
        http_policy = self.policy.tools.http_get

        # Check URL argument
        url_str = args.get("url")
        if not url_str:
            return PolicyDecision.deny(
                "No URL provided",
                rule="missing_argument",
            )

        # Parse URL
        try:
            parsed = urlparse(url_str)
            if not parsed.scheme or not parsed.netloc:
                return PolicyDecision.deny(
                    f"Invalid URL: {url_str}",
                    rule="invalid_url",
                )
        except Exception as e:
            return PolicyDecision.deny(
                f"Failed to parse URL: {e}",
                rule="invalid_url",
            )

        # Extract domain (hostname without port)
        domain = parsed.hostname or ""

        # Check if domain is allowed
        if not http_policy.allow_domains:
            return PolicyDecision.deny(
                "No domains allowed for http.get",
                rule="allow_domains=[]",
            )

        domain_allowed = False
        matched_domain = None
        for allowed_domain in http_policy.allow_domains:
            if self._domain_matches(domain, allowed_domain):
                domain_allowed = True
                matched_domain = allowed_domain
                break

        if not domain_allowed:
            return PolicyDecision.deny(
                f"Domain not in allowlist: {domain}",
                rule="allow_domains",
            )

        # Check for private IPs (if enabled)
        if http_policy.deny_private_ips:
            if self._is_private_ip_or_localhost(domain):
                return PolicyDecision.deny(
                    f"Private IP/localhost blocked: {domain}",
                    rule="deny_private_ips=true",
                )

        return PolicyDecision.allow(
            f"Domain allowed: {matched_domain}",
            rule=f"allow_domains[{matched_domain}]",
        )

    def _domain_matches(self, domain: str, pattern: str) -> bool:
        """
        Check if a domain matches a pattern.

        Supports exact match and wildcard subdomains.
        Examples:
            api.github.com matches api.github.com
            api.github.com matches *.github.com
            sub.api.github.com matches *.github.com
        """
        domain = domain.lower()
        pattern = pattern.lower()

        if pattern.startswith("*."):
            # Wildcard subdomain match
            suffix = pattern[1:]  # .github.com
            return domain.endswith(suffix) or domain == pattern[2:]
        else:
            # Exact match
            return domain == pattern

    def _is_private_ip_or_localhost(self, host: str) -> bool:
        """
        Check if a host is a private IP or localhost.

        Blocks:
        - localhost, 127.0.0.0/8
        - 10.0.0.0/8
        - 172.16.0.0/12
        - 192.168.0.0/16
        - ::1 (IPv6 localhost)
        - Various localhost aliases
        """
        host = host.lower()

        # Check localhost aliases
        if host in ("localhost", "localhost.localdomain", "127.0.0.1", "::1"):
            return True

        # Check if it's an IP address
        try:
            import ipaddress

            ip = ipaddress.ip_address(host)
            return ip.is_private or ip.is_loopback or ip.is_reserved
        except ValueError:
            # Not an IP address, assume it's a hostname
            # Could be a hostname that resolves to private IP
            # (DNS rebinding prevention would need actual resolution)
            pass

        return False

    # =========================================================================
    # Shell Policy Evaluation
    # =========================================================================

    def _evaluate_shell_run(self, args: dict[str, Any]) -> PolicyDecision:
        """
        Evaluate shell.run against policy.

        Security checks:
        1. cmd must be a list (not a string - prevents shell injection)
        2. Executable must be in allow_executables
        3. Arguments must not contain deny_tokens
        """
        shell_policy = self.policy.tools.shell_run

        # Check cmd argument
        cmd = args.get("cmd")
        if cmd is None:
            return PolicyDecision.deny(
                "No cmd provided",
                rule="missing_argument",
            )

        if not isinstance(cmd, list):
            return PolicyDecision.deny(
                "cmd must be a list, not a string (shell=True is not allowed)",
                rule="cmd_must_be_list",
            )

        if len(cmd) == 0:
            return PolicyDecision.deny(
                "cmd list is empty",
                rule="cmd_empty",
            )

        # Extract executable (first element)
        executable = cmd[0]

        # Get just the executable name (not full path)
        executable_name = Path(executable).name

        # Check if executable is allowed
        if not shell_policy.allow_executables:
            return PolicyDecision.deny(
                "No executables allowed for shell.run",
                rule="allow_executables=[]",
            )

        if executable_name not in shell_policy.allow_executables:
            return PolicyDecision.deny(
                f"Executable not in allowlist: {executable_name}",
                rule="allow_executables",
            )

        # Check for denied tokens in arguments
        # Use word boundary matching to avoid false positives like "su" in "capsule"
        # A token matches if it's not embedded within alphanumeric characters
        full_cmd_str = " ".join(str(arg) for arg in cmd)
        for token in shell_policy.deny_tokens:
            # Escape regex special characters and use negative lookbehind/lookahead
            # to ensure token is not part of a larger alphanumeric word
            pattern = r"(?<![a-zA-Z0-9])" + re.escape(token) + r"(?![a-zA-Z0-9])"
            if re.search(pattern, full_cmd_str, re.IGNORECASE):
                return PolicyDecision.deny(
                    f"Blocked token found: {token}",
                    rule=f"deny_tokens[{token}]",
                )

        return PolicyDecision.allow(
            f"Executable allowed: {executable_name}",
            rule=f"allow_executables[{executable_name}]",
        )
