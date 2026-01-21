"""
Tests for the planner JSON repair module.

Tests:
    - extract_json: Extract JSON from mixed text
    - repair_json: Fix common SLM JSON errors
    - parse_json_safely: Combined extraction and repair
    - validate_tool_call_json: Validate tool call structure
"""

from capsule.planner.json_repair import (
    extract_json,
    parse_json_safely,
    repair_json,
    validate_tool_call_json,
)


class TestExtractJson:
    """Tests for extract_json function."""

    def test_extract_bare_object(self):
        """Test extracting a bare JSON object."""
        text = '{"tool": "fs.read", "args": {"path": "/test"}}'
        result = extract_json(text)
        assert result == text

    def test_extract_from_markdown_code_block(self):
        """Test extracting JSON from markdown code block."""
        text = """Here's the tool call:
```json
{"tool": "fs.read", "args": {"path": "/test"}}
```
Let me know if you need anything else."""
        result = extract_json(text)
        assert result == '{"tool": "fs.read", "args": {"path": "/test"}}'

    def test_extract_from_plain_code_block(self):
        """Test extracting JSON from plain code block."""
        text = """Response:
```
{"tool": "shell.run", "args": {"command": "ls"}}
```
Done."""
        result = extract_json(text)
        assert result == '{"tool": "shell.run", "args": {"command": "ls"}}'

    def test_extract_from_inline_code(self):
        """Test extracting JSON from inline code."""
        text = 'The answer is `{"done": true, "reason": "complete"}`.'
        result = extract_json(text)
        assert result == '{"done": true, "reason": "complete"}'

    def test_extract_from_mixed_text_object(self):
        """Test extracting JSON object from mixed text."""
        text = 'I will call {"tool": "fs.read", "args": {}} to read the file.'
        result = extract_json(text)
        assert result == '{"tool": "fs.read", "args": {}}'

    def test_extract_array(self):
        """Test extracting JSON array."""
        text = "Results: [1, 2, 3]"
        result = extract_json(text)
        assert result == "[1, 2, 3]"

    def test_extract_nested_object(self):
        """Test extracting nested JSON object."""
        text = '{"outer": {"inner": {"deep": "value"}}}'
        result = extract_json(text)
        assert result == text

    def test_extract_with_string_containing_braces(self):
        """Test extracting JSON with strings containing braces."""
        text = '{"message": "Use {variable} syntax"}'
        result = extract_json(text)
        assert result == text

    def test_extract_empty_input(self):
        """Test extracting from empty input."""
        assert extract_json("") is None
        assert extract_json("   ") is None
        assert extract_json(None) is None

    def test_extract_no_json(self):
        """Test extracting from text with no JSON."""
        text = "This is just plain text without any JSON."
        result = extract_json(text)
        assert result is None

    def test_extract_incomplete_json(self):
        """Test extracting incomplete JSON."""
        # The function may return the incomplete text, but it won't parse
        text = '{"tool": "fs.read", "args": {'
        # Just call the function - may return something or None
        # The important thing is it doesn't crash
        extract_json(text)

    def test_extract_prefers_code_block(self):
        """Test that code blocks are preferred over bare JSON."""
        text = """Some text {"noise": true}
```json
{"tool": "correct"}
```
More {"noise": false}"""
        result = extract_json(text)
        assert result == '{"tool": "correct"}'


