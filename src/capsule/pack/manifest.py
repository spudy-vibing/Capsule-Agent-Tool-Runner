"""
Pack manifest schema definitions.

This module defines the Pydantic models for pack manifests:
- PackInputSchema: Input parameter definitions
- PackOutputSchema: Output definitions
- PackManifest: Complete pack manifest

Design Decisions:
    - All models use strict validation (extra="forbid")
    - PackManifest is frozen (immutable after creation)
    - Input/output schemas support type validation
    - Pack names follow lowercase alphanumeric with hyphens/underscores
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# Input/Output Schema Models
# =============================================================================


class PackInputSchema(BaseModel):
    """
    Schema for a single pack input parameter.

    Defines the type, constraints, and metadata for pack inputs.
    Supports common types: string, integer, boolean, number, array, object.

    Attributes:
        type: Data type (string, integer, boolean, number, array, object)
        required: Whether this input is required
        default: Default value if not provided
        description: Human-readable description
        enum: Allowed values for string type
        pattern: Regex pattern for string validation
        items: Item type for array type
        min_value: Minimum value for numeric types
        max_value: Maximum value for numeric types
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str = Field(
        ...,
        description="Input type: string, integer, boolean, number, array, object",
    )
    required: bool = Field(
        default=True,
        description="Whether this input is required",
    )
    default: Any = Field(
        default=None,
        description="Default value if not provided",
    )
    description: str = Field(
        default="",
        description="Human-readable description of this input",
    )
    enum: list[str] | None = Field(
        default=None,
        description="Allowed values for string type",
    )
    pattern: str | None = Field(
        default=None,
        description="Regex pattern for string validation",
    )
    items: str | None = Field(
        default=None,
        description="Item type for array type",
    )
    min_value: int | float | None = Field(
        default=None,
        description="Minimum value for numeric types",
    )
    max_value: int | float | None = Field(
        default=None,
        description="Maximum value for numeric types",
    )

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Validate that type is a known type."""
        valid_types = {"string", "integer", "boolean", "number", "array", "object"}
        if v not in valid_types:
            msg = f"Invalid input type: {v}. Must be one of: {', '.join(sorted(valid_types))}"
            raise ValueError(msg)
        return v


class PackOutputSchema(BaseModel):
    """
    Schema for a single pack output.

    Describes the expected output format from pack execution.

    Attributes:
        type: Output data type
        description: Human-readable description
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str = Field(
        ...,
        description="Output type: string, integer, boolean, number, array, object",
    )
    description: str = Field(
        default="",
        description="Human-readable description of this output",
    )


# =============================================================================
# Pack Manifest Model
# =============================================================================


# Known tools in Capsule v0.2
KNOWN_TOOLS = {"fs.read", "fs.write", "http.get", "shell.run"}


class PackManifest(BaseModel):
    """
    Complete manifest for a Capsule pack.

    The manifest defines all metadata, requirements, and configuration
    for a pack. It is loaded from manifest.yaml in the pack directory.

    Attributes:
        name: Unique pack identifier (lowercase alphanumeric with hyphens/underscores)
        version: Semantic version string (e.g., "1.0.0")
        description: Human-readable description of what the pack does
        author: Pack author name or organization
        license: License identifier (e.g., "MIT", "Apache-2.0")
        tags: List of tags for categorization
        capsule_version: Required Capsule version (e.g., ">=0.2.0")
        tools_required: List of tool identifiers this pack uses
        yaml_entry: Path to YAML plan file (relative to pack root)
        prompt_template: Path to prompt template file (relative to pack root)
        default_policy: Path to default policy file (relative to pack root)
        inputs: Input parameter schemas
        outputs: Output schemas
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Identity
    name: str = Field(
        ...,
        description="Unique pack identifier",
        min_length=1,
        max_length=64,
    )
    version: str = Field(
        ...,
        description="Semantic version string",
    )
    description: str = Field(
        default="",
        description="Human-readable description",
    )
    author: str = Field(
        default="",
        description="Pack author name or organization",
    )
    license: str = Field(
        default="MIT",
        description="License identifier",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for categorization",
    )
    capsule_version: str = Field(
        default=">=0.2.0",
        description="Required Capsule version",
    )

    # Tool requirements
    tools_required: list[str] = Field(
        default_factory=list,
        description="List of tool identifiers this pack uses",
    )

    # File paths (relative to pack root)
    yaml_entry: str | None = Field(
        default="plans/default.yaml",
        description="Path to YAML plan file (null for agent-only packs)",
    )
    prompt_template: str | None = Field(
        default="prompts/system.txt",
        description="Path to prompt template file",
    )
    # Note: policy.yaml is always expected at pack root (convention over configuration)

    # Schemas
    inputs: dict[str, PackInputSchema] = Field(
        default_factory=dict,
        description="Input parameter schemas",
    )
    outputs: dict[str, PackOutputSchema] = Field(
        default_factory=dict,
        description="Output schemas",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate pack name format (lowercase alphanumeric with hyphens/underscores)."""
        import re

        if not re.match(r"^[a-z][a-z0-9_-]*$", v):
            msg = (
                f"Invalid pack name: {v}. "
                "Must start with lowercase letter, contain only lowercase letters, "
                "numbers, hyphens, and underscores."
            )
            raise ValueError(msg)
        return v

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        """Validate semantic version format."""
        import re

        # Simple semver pattern: major.minor.patch with optional pre-release
        if not re.match(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$", v):
            msg = f"Invalid version format: {v}. Expected semver (e.g., '1.0.0')"
            raise ValueError(msg)
        return v

    @field_validator("tools_required")
    @classmethod
    def validate_tools(cls, v: list[str]) -> list[str]:
        """Validate that all tools are known."""
        unknown = set(v) - KNOWN_TOOLS
        if unknown:
            msg = f"Unknown tools: {', '.join(sorted(unknown))}. Known tools: {', '.join(sorted(KNOWN_TOOLS))}"
            raise ValueError(msg)
        return v

    @field_validator("capsule_version")
    @classmethod
    def validate_capsule_version(cls, v: str) -> str:
        """Validate capsule version requirement format."""
        import re

        # Support formats like ">=0.2.0", "==1.0.0", "~=0.2"
        if not re.match(r"^(>=|<=|==|~=|>|<)?\d+\.\d+(\.\d+)?$", v):
            msg = f"Invalid capsule_version format: {v}. Expected format like '>=0.2.0'"
            raise ValueError(msg)
        return v
