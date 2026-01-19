"""
Unit tests for filesystem tools (fs.read, fs.write).

Tests cover:
- Reading text files
- Reading binary files
- Handling missing files
- Handling permission errors
- Encoding handling
- Argument validation
- Writing files (basic)
"""

from pathlib import Path

import pytest

from capsule.tools import ToolContext, default_registry, get_tool
from capsule.tools.fs import FsReadTool, FsWriteTool


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def fs_read() -> FsReadTool:
    """Get an fs.read tool instance."""
    return FsReadTool()


@pytest.fixture
def fs_write() -> FsWriteTool:
    """Get an fs.write tool instance."""
    return FsWriteTool()


@pytest.fixture
def context(temp_dir: Path) -> ToolContext:
    """Create a tool context with temp directory as working dir."""
    return ToolContext(
        run_id="test-run",
        working_dir=str(temp_dir),
    )


@pytest.fixture
def sample_file(temp_dir: Path) -> Path:
    """Create a sample text file."""
    path = temp_dir / "sample.txt"
    path.write_text("Hello, World!\nLine 2\n")
    return path


@pytest.fixture
def binary_file(temp_dir: Path) -> Path:
    """Create a sample binary file."""
    path = temp_dir / "sample.bin"
    path.write_bytes(b"\x00\x01\x02\x03\xff\xfe")
    return path


@pytest.fixture
def unicode_file(temp_dir: Path) -> Path:
    """Create a file with unicode content."""
    path = temp_dir / "unicode.txt"
    path.write_text("Hello \u4e16\u754c \U0001f600", encoding="utf-8")
    return path


# =============================================================================
# FsReadTool Registration Tests
# =============================================================================


class TestFsReadRegistration:
    """Test that fs.read is properly registered."""

    def test_registered_in_default_registry(self) -> None:
        """fs.read should be in the default registry."""
        assert "fs.read" in default_registry

    def test_get_tool(self) -> None:
        """Can retrieve fs.read via get_tool."""
        tool = get_tool("fs.read")
        assert tool.name == "fs.read"


# =============================================================================
# FsReadTool Basic Tests
# =============================================================================


class TestFsReadTool:
    """Tests for FsReadTool."""

    def test_name(self, fs_read: FsReadTool) -> None:
        """Tool has correct name."""
        assert fs_read.name == "fs.read"

    def test_description(self, fs_read: FsReadTool) -> None:
        """Tool has a description."""
        assert "read" in fs_read.description.lower()


# =============================================================================
# FsReadTool Argument Validation Tests
# =============================================================================


class TestFsReadValidation:
    """Tests for fs.read argument validation."""

    def test_path_required(self, fs_read: FsReadTool) -> None:
        """path argument is required."""
        errors = fs_read.validate_args({})
        assert any("path" in e and "required" in e for e in errors)

    def test_path_must_be_string(self, fs_read: FsReadTool) -> None:
        """path must be a string."""
        errors = fs_read.validate_args({"path": 123})
        assert any("path" in e and "string" in e for e in errors)

    def test_path_cannot_be_empty(self, fs_read: FsReadTool) -> None:
        """path cannot be empty."""
        errors = fs_read.validate_args({"path": ""})
        assert any("empty" in e for e in errors)

        errors = fs_read.validate_args({"path": "   "})
        assert any("empty" in e for e in errors)

    def test_encoding_must_be_string(self, fs_read: FsReadTool) -> None:
        """encoding must be a string if provided."""
        errors = fs_read.validate_args({"path": "./file", "encoding": 123})
        assert any("encoding" in e and "string" in e for e in errors)

    def test_binary_must_be_bool(self, fs_read: FsReadTool) -> None:
        """binary must be a bool if provided."""
        errors = fs_read.validate_args({"path": "./file", "binary": "true"})
        assert any("binary" in e and "boolean" in e for e in errors)

    def test_valid_args(self, fs_read: FsReadTool) -> None:
        """Valid arguments pass validation."""
        errors = fs_read.validate_args({"path": "./file"})
        assert errors == []

        errors = fs_read.validate_args({
            "path": "./file",
            "encoding": "utf-8",
            "binary": True,
        })
        assert errors == []


