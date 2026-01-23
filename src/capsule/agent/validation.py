"""
Output validation for agent results.

This module provides utilities to validate that an agent's output
only references resources that were actually accessed during execution,
helping detect hallucinated results from SLMs.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from capsule.agent.loop import ExecutionContext


@dataclass
class ValidationResult:
    """
    Result of validating agent output against execution context.

    Attributes:
        is_valid: True if all referenced files were actually accessed
        hallucinated_paths: Paths mentioned in output but never accessed
        accessed_paths: Paths that were actually accessed
        warnings: Non-fatal issues found during validation
    """

    is_valid: bool = True
    hallucinated_paths: list[str] = field(default_factory=list)
    accessed_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def extract_file_paths(output: Any) -> set[str]:
    """
    Extract file paths mentioned in an output.

    Handles various output formats:
    - JSON with 'file', 'file_path', 'path' keys
    - Plain text with path-like strings
    - Nested structures

    Args:
        output: The output to extract paths from (dict, list, str, etc.)

    Returns:
        Set of file paths found in the output
    """
    paths: set[str] = set()

    if output is None:
        return paths

    if isinstance(output, str):
        # Try to parse as JSON first
        try:
            parsed = json.loads(output)
            return extract_file_paths(parsed)
        except (json.JSONDecodeError, TypeError):
            pass

        # Extract path-like strings from text
        # Match common path patterns
        path_patterns = [
            r'["\']([./][^"\'<>|*?\n]+)["\']',  # Quoted paths starting with . or /
            r'(?:file|path)["\']?\s*[:=]\s*["\']([^"\'<>|*?\n]+)["\']',  # file: "..." or path = "..."
        ]

        for pattern in path_patterns:
            matches = re.findall(pattern, output, re.IGNORECASE)
            for match in matches:
                if _looks_like_path(match):
                    paths.add(match)

        return paths

    if isinstance(output, dict):
        # Check common path keys
        path_keys = ['file', 'file_path', 'path', 'filepath', 'filename']
        for key in path_keys:
            if key in output:
                value = output[key]
                if isinstance(value, str) and _looks_like_path(value):
                    paths.add(value)

        # Check for 'findings' array (common in audit outputs)
        if 'findings' in output and isinstance(output['findings'], list):
            for finding in output['findings']:
                if isinstance(finding, dict):
                    paths.update(extract_file_paths(finding))

        # Check for 'top_files_with_findings' array
        if 'top_files_with_findings' in output and isinstance(output['top_files_with_findings'], list):
            for item in output['top_files_with_findings']:
                if isinstance(item, dict):
                    paths.update(extract_file_paths(item))

        # Recursively check all values
        for value in output.values():
            if isinstance(value, (dict, list)):
                paths.update(extract_file_paths(value))

        return paths

    if isinstance(output, list):
        for item in output:
            paths.update(extract_file_paths(item))
        return paths

    return paths


def _looks_like_path(s: str) -> bool:
    """Check if a string looks like a file path."""
    if not s or len(s) < 2:
        return False

    # Must start with /, ./, ../, or be a relative path with extension
    if s.startswith(('/','./','../')):
        return True

    # Check for path-like structure (has / and reasonable extension)
    if '/' in s and not s.startswith('http'):
        # Has a file extension or is a directory path
        if '.' in s.split('/')[-1] or s.endswith('/'):
            return True

    return False


def validate_output(
    output: Any,
    execution_context: ExecutionContext,
    strict: bool = False,
) -> ValidationResult:
    """
    Validate that output only references files that were actually accessed.

    Args:
        output: The agent's final output to validate
        execution_context: The context tracking what was actually accessed
        strict: If True, any hallucinated path makes result invalid

    Returns:
        ValidationResult with details about validation
    """
    result = ValidationResult()
    result.accessed_paths = list(execution_context.files_read)

    # Extract paths mentioned in output
    mentioned_paths = extract_file_paths(output)

    # Check each mentioned path against accessed files
    for path in mentioned_paths:
        if not execution_context.was_file_accessed(path):
            result.hallucinated_paths.append(path)

    # Determine validity
    if result.hallucinated_paths:
        if strict:
            result.is_valid = False
        else:
            # In non-strict mode, warn but don't fail
            result.warnings.append(
                f"Output references {len(result.hallucinated_paths)} file(s) that were not accessed"
            )

    # Additional checks
    if not result.accessed_paths and mentioned_paths:
        result.warnings.append(
            "Output mentions files but no files were read during execution"
        )
        if strict:
            result.is_valid = False

    return result


def format_validation_result(result: ValidationResult) -> str:
    """Format validation result for display."""
    lines = []

    if result.is_valid:
        lines.append("✓ Output validation passed")
    else:
        lines.append("✗ Output validation failed")

    if result.hallucinated_paths:
        lines.append(f"\nHallucinated paths ({len(result.hallucinated_paths)}):")
        for path in result.hallucinated_paths[:5]:  # Show first 5
            lines.append(f"  - {path}")
        if len(result.hallucinated_paths) > 5:
            lines.append(f"  ... and {len(result.hallucinated_paths) - 5} more")

    if result.accessed_paths:
        lines.append(f"\nActually accessed ({len(result.accessed_paths)}):")
        for path in result.accessed_paths[:5]:
            lines.append(f"  - {path}")
        if len(result.accessed_paths) > 5:
            lines.append(f"  ... and {len(result.accessed_paths) - 5} more")

    if result.warnings:
        lines.append("\nWarnings:")
        for warning in result.warnings:
            lines.append(f"  ⚠ {warning}")

    return "\n".join(lines)
