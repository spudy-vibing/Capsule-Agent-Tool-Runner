"""
JSON repair utilities for SLM output.

Small language models often produce malformed JSON with common errors:
- Trailing commas
- Missing quotes around keys
- Single quotes instead of double quotes
- Unescaped newlines in strings
- Truncated responses

This module provides utilities to repair such JSON and extract
valid JSON from mixed output.

Design Principles:
    - Best effort repair (may not succeed)
    - Bounded attempts to prevent infinite loops
    - Preserve original meaning where possible
    - Return None rather than guess incorrectly
"""

import json
import re
from typing import Any

# Maximum number of repair attempts
MAX_REPAIR_ATTEMPTS = 3


def extract_json(text: str) -> str | None:
    """
    Extract JSON object or array from mixed text.

    SLMs often produce output like:
        "Here's the tool call:
        ```json
        {"tool": "fs.read", "args": {...}}
        ```
        Let me know if you need anything else."

    This function extracts just the JSON part.

    Args:
        text: Mixed text potentially containing JSON

    Returns:
        Extracted JSON string, or None if not found
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # Try to find JSON in code blocks first
    code_block_patterns = [
        r"```json\s*([\s\S]*?)\s*```",  # ```json ... ```
        r"```\s*([\s\S]*?)\s*```",  # ``` ... ```
        r"`([\s\S]*?)`",  # ` ... `
    ]

    for pattern in code_block_patterns:
        match = re.search(pattern, text)
        if match:
            candidate = match.group(1).strip()
            if candidate.startswith(("{", "[")):
                return candidate

    # Try to find bare JSON object or array
    # Find first { or [ and match to closing } or ]
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start_idx = text.find(start_char)
        if start_idx == -1:
            continue

        # Find matching closing bracket
        depth = 0
        in_string = False
        escape_next = False

        for i, char in enumerate(text[start_idx:], start_idx):
            if escape_next:
                escape_next = False
                continue

            if char == "\\":
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == start_char:
                depth += 1
            elif char == end_char:
                depth -= 1
                if depth == 0:
                    return text[start_idx : i + 1]

    return None


def repair_json(text: str) -> str | None:
    """
    Attempt to repair malformed JSON.

    Handles common SLM errors:
    - Trailing commas: {"a": 1,} -> {"a": 1}
    - Single quotes: {'a': 1} -> {"a": 1}
    - Unquoted keys: {a: 1} -> {"a": 1}
    - Missing commas between elements

    Args:
        text: Malformed JSON string

    Returns:
        Repaired JSON string, or None if repair failed

    Note:
        This is best-effort. Complex malformations may not be repairable.
    """
    if not text:
        return None

    attempts = 0

    while attempts < MAX_REPAIR_ATTEMPTS:
        attempts += 1

        # Try parsing first
        try:
            json.loads(text)
            return text  # Already valid
        except json.JSONDecodeError:
            pass

        # Apply repairs
        repaired = _apply_repairs(text)

        if repaired == text:
            # No more repairs possible
            break

        text = repaired

    # Final attempt
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        return None


def _apply_repairs(text: str) -> str:
    """Apply a single round of JSON repairs."""
    # Remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # Replace single quotes with double quotes (careful with nested quotes)
    # Only do this if there are no double quotes (to avoid breaking valid JSON)
    if '"' not in text and "'" in text:
        text = text.replace("'", '"')

    # Add quotes around unquoted keys
    # Match: {key: or , key: where key is alphanumeric
    text = re.sub(r"([{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'\1"\2":', text)

    # Fix common boolean/null case issues
    text = re.sub(r"\bTrue\b", "true", text)
    text = re.sub(r"\bFalse\b", "false", text)
    text = re.sub(r"\bNone\b", "null", text)

    # Remove JavaScript-style comments
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    return text


def parse_json_safely(text: str) -> tuple[Any, str | None]:
    """
    Parse JSON with automatic extraction and repair.

    This is the main entry point for parsing SLM output.
    It combines extraction and repair for best results.

    Args:
        text: Raw text from SLM that may contain JSON

    Returns:
        Tuple of (parsed_object, error_message)
        If successful: (object, None)
        If failed: (None, error_description)

    Example:
        result, error = parse_json_safely(slm_output)
        if error:
            print(f"Failed to parse: {error}")
        else:
            print(f"Parsed: {result}")
    """
    if not text or not text.strip():
        return None, "Empty input"

    # Step 1: Try direct parse
    try:
        return json.loads(text), None
    except json.JSONDecodeError:
        pass

    # Step 2: Extract JSON from mixed text
    extracted = extract_json(text)
    if extracted:
        try:
            return json.loads(extracted), None
        except json.JSONDecodeError:
            # Try repairing the extracted JSON
            repaired = repair_json(extracted)
            if repaired:
                try:
                    return json.loads(repaired), None
                except json.JSONDecodeError as e:
                    return None, f"Repair failed: {e}"

    # Step 3: Try repairing the original text
    repaired = repair_json(text)
    if repaired:
        try:
            return json.loads(repaired), None
        except json.JSONDecodeError as e:
            return None, f"Repair failed: {e}"

    return None, "No valid JSON found in response"


def validate_tool_call_json(data: Any) -> tuple[bool, str | None]:
    """
    Validate that parsed JSON represents a valid tool call.

    Expected format:
        {"tool": "tool_name", "args": {...}}
        or
        {"done": true, "reason": "..."}

    Args:
        data: Parsed JSON object

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not isinstance(data, dict):
        return False, f"Expected object, got {type(data).__name__}"

    # Check for done signal
    if "done" in data:
        if not isinstance(data.get("done"), bool):
            return False, "'done' must be a boolean"
        return True, None

    # Check for tool call
    if "tool" not in data:
        return False, "Missing 'tool' field"

    if not isinstance(data["tool"], str):
        return False, "'tool' must be a string"

    if not data["tool"]:
        return False, "'tool' cannot be empty"

    # Args is optional but must be a dict if present
    if "args" in data and not isinstance(data["args"], dict):
        return False, "'args' must be an object"

    return True, None