# =============================================================================
# FsReadTool Execution Tests
# =============================================================================


class TestFsReadExecution:
    """Tests for fs.read execution."""

    def test_read_text_file(
        self,
        fs_read: FsReadTool,
        context: ToolContext,
        sample_file: Path,
    ) -> None:
        """Read a simple text file."""
        output = fs_read.execute({"path": str(sample_file)}, context)
        assert output.success is True
        assert "Hello, World!" in output.data
        assert "Line 2" in output.data
        assert output.metadata["binary"] is False

    def test_read_relative_path(
        self,
        fs_read: FsReadTool,
        context: ToolContext,
        sample_file: Path,
    ) -> None:
        """Read using relative path."""
        output = fs_read.execute({"path": "sample.txt"}, context)
        assert output.success is True
        assert "Hello, World!" in output.data

    def test_read_binary_file(
        self,
        fs_read: FsReadTool,
        context: ToolContext,
        binary_file: Path,
    ) -> None:
        """Read a binary file."""
        output = fs_read.execute(
            {"path": str(binary_file), "binary": True},
            context,
        )
        assert output.success is True
        assert output.data == b"\x00\x01\x02\x03\xff\xfe"
        assert output.metadata["binary"] is True

    def test_read_unicode_file(
        self,
        fs_read: FsReadTool,
        context: ToolContext,
        unicode_file: Path,
    ) -> None:
        """Read a file with unicode content."""
        output = fs_read.execute({"path": str(unicode_file)}, context)
        assert output.success is True
        assert "\u4e16\u754c" in output.data  # Chinese characters
        assert "\U0001f600" in output.data  # Emoji

    def test_read_with_encoding(
        self,
        fs_read: FsReadTool,
        context: ToolContext,
        temp_dir: Path,
    ) -> None:
        """Read with specific encoding."""
        # Create a file with latin-1 encoding
        path = temp_dir / "latin1.txt"
        path.write_bytes("caf\xe9".encode("latin-1"))

        output = fs_read.execute(
            {"path": str(path), "encoding": "latin-1"},
            context,
        )
        assert output.success is True
        assert output.data == "caf\xe9"

    def test_file_not_found(
        self,
        fs_read: FsReadTool,
        context: ToolContext,
    ) -> None:
        """Handle missing file."""
        output = fs_read.execute({"path": "nonexistent.txt"}, context)
        assert output.success is False
        assert "not found" in output.error.lower()

    def test_read_directory_fails(
        self,
        fs_read: FsReadTool,
        context: ToolContext,
        temp_dir: Path,
    ) -> None:
        """Cannot read a directory."""
        subdir = temp_dir / "subdir"
        subdir.mkdir()

        output = fs_read.execute({"path": str(subdir)}, context)
        assert output.success is False
        assert "not a file" in output.error.lower()

    def test_encoding_error(
        self,
        fs_read: FsReadTool,
        context: ToolContext,
        binary_file: Path,
    ) -> None:
        """Handle encoding errors gracefully."""
        # Try to read binary as text
        output = fs_read.execute({"path": str(binary_file)}, context)
        assert output.success is False
        assert "encoding" in output.error.lower()

    def test_invalid_args_during_execute(
        self,
        fs_read: FsReadTool,
        context: ToolContext,
    ) -> None:
        """Execute with invalid args returns failure."""
        output = fs_read.execute({}, context)
        assert output.success is False
        assert "invalid arguments" in output.error.lower()

    def test_metadata_includes_size(
        self,
        fs_read: FsReadTool,
        context: ToolContext,
        sample_file: Path,
    ) -> None:
        """Output metadata includes file size."""
        output = fs_read.execute({"path": str(sample_file)}, context)
        assert output.success is True
        assert "size" in output.metadata
        assert output.metadata["size"] > 0


# =============================================================================
# FsWriteTool Basic Tests
# =============================================================================


class TestFsWriteTool:
    """Tests for FsWriteTool."""

    def test_name(self, fs_write: FsWriteTool) -> None:
        """Tool has correct name."""
        assert fs_write.name == "fs.write"

    def test_registered_in_default_registry(self) -> None:
        """fs.write should be in the default registry."""
        assert "fs.write" in default_registry


