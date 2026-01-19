"""
Unit tests for tool base classes and registry.

Tests cover:
- ToolOutput creation and methods
- ToolContext creation
- Tool ABC implementation
- ToolRegistry operations
"""

from typing import Any

import pytest

from capsule.errors import ToolNotFoundError
from capsule.tools import (
    Tool,
    ToolContext,
    ToolOutput,
    ToolRegistry,
    default_registry,
    get_tool,
    register_tool,
)


# =============================================================================
# Test Fixtures
# =============================================================================


class MockTool(Tool):
    """A simple mock tool for testing."""

    def __init__(self, tool_name: str = "mock.tool") -> None:
        self._name = tool_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "A mock tool for testing"

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        message = args.get("message", "default")
        return ToolOutput.ok(f"executed: {message}")


class FailingTool(Tool):
    """A tool that always fails."""

    @property
    def name(self) -> str:
        return "failing.tool"

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        return ToolOutput.fail("This tool always fails")


class ValidatingTool(Tool):
    """A tool with argument validation."""

    @property
    def name(self) -> str:
        return "validating.tool"

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        return ToolOutput.ok(args)

    def validate_args(self, args: dict[str, Any]) -> list[str]:
        errors = []
        if "required_field" not in args:
            errors.append("missing required_field")
        return errors


# =============================================================================
# ToolOutput Tests
# =============================================================================


class TestToolOutput:
    """Tests for ToolOutput dataclass."""

    def test_create_success(self) -> None:
        """Create a successful output."""
        output = ToolOutput(success=True, data="result")
        assert output.success is True
        assert output.data == "result"
        assert output.error is None
        assert output.metadata == {}

    def test_create_failure(self) -> None:
        """Create a failed output."""
        output = ToolOutput(success=False, error="something went wrong")
        assert output.success is False
        assert output.data is None
        assert output.error == "something went wrong"

    def test_ok_helper(self) -> None:
        """Use ToolOutput.ok() helper."""
        output = ToolOutput.ok("data", key="value")
        assert output.success is True
        assert output.data == "data"
        assert output.metadata["key"] == "value"

    def test_fail_helper(self) -> None:
        """Use ToolOutput.fail() helper."""
        output = ToolOutput.fail("error message", key="value")
        assert output.success is False
        assert output.error == "error message"
        assert output.metadata["key"] == "value"

    def test_is_frozen(self) -> None:
        """ToolOutput should be immutable."""
        output = ToolOutput.ok("data")
        with pytest.raises(AttributeError):
            output.success = False  # type: ignore

    def test_various_data_types(self) -> None:
        """ToolOutput can hold various data types."""
        # String
        assert ToolOutput.ok("hello").data == "hello"
        # Dict
        assert ToolOutput.ok({"key": "value"}).data == {"key": "value"}
        # List
        assert ToolOutput.ok([1, 2, 3]).data == [1, 2, 3]
        # Bytes
        assert ToolOutput.ok(b"binary").data == b"binary"
        # None
        assert ToolOutput.ok(None).data is None


# =============================================================================
# ToolContext Tests
# =============================================================================


class TestToolContext:
    """Tests for ToolContext dataclass."""

    def test_create_minimal(self) -> None:
        """Create context with just run_id."""
        context = ToolContext(run_id="run-123")
        assert context.run_id == "run-123"
        assert context.policy is None
        assert context.working_dir == "."
        assert context.metadata == {}

    def test_create_full(self) -> None:
        """Create context with all fields."""
        context = ToolContext(
            run_id="run-123",
            working_dir="/home/user",
            metadata={"key": "value"},
        )
        assert context.run_id == "run-123"
        assert context.working_dir == "/home/user"
        assert context.metadata["key"] == "value"

    def test_is_mutable(self) -> None:
        """ToolContext is mutable for metadata updates."""
        context = ToolContext(run_id="run-123")
        context.metadata["new_key"] = "new_value"
        assert context.metadata["new_key"] == "new_value"


# =============================================================================
# Tool ABC Tests
# =============================================================================


class TestTool:
    """Tests for Tool ABC."""

    def test_mock_tool_name(self) -> None:
        """Mock tool has correct name."""
        tool = MockTool()
        assert tool.name == "mock.tool"

    def test_mock_tool_description(self) -> None:
        """Mock tool has description."""
        tool = MockTool()
        assert "mock" in tool.description.lower()

    def test_mock_tool_execute(self) -> None:
        """Mock tool executes correctly."""
        tool = MockTool()
        context = ToolContext(run_id="test")
        output = tool.execute({"message": "hello"}, context)
        assert output.success is True
        assert "hello" in output.data

    def test_failing_tool(self) -> None:
        """Failing tool returns failure output."""
        tool = FailingTool()
        context = ToolContext(run_id="test")
        output = tool.execute({}, context)
        assert output.success is False
        assert "fails" in output.error.lower()

    def test_validate_args_default(self) -> None:
        """Default validate_args accepts anything."""
        tool = MockTool()
        errors = tool.validate_args({"any": "thing"})
        assert errors == []

    def test_validate_args_custom(self) -> None:
        """Custom validate_args can reject args."""
        tool = ValidatingTool()

        # Missing required field
        errors = tool.validate_args({})
        assert len(errors) == 1
        assert "required_field" in errors[0]

        # Has required field
        errors = tool.validate_args({"required_field": "value"})
        assert errors == []

    def test_tool_repr(self) -> None:
        """Tool has readable repr."""
        tool = MockTool()
        assert "mock.tool" in repr(tool)