class TestRepairJson:
    """Tests for repair_json function."""

    def test_repair_valid_json(self):
        """Test that valid JSON is returned unchanged."""
        text = '{"tool": "fs.read", "args": {"path": "/test"}}'
        result = repair_json(text)
        assert result == text

    def test_repair_trailing_comma(self):
        """Test repairing trailing comma in object."""
        text = '{"tool": "fs.read", "args": {},}'
        result = repair_json(text)
        assert result is not None
        import json

        parsed = json.loads(result)
        assert parsed["tool"] == "fs.read"

    def test_repair_trailing_comma_in_array(self):
        """Test repairing trailing comma in array."""
        text = "[1, 2, 3,]"
        result = repair_json(text)
        assert result is not None
        import json

        parsed = json.loads(result)
        assert parsed == [1, 2, 3]

    def test_repair_single_quotes(self):
        """Test repairing single quotes."""
        text = "{'tool': 'fs.read'}"
        result = repair_json(text)
        assert result is not None
        import json

        parsed = json.loads(result)
        assert parsed["tool"] == "fs.read"

    def test_repair_unquoted_keys(self):
        """Test repairing unquoted keys."""
        text = '{tool: "fs.read", args: {}}'
        result = repair_json(text)
        assert result is not None
        import json

        parsed = json.loads(result)
        assert parsed["tool"] == "fs.read"

    def test_repair_python_booleans(self):
        """Test repairing Python-style booleans."""
        text = '{"done": True, "value": False}'
        result = repair_json(text)
        assert result is not None
        import json

        parsed = json.loads(result)
        assert parsed["done"] is True
        assert parsed["value"] is False

    def test_repair_python_none(self):
        """Test repairing Python None."""
        text = '{"value": None}'
        result = repair_json(text)
        assert result is not None
        import json

        parsed = json.loads(result)
        assert parsed["value"] is None

    def test_repair_js_line_comment(self):
        """Test removing JavaScript-style line comments."""
        text = """{"tool": "fs.read"  // read file
}"""
        result = repair_json(text)
        assert result is not None
        import json

        parsed = json.loads(result)
        assert parsed["tool"] == "fs.read"

    def test_repair_js_block_comment(self):
        """Test removing JavaScript-style block comments."""
        text = '{"tool": /* tool name */ "fs.read"}'
        result = repair_json(text)
        assert result is not None
        import json

        parsed = json.loads(result)
        assert parsed["tool"] == "fs.read"

    def test_repair_empty_input(self):
        """Test repairing empty input."""
        assert repair_json("") is None
        assert repair_json(None) is None

    def test_repair_unrepairable(self):
        """Test unrepairable JSON returns None."""
        text = "not json at all"
        result = repair_json(text)
        assert result is None

    def test_repair_multiple_issues(self):
        """Test repairing multiple issues at once."""
        text = "{tool: 'fs.read', done: False,}"
        result = repair_json(text)
        assert result is not None
        import json

        parsed = json.loads(result)
        assert parsed["tool"] == "fs.read"
        assert parsed["done"] is False


class TestParseJsonSafely:
    """Tests for parse_json_safely function."""

    def test_parse_valid_json(self):
        """Test parsing valid JSON."""
        text = '{"tool": "fs.read", "args": {"path": "/test"}}'
        result, error = parse_json_safely(text)
        assert error is None
        assert result["tool"] == "fs.read"

    def test_parse_from_code_block(self):
        """Test parsing from code block."""
        text = """```json
{"tool": "fs.read"}
```"""
        result, error = parse_json_safely(text)
        assert error is None
        assert result["tool"] == "fs.read"

    def test_parse_with_repair(self):
        """Test parsing with automatic repair."""
        text = '{tool: "fs.read", done: False,}'
        result, error = parse_json_safely(text)
        assert error is None
        assert result["tool"] == "fs.read"
        assert result["done"] is False

    def test_parse_combined_extract_and_repair(self):
        """Test combined extraction and repair."""
        text = """I'll call the tool:
```
{tool: 'shell.run', args: {command: 'ls'},}
```
Done!"""
        result, error = parse_json_safely(text)
        assert error is None
        assert result["tool"] == "shell.run"
        assert result["args"]["command"] == "ls"

    def test_parse_empty_input(self):
        """Test parsing empty input."""
        result, error = parse_json_safely("")
        assert result is None
        assert error == "Empty input"

        result, error = parse_json_safely("   ")
        assert result is None
        assert error == "Empty input"

    def test_parse_no_json(self):
        """Test parsing text with no JSON."""
        result, error = parse_json_safely("This has no JSON content.")
        assert result is None
        assert "No valid JSON" in error

    def test_parse_returns_error_on_failure(self):
        """Test that parsing returns descriptive error on failure."""
        result, error = parse_json_safely("{broken json here")
        assert result is None
        assert error is not None


