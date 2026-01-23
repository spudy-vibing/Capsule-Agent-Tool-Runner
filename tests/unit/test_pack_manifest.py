"""
Unit tests for pack manifest schema validation.

Tests cover:
- PackInputSchema parsing and validation
- PackOutputSchema parsing and validation
- PackManifest parsing and validation
- Type and constraint validation
- Edge cases and error handling
"""

import pytest
from pydantic import ValidationError

from capsule.pack.manifest import (
    KNOWN_TOOLS,
    PackInputSchema,
    PackManifest,
    PackOutputSchema,
)


# =============================================================================
# PackInputSchema Tests
# =============================================================================


class TestPackInputSchema:
    """Tests for PackInputSchema model."""

    def test_minimal_input(self) -> None:
        """Input only needs a type."""
        schema = PackInputSchema(type="string")
        assert schema.type == "string"
        assert schema.required is True
        assert schema.default is None
        assert schema.description == ""

    def test_full_input_schema(self) -> None:
        """Input with all fields populated."""
        schema = PackInputSchema(
            type="string",
            required=False,
            default="hello",
            description="A greeting",
            enum=["hello", "hi", "hey"],
            pattern="^h.*",
        )
        assert schema.type == "string"
        assert schema.required is False
        assert schema.default == "hello"
        assert schema.description == "A greeting"
        assert schema.enum == ["hello", "hi", "hey"]
        assert schema.pattern == "^h.*"

    def test_valid_types(self) -> None:
        """All valid input types."""
        for type_name in ["string", "integer", "boolean", "number", "array", "object"]:
            schema = PackInputSchema(type=type_name)
            assert schema.type == type_name

    def test_invalid_type_rejected(self) -> None:
        """Unknown type should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PackInputSchema(type="unknown")
        assert "Invalid input type" in str(exc_info.value)

    def test_array_with_items(self) -> None:
        """Array type with items specification."""
        schema = PackInputSchema(type="array", items="string")
        assert schema.type == "array"
        assert schema.items == "string"

    def test_numeric_range(self) -> None:
        """Numeric type with min/max values."""
        schema = PackInputSchema(
            type="integer",
            min_value=0,
            max_value=100,
        )
        assert schema.min_value == 0
        assert schema.max_value == 100

    def test_schema_is_immutable(self) -> None:
        """Schema should be immutable (frozen)."""
        schema = PackInputSchema(type="string")
        with pytest.raises(ValidationError):
            schema.type = "integer"  # type: ignore

    def test_extra_fields_rejected(self) -> None:
        """Unknown fields should be rejected."""
        with pytest.raises(ValidationError):
            PackInputSchema(type="string", unknown="value")  # type: ignore


# =============================================================================
# PackOutputSchema Tests
# =============================================================================


class TestPackOutputSchema:
    """Tests for PackOutputSchema model."""

    def test_minimal_output(self) -> None:
        """Output only needs a type."""
        schema = PackOutputSchema(type="string")
        assert schema.type == "string"
        assert schema.description == ""

    def test_output_with_description(self) -> None:
        """Output with description."""
        schema = PackOutputSchema(
            type="object",
            description="The result object",
        )
        assert schema.type == "object"
        assert schema.description == "The result object"

    def test_output_is_immutable(self) -> None:
        """Schema should be immutable (frozen)."""
        schema = PackOutputSchema(type="string")
        with pytest.raises(ValidationError):
            schema.type = "integer"  # type: ignore


# =============================================================================
# PackManifest Tests
# =============================================================================


class TestPackManifest:
    """Tests for PackManifest model."""

    def test_minimal_manifest(self) -> None:
        """Manifest only needs name and version."""
        manifest = PackManifest(name="test-pack", version="1.0.0")
        assert manifest.name == "test-pack"
        assert manifest.version == "1.0.0"
        assert manifest.description == ""
        assert manifest.author == ""
        assert manifest.license == "MIT"
        assert manifest.tags == []
        assert manifest.capsule_version == ">=0.2.0"
        assert manifest.tools_required == []
        assert manifest.yaml_entry == "plans/default.yaml"
        assert manifest.prompt_template == "prompts/system.txt"
        assert manifest.inputs == {}
        assert manifest.outputs == {}

    def test_full_manifest(self) -> None:
        """Manifest with all fields populated."""
        manifest = PackManifest(
            name="my-pack",
            version="2.1.0",
            description="A test pack",
            author="Test Author",
            license="Apache-2.0",
            tags=["test", "example"],
            capsule_version=">=0.2.0",
            tools_required=["fs.read", "http.get"],
            yaml_entry="plans/main.yaml",
            prompt_template="prompts/main.txt",
            inputs={
                "target": PackInputSchema(type="string", required=True),
            },
            outputs={
                "result": PackOutputSchema(type="object"),
            },
        )
        assert manifest.name == "my-pack"
        assert manifest.version == "2.1.0"
        assert manifest.description == "A test pack"
        assert manifest.author == "Test Author"
        assert manifest.license == "Apache-2.0"
        assert manifest.tags == ["test", "example"]
        assert manifest.tools_required == ["fs.read", "http.get"]

    # Name validation tests

    def test_valid_names(self) -> None:
        """Various valid pack names."""
        valid_names = [
            "pack",
            "my-pack",
            "my_pack",
            "pack123",
            "a",
            "my-cool-pack-v2",
        ]
        for name in valid_names:
            manifest = PackManifest(name=name, version="1.0.0")
            assert manifest.name == name

    def test_name_must_start_with_letter(self) -> None:
        """Pack name must start with a lowercase letter."""
        with pytest.raises(ValidationError) as exc_info:
            PackManifest(name="123pack", version="1.0.0")
        assert "Invalid pack name" in str(exc_info.value)

    def test_uppercase_name_rejected(self) -> None:
        """Pack name with uppercase should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PackManifest(name="MyPack", version="1.0.0")
        assert "Invalid pack name" in str(exc_info.value)

    def test_empty_name_rejected(self) -> None:
        """Empty pack name should be rejected."""
        with pytest.raises(ValidationError):
            PackManifest(name="", version="1.0.0")

    def test_name_with_special_chars_rejected(self) -> None:
        """Pack name with special characters should be rejected."""
        invalid_names = ["my.pack", "my/pack", "my pack", "my@pack"]
        for name in invalid_names:
            with pytest.raises(ValidationError):
                PackManifest(name=name, version="1.0.0")

    # Version validation tests

    def test_valid_versions(self) -> None:
        """Various valid version strings."""
        valid_versions = [
            "1.0.0",
            "0.1.0",
            "10.20.30",
            "1.0.0-alpha",
            "1.0.0-beta.1",
            "2.0.0-rc.1",
        ]
        for version in valid_versions:
            manifest = PackManifest(name="test", version=version)
            assert manifest.version == version

    def test_invalid_version_rejected(self) -> None:
        """Invalid version formats should be rejected."""
        invalid_versions = [
            "1.0",  # missing patch
            "1",  # only major
            "v1.0.0",  # prefix v
            "1.0.0.0",  # too many parts
        ]
        for version in invalid_versions:
            with pytest.raises(ValidationError) as exc_info:
                PackManifest(name="test", version=version)
            assert "Invalid version format" in str(exc_info.value)

    # Tools validation tests

    def test_valid_tools_required(self) -> None:
        """Valid tools should be accepted."""
        for tool in KNOWN_TOOLS:
            manifest = PackManifest(
                name="test",
                version="1.0.0",
                tools_required=[tool],
            )
            assert tool in manifest.tools_required

    def test_all_tools_required(self) -> None:
        """All known tools can be required."""
        manifest = PackManifest(
            name="test",
            version="1.0.0",
            tools_required=list(KNOWN_TOOLS),
        )
        assert set(manifest.tools_required) == KNOWN_TOOLS

    def test_unknown_tool_rejected(self) -> None:
        """Unknown tool should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PackManifest(
                name="test",
                version="1.0.0",
                tools_required=["unknown.tool"],
            )
        assert "Unknown tools" in str(exc_info.value)

    # Capsule version validation tests

    def test_valid_capsule_versions(self) -> None:
        """Various valid capsule version requirements."""
        valid_versions = [
            ">=0.2.0",
            "==1.0.0",
            ">=0.2",
            "~=0.2",
            ">0.1.0",
            "<1.0.0",
        ]
        for version in valid_versions:
            manifest = PackManifest(
                name="test",
                version="1.0.0",
                capsule_version=version,
            )
            assert manifest.capsule_version == version

    def test_invalid_capsule_version_rejected(self) -> None:
        """Invalid capsule version requirement should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PackManifest(
                name="test",
                version="1.0.0",
                capsule_version="invalid",
            )
        assert "Invalid capsule_version format" in str(exc_info.value)

    # Immutability tests

    def test_manifest_is_immutable(self) -> None:
        """Manifest should be immutable (frozen)."""
        manifest = PackManifest(name="test", version="1.0.0")
        with pytest.raises(ValidationError):
            manifest.name = "other"  # type: ignore

    def test_extra_fields_rejected(self) -> None:
        """Unknown fields should be rejected."""
        with pytest.raises(ValidationError):
            PackManifest(
                name="test",
                version="1.0.0",
                unknown_field="value",  # type: ignore
            )

    # Optional fields tests

    def test_null_yaml_entry(self) -> None:
        """yaml_entry can be null for agent-only packs."""
        manifest = PackManifest(
            name="test",
            version="1.0.0",
            yaml_entry=None,
        )
        assert manifest.yaml_entry is None

    def test_null_prompt_template(self) -> None:
        """prompt_template can be null."""
        manifest = PackManifest(
            name="test",
            version="1.0.0",
            prompt_template=None,
        )
        assert manifest.prompt_template is None


# =============================================================================
# KNOWN_TOOLS Tests
# =============================================================================


class TestKnownTools:
    """Tests for KNOWN_TOOLS constant."""

    def test_known_tools_contains_core_tools(self) -> None:
        """KNOWN_TOOLS should contain all core Capsule tools."""
        assert "fs.read" in KNOWN_TOOLS
        assert "fs.write" in KNOWN_TOOLS
        assert "http.get" in KNOWN_TOOLS
        assert "shell.run" in KNOWN_TOOLS

    def test_known_tools_count(self) -> None:
        """KNOWN_TOOLS should have exactly 4 tools in v0.2."""
        assert len(KNOWN_TOOLS) == 4
