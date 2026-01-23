"""Tests for agent output validation."""

import pytest

from capsule.agent.loop import ExecutionContext
from capsule.agent.validation import (
    ValidationResult,
    extract_file_paths,
    validate_output,
    format_validation_result,
)


class TestExecutionContext:
    """Tests for ExecutionContext class."""

    def test_record_fs_read(self):
        """Test recording fs.read tool calls."""
        ctx = ExecutionContext()
        ctx.record_tool_call("fs.read", {"path": "/tmp/test.txt"})

        assert "/tmp/test.txt" in ctx.files_read
        assert len(ctx.tool_calls) == 1

    def test_record_shell_run(self):
        """Test recording shell.run tool calls."""
        ctx = ExecutionContext()
        ctx.record_tool_call("shell.run", {"command": "ls -la"})

        assert "ls -la" in ctx.commands_run
        assert len(ctx.tool_calls) == 1

    def test_record_multiple_calls(self):
        """Test recording multiple tool calls."""
        ctx = ExecutionContext()
        ctx.record_tool_call("shell.run", {"command": "find . -name '*.py'"})
        ctx.record_tool_call("fs.read", {"path": "src/main.py"})
        ctx.record_tool_call("fs.read", {"path": "src/utils.py"})

        assert len(ctx.files_read) == 2
        assert len(ctx.commands_run) == 1
        assert len(ctx.tool_calls) == 3

    def test_was_file_accessed_exact_match(self):
        """Test checking file access with exact match."""
        ctx = ExecutionContext()
        ctx.record_tool_call("fs.read", {"path": "/project/src/main.py"})

        assert ctx.was_file_accessed("/project/src/main.py")
        assert not ctx.was_file_accessed("/project/src/other.py")

    def test_was_file_accessed_partial_match(self):
        """Test checking file access with partial path match."""
        ctx = ExecutionContext()
        ctx.record_tool_call("fs.read", {"path": "/project/src/main.py"})

        # Should find partial matches
        assert ctx.was_file_accessed("main.py")

    def test_get_accessed_files(self):
        """Test getting sorted list of accessed files."""
        ctx = ExecutionContext()
        ctx.record_tool_call("fs.read", {"path": "z.txt"})
        ctx.record_tool_call("fs.read", {"path": "a.txt"})
        ctx.record_tool_call("fs.read", {"path": "m.txt"})

        files = ctx.get_accessed_files()
        assert files == ["a.txt", "m.txt", "z.txt"]


class TestExtractFilePaths:
    """Tests for extract_file_paths function."""

    def test_extract_from_dict_with_file_key(self):
        """Test extracting paths from dict with 'file' key."""
        output = {"file": "/tmp/test.txt", "line": 42}
        paths = extract_file_paths(output)

        assert "/tmp/test.txt" in paths

    def test_extract_from_dict_with_path_key(self):
        """Test extracting paths from dict with 'path' key."""
        output = {"path": "./src/main.py"}
        paths = extract_file_paths(output)

        assert "./src/main.py" in paths

    def test_extract_from_findings_array(self):
        """Test extracting paths from findings array."""
        output = {
            "findings": [
                {"file": "/tmp/secret1.txt", "line": 10},
                {"file": "/tmp/secret2.txt", "line": 20},
            ]
        }
        paths = extract_file_paths(output)

        assert "/tmp/secret1.txt" in paths
        assert "/tmp/secret2.txt" in paths

    def test_extract_from_top_files_with_findings(self):
        """Test extracting paths from top_files_with_findings."""
        output = {
            "top_files_with_findings": [
                {"file_path": "docs/secrets/confidential.yaml"},
                {"file_path": "config/credentials.json"},
            ]
        }
        paths = extract_file_paths(output)

        assert "docs/secrets/confidential.yaml" in paths
        assert "config/credentials.json" in paths

    def test_extract_from_json_string(self):
        """Test extracting paths from JSON string."""
        output = '{"file": "/tmp/test.txt", "line": 42}'
        paths = extract_file_paths(output)

        assert "/tmp/test.txt" in paths

    def test_extract_from_nested_structure(self):
        """Test extracting paths from deeply nested structure."""
        output = {
            "results": {
                "scans": [
                    {"findings": [{"file": "/deep/nested/path.py"}]}
                ]
            }
        }
        paths = extract_file_paths(output)

        assert "/deep/nested/path.py" in paths

    def test_empty_output(self):
        """Test with empty/None output."""
        assert extract_file_paths(None) == set()
        assert extract_file_paths("") == set()
        assert extract_file_paths({}) == set()