# =============================================================================
# ToolRegistry Tests
# =============================================================================


class TestToolRegistry:
    """Tests for ToolRegistry."""

    @pytest.fixture
    def registry(self) -> ToolRegistry:
        """Create a fresh registry for each test."""
        return ToolRegistry()

    def test_empty_registry(self, registry: ToolRegistry) -> None:
        """New registry is empty."""
        assert len(registry) == 0
        assert registry.list_tools() == []

    def test_register_tool(self, registry: ToolRegistry) -> None:
        """Register a tool."""
        tool = MockTool()
        registry.register(tool)
        assert len(registry) == 1
        assert "mock.tool" in registry

    def test_get_registered_tool(self, registry: ToolRegistry) -> None:
        """Get a registered tool."""
        tool = MockTool()
        registry.register(tool)
        retrieved = registry.get("mock.tool")
        assert retrieved is tool

    def test_get_unregistered_tool_raises(self, registry: ToolRegistry) -> None:
        """Getting unknown tool raises ToolNotFoundError."""
        with pytest.raises(ToolNotFoundError) as exc_info:
            registry.get("unknown.tool")
        assert "unknown.tool" in str(exc_info.value)

    def test_get_optional(self, registry: ToolRegistry) -> None:
        """get_optional returns None for unknown tools."""
        assert registry.get_optional("unknown") is None

        tool = MockTool()
        registry.register(tool)
        assert registry.get_optional("mock.tool") is tool

    def test_has(self, registry: ToolRegistry) -> None:
        """has() checks if tool is registered."""
        assert not registry.has("mock.tool")

        registry.register(MockTool())
        assert registry.has("mock.tool")

    def test_unregister(self, registry: ToolRegistry) -> None:
        """Unregister a tool."""
        registry.register(MockTool())
        assert registry.has("mock.tool")

        result = registry.unregister("mock.tool")
        assert result is True
        assert not registry.has("mock.tool")

        # Unregistering again returns False
        result = registry.unregister("mock.tool")
        assert result is False

    def test_clear(self, registry: ToolRegistry) -> None:
        """Clear all tools from registry."""
        registry.register(MockTool("tool1"))
        registry.register(MockTool("tool2"))
        assert len(registry) == 2

        registry.clear()
        assert len(registry) == 0

    def test_list_tools(self, registry: ToolRegistry) -> None:
        """List all registered tool names."""
        registry.register(MockTool("z.tool"))
        registry.register(MockTool("a.tool"))
        registry.register(MockTool("m.tool"))

        tools = registry.list_tools()
        assert tools == ["a.tool", "m.tool", "z.tool"]  # Sorted

    def test_iterate(self, registry: ToolRegistry) -> None:
        """Iterate over registered tools."""
        registry.register(MockTool("tool1"))
        registry.register(MockTool("tool2"))

        names = [tool.name for tool in registry]
        assert "tool1" in names
        assert "tool2" in names

    def test_contains(self, registry: ToolRegistry) -> None:
        """Use 'in' operator to check registration."""
        registry.register(MockTool())
        assert "mock.tool" in registry
        assert "unknown" not in registry

    def test_repr(self, registry: ToolRegistry) -> None:
        """Registry has readable repr."""
        registry.register(MockTool())
        assert "mock.tool" in repr(registry)

    def test_register_none_raises(self, registry: ToolRegistry) -> None:
        """Registering None raises ValueError."""
        with pytest.raises(ValueError, match="None"):
            registry.register(None)  # type: ignore

    def test_reregister_replaces(self, registry: ToolRegistry) -> None:
        """Re-registering a tool replaces the old one."""
        tool1 = MockTool()
        tool2 = MockTool()

        registry.register(tool1)
        registry.register(tool2)

        assert len(registry) == 1
        assert registry.get("mock.tool") is tool2


# =============================================================================
# Global Registry Tests
# =============================================================================


class TestGlobalRegistry:
    """Tests for global registry and convenience functions."""

    @pytest.fixture(autouse=True)
    def cleanup_registry(self) -> None:
        """Clean up global registry after each test."""
        # Store original tools
        original = list(default_registry)

        yield

        # Restore original state
        default_registry.clear()
        for tool in original:
            default_registry.register(tool)

    def test_register_tool_function(self) -> None:
        """register_tool() adds to default registry."""
        tool = MockTool("global.test.tool")
        register_tool(tool)
        assert "global.test.tool" in default_registry

    def test_get_tool_function(self) -> None:
        """get_tool() retrieves from default registry."""
        tool = MockTool("global.test.tool2")
        default_registry.register(tool)
        retrieved = get_tool("global.test.tool2")
        assert retrieved is tool

    def test_get_tool_not_found(self) -> None:
        """get_tool() raises for unknown tools."""
        with pytest.raises(ToolNotFoundError):
            get_tool("definitely.not.registered")