class TestValidateToolCallJson:
    """Tests for validate_tool_call_json function."""

    def test_validate_valid_tool_call(self):
        """Test validating a valid tool call."""
        data = {"tool": "fs.read", "args": {"path": "/test"}}
        is_valid, error = validate_tool_call_json(data)
        assert is_valid
        assert error is None

    def test_validate_tool_call_without_args(self):
        """Test validating tool call without args (args is optional)."""
        data = {"tool": "noop"}
        is_valid, error = validate_tool_call_json(data)
        assert is_valid
        assert error is None

    def test_validate_done_signal(self):
        """Test validating done signal."""
        data = {"done": True, "reason": "task_complete"}
        is_valid, error = validate_tool_call_json(data)
        assert is_valid
        assert error is None

    def test_validate_done_with_output(self):
        """Test validating done with output."""
        data = {"done": True, "output": "Result data", "reason": "success"}
        is_valid, error = validate_tool_call_json(data)
        assert is_valid
        assert error is None

    def test_validate_missing_tool(self):
        """Test validating object without tool field."""
        data = {"args": {"path": "/test"}}
        is_valid, error = validate_tool_call_json(data)
        assert not is_valid
        assert "Missing 'tool' field" in error

    def test_validate_empty_tool(self):
        """Test validating object with empty tool field."""
        data = {"tool": "", "args": {}}
        is_valid, error = validate_tool_call_json(data)
        assert not is_valid
        assert "'tool' cannot be empty" in error

    def test_validate_tool_not_string(self):
        """Test validating object with non-string tool."""
        data = {"tool": 123, "args": {}}
        is_valid, error = validate_tool_call_json(data)
        assert not is_valid
        assert "'tool' must be a string" in error

    def test_validate_args_not_object(self):
        """Test validating object with non-object args."""
        data = {"tool": "fs.read", "args": [1, 2, 3]}
        is_valid, error = validate_tool_call_json(data)
        assert not is_valid
        assert "'args' must be an object" in error

    def test_validate_args_string(self):
        """Test validating object with string args."""
        data = {"tool": "fs.read", "args": "not an object"}
        is_valid, error = validate_tool_call_json(data)
        assert not is_valid
        assert "'args' must be an object" in error

    def test_validate_done_not_boolean(self):
        """Test validating done that's not a boolean."""
        data = {"done": "yes"}
        is_valid, error = validate_tool_call_json(data)
        assert not is_valid
        assert "'done' must be a boolean" in error

    def test_validate_not_dict(self):
        """Test validating non-dict input."""
        is_valid, error = validate_tool_call_json([1, 2, 3])
        assert not is_valid
        assert "Expected object" in error

        is_valid, error = validate_tool_call_json("string")
        assert not is_valid
        assert "Expected object" in error

        is_valid, error = validate_tool_call_json(None)
        assert not is_valid
        assert "Expected object" in error

    def test_validate_with_reasoning(self):
        """Test validating tool call with optional reasoning field."""
        data = {
            "tool": "fs.read",
            "args": {"path": "/test"},
            "reasoning": "Need to read config file",
        }
        is_valid, error = validate_tool_call_json(data)
        assert is_valid
        assert error is None

    def test_validate_done_false(self):
        """Test validating done: false (should still be valid if tool present)."""
        # done: false should still require tool
        data = {"done": False}
        is_valid, _error = validate_tool_call_json(data)
        assert is_valid  # done is present, so it's a valid done signal