# =============================================================================
# FsWriteTool Validation Tests
# =============================================================================


class TestFsWriteValidation:
    """Tests for fs.write argument validation."""

    def test_path_required(self, fs_write: FsWriteTool) -> None:
        """path argument is required."""
        errors = fs_write.validate_args({"content": "hello"})
        assert any("path" in e and "required" in e for e in errors)

    def test_content_required(self, fs_write: FsWriteTool) -> None:
        """content argument is required."""
        errors = fs_write.validate_args({"path": "./file"})
        assert any("content" in e and "required" in e for e in errors)

    def test_mode_must_be_valid(self, fs_write: FsWriteTool) -> None:
        """mode must be 'overwrite' or 'append'."""
        errors = fs_write.validate_args({
            "path": "./file",
            "content": "hello",
            "mode": "invalid",
        })
        assert any("mode" in e for e in errors)

    def test_valid_args(self, fs_write: FsWriteTool) -> None:
        """Valid arguments pass validation."""
        errors = fs_write.validate_args({
            "path": "./file",
            "content": "hello",
        })
        assert errors == []


# =============================================================================
# FsWriteTool Execution Tests
# =============================================================================


class TestFsWriteExecution:
    """Tests for fs.write execution."""

    def test_write_text_file(
        self,
        fs_write: FsWriteTool,
        context: ToolContext,
        temp_dir: Path,
    ) -> None:
        """Write a simple text file."""
        path = temp_dir / "output.txt"
        output = fs_write.execute(
            {"path": str(path), "content": "Hello, World!"},
            context,
        )
        assert output.success is True
        assert path.read_text() == "Hello, World!"

    def test_write_relative_path(
        self,
        fs_write: FsWriteTool,
        context: ToolContext,
        temp_dir: Path,
    ) -> None:
        """Write using relative path."""
        output = fs_write.execute(
            {"path": "output.txt", "content": "Hello!"},
            context,
        )
        assert output.success is True
        assert (temp_dir / "output.txt").read_text() == "Hello!"

    def test_overwrite_existing_file(
        self,
        fs_write: FsWriteTool,
        context: ToolContext,
        sample_file: Path,
    ) -> None:
        """Overwrite an existing file."""
        output = fs_write.execute(
            {"path": str(sample_file), "content": "New content"},
            context,
        )
        assert output.success is True
        assert sample_file.read_text() == "New content"

    def test_append_to_file(
        self,
        fs_write: FsWriteTool,
        context: ToolContext,
        sample_file: Path,
    ) -> None:
        """Append to an existing file."""
        original = sample_file.read_text()
        output = fs_write.execute(
            {"path": str(sample_file), "content": "Appended!", "mode": "append"},
            context,
        )
        assert output.success is True
        assert sample_file.read_text() == original + "Appended!"

    def test_write_bytes(
        self,
        fs_write: FsWriteTool,
        context: ToolContext,
        temp_dir: Path,
    ) -> None:
        """Write binary content."""
        path = temp_dir / "binary.bin"
        output = fs_write.execute(
            {"path": str(path), "content": b"\x00\x01\x02"},
            context,
        )
        assert output.success is True
        assert path.read_bytes() == b"\x00\x01\x02"

    def test_create_dirs(
        self,
        fs_write: FsWriteTool,
        context: ToolContext,
        temp_dir: Path,
    ) -> None:
        """Create parent directories when requested."""
        path = temp_dir / "a" / "b" / "c" / "file.txt"
        output = fs_write.execute(
            {"path": str(path), "content": "nested", "create_dirs": True},
            context,
        )
        assert output.success is True
        assert path.read_text() == "nested"

    def test_fail_without_create_dirs(
        self,
        fs_write: FsWriteTool,
        context: ToolContext,
        temp_dir: Path,
    ) -> None:
        """Fail when parent doesn't exist and create_dirs=False."""
        path = temp_dir / "nonexistent" / "file.txt"
        output = fs_write.execute(
            {"path": str(path), "content": "content"},
            context,
        )
        assert output.success is False
        assert "directory" in output.error.lower()