class TestValidateOutput:
    """Tests for validate_output function."""

    def test_valid_output_all_files_accessed(self):
        """Test validation passes when all mentioned files were accessed."""
        ctx = ExecutionContext()
        ctx.record_tool_call("fs.read", {"path": "/tmp/file1.txt"})
        ctx.record_tool_call("fs.read", {"path": "/tmp/file2.txt"})

        output = {
            "findings": [
                {"file": "/tmp/file1.txt", "type": "secret"},
            ]
        }

        result = validate_output(output, ctx)

        assert result.is_valid
        assert len(result.hallucinated_paths) == 0

    def test_invalid_output_hallucinated_file(self):
        """Test validation catches hallucinated files."""
        ctx = ExecutionContext()
        ctx.record_tool_call("fs.read", {"path": "/tmp/real.txt"})

        output = {
            "findings": [
                {"file": "/tmp/fake.txt", "type": "secret"},  # Never accessed!
            ]
        }

        result = validate_output(output, ctx, strict=True)

        assert not result.is_valid
        assert "/tmp/fake.txt" in result.hallucinated_paths

    def test_non_strict_mode_warns_but_passes(self):
        """Test non-strict mode warns but doesn't fail."""
        ctx = ExecutionContext()
        ctx.record_tool_call("fs.read", {"path": "/tmp/real.txt"})

        output = {
            "findings": [
                {"file": "/tmp/fake.txt", "type": "secret"},
            ]
        }

        result = validate_output(output, ctx, strict=False)

        assert result.is_valid  # Still valid in non-strict
        assert "/tmp/fake.txt" in result.hallucinated_paths
        assert len(result.warnings) > 0

    def test_no_files_accessed_but_output_mentions_files(self):
        """Test warning when output mentions files but none were accessed."""
        ctx = ExecutionContext()
        # No files read

        output = {
            "findings": [
                {"file": "/tmp/fake.txt", "type": "secret"},
            ]
        }

        result = validate_output(output, ctx, strict=True)

        assert not result.is_valid
        assert "/tmp/fake.txt" in result.hallucinated_paths

    def test_empty_output_is_valid(self):
        """Test that empty output is valid."""
        ctx = ExecutionContext()
        ctx.record_tool_call("fs.read", {"path": "/tmp/file.txt"})

        result = validate_output({"findings": []}, ctx)

        assert result.is_valid


class TestFormatValidationResult:
    """Tests for format_validation_result function."""

    def test_format_valid_result(self):
        """Test formatting a valid result."""
        result = ValidationResult(
            is_valid=True,
            accessed_paths=["/tmp/file.txt"],
        )
        formatted = format_validation_result(result)

        assert "passed" in formatted.lower()

    def test_format_invalid_result_with_hallucinations(self):
        """Test formatting an invalid result with hallucinations."""
        result = ValidationResult(
            is_valid=False,
            hallucinated_paths=["/fake/path1.txt", "/fake/path2.txt"],
            accessed_paths=["/real/file.txt"],
        )
        formatted = format_validation_result(result)

        assert "failed" in formatted.lower()
        assert "/fake/path1.txt" in formatted
        assert "/real/file.txt" in formatted

    def test_format_result_with_warnings(self):
        """Test formatting a result with warnings."""
        result = ValidationResult(
            is_valid=True,
            warnings=["Output references files that were not accessed"],
        )
        formatted = format_validation_result(result)

        assert "warning" in formatted.lower()
