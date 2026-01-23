"""
Unit tests for pack loader.

Tests cover:
- PackLoader initialization
- Pack resolution by name and path
- Manifest loading and validation
- Policy loading and merging
- Prompt template rendering
- Structure and input validation
"""

from pathlib import Path

import pytest

from capsule.errors import (
    PackInputError,
    PackManifestError,
    PackMissingFileError,
    PackNotFoundError,
)
from capsule.pack.loader import PackLoader
from capsule.schema import Policy


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def minimal_pack(temp_dir: Path) -> Path:
    """Create a minimal valid pack."""
    pack_dir = temp_dir / "minimal-pack"
    pack_dir.mkdir()

    # Create manifest.yaml
    (pack_dir / "manifest.yaml").write_text(
        """
name: minimal-pack
version: "1.0.0"
description: A minimal test pack
tools_required:
  - fs.read
yaml_entry: null
prompt_template: null
"""
    )

    # Create policy.yaml
    (pack_dir / "policy.yaml").write_text(
        """
boundary: deny_by_default
tools:
  fs.read:
    allow_paths:
      - "./**"
"""
    )

    return pack_dir


@pytest.fixture
def full_pack(temp_dir: Path) -> Path:
    """Create a full-featured pack with all files."""
    pack_dir = temp_dir / "full-pack"
    pack_dir.mkdir()
    (pack_dir / "prompts").mkdir()
    (pack_dir / "plans").mkdir()

    # Create manifest.yaml
    (pack_dir / "manifest.yaml").write_text(
        """
name: full-pack
version: "1.0.0"
description: A full test pack
author: Test Author
tools_required:
  - fs.read
  - http.get
yaml_entry: plans/default.yaml
prompt_template: prompts/system.txt
inputs:
  target_directory:
    type: string
    required: true
    description: Directory to scan
  output_format:
    type: string
    required: false
    default: json
    enum: [json, markdown, text]
  max_files:
    type: integer
    required: false
    default: 100
    min_value: 1
    max_value: 1000
outputs:
  report:
    type: object
    description: The generated report
"""
    )

    # Create policy.yaml
    (pack_dir / "policy.yaml").write_text(
        """
boundary: deny_by_default
global_timeout_seconds: 120
max_calls_per_tool: 50
tools:
  fs.read:
    allow_paths:
      - "./**"
    max_size_bytes: 1048576
  http.get:
    allow_domains:
      - api.github.com
"""
    )

    # Create prompts/system.txt
    (pack_dir / "prompts" / "system.txt").write_text(
        """You are a test assistant.
Pack: {{ pack_name }} v{{ pack_version }}
Target: {{ input.target_directory }}
Format: {{ input.output_format }}

Policy:
{{ policy_summary }}
"""
    )

    # Create plans/default.yaml
    (pack_dir / "plans" / "default.yaml").write_text(
        """
version: "1.0"
name: full-pack-plan
steps:
  - tool: fs.read
    args:
      path: "./README.md"
"""
    )

    return pack_dir


@pytest.fixture
def invalid_manifest_pack(temp_dir: Path) -> Path:
    """Create a pack with invalid manifest."""
    pack_dir = temp_dir / "invalid-pack"
    pack_dir.mkdir()

    # Create invalid manifest.yaml (missing required fields)
    (pack_dir / "manifest.yaml").write_text(
        """
description: Missing name and version
"""
    )

    return pack_dir


@pytest.fixture
def missing_policy_pack(temp_dir: Path) -> Path:
    """Create a pack with missing policy file."""
    pack_dir = temp_dir / "missing-policy"
    pack_dir.mkdir()

    # Create manifest.yaml
    (pack_dir / "manifest.yaml").write_text(
        """
name: missing-policy
version: "1.0.0"
"""
    )

    # Don't create policy.yaml

    return pack_dir


# =============================================================================
# PackLoader Initialization Tests
# =============================================================================


class TestPackLoaderInit:
    """Tests for PackLoader initialization."""

    def test_init_with_valid_path(self, minimal_pack: Path) -> None:
        """Initialize with valid pack directory."""
        loader = PackLoader(minimal_pack)
        # Compare resolved paths to handle macOS /var -> /private/var symlink
        assert loader.pack_path.resolve() == minimal_pack.resolve()

    def test_init_with_string_path(self, minimal_pack: Path) -> None:
        """Initialize with string path."""
        loader = PackLoader(str(minimal_pack))
        # Compare resolved paths to handle macOS /var -> /private/var symlink
        assert loader.pack_path.resolve() == minimal_pack.resolve()

    def test_init_resolves_path(self, minimal_pack: Path) -> None:
        """Path should be resolved to absolute."""
        loader = PackLoader(minimal_pack)
        assert loader.pack_path.is_absolute()

    def test_init_nonexistent_path_raises(self, temp_dir: Path) -> None:
        """Non-existent path should raise PackNotFoundError."""
        with pytest.raises(PackNotFoundError) as exc_info:
            PackLoader(temp_dir / "nonexistent")
        assert "nonexistent" in str(exc_info.value)

    def test_init_file_path_raises(self, minimal_pack: Path) -> None:
        """File path (not directory) should raise PackNotFoundError."""
        file_path = minimal_pack / "manifest.yaml"
        with pytest.raises(PackNotFoundError) as exc_info:
            PackLoader(file_path)
        assert "not a directory" in str(exc_info.value)


# =============================================================================
# Pack Resolution Tests
# =============================================================================


class TestPackResolution:
    """Tests for pack resolution by name."""

    def test_resolve_by_path(self, minimal_pack: Path) -> None:
        """Resolve pack by explicit path."""
        loader = PackLoader.resolve_pack(str(minimal_pack))
        # Compare resolved paths to handle macOS /var -> /private/var symlink
        assert loader.pack_path.resolve() == minimal_pack.resolve()

    def test_resolve_nonexistent_raises(self) -> None:
        """Non-existent pack should raise PackNotFoundError."""
        with pytest.raises(PackNotFoundError) as exc_info:
            PackLoader.resolve_pack("nonexistent-pack-12345")
        assert "not found" in str(exc_info.value)

    def test_list_bundled_packs_returns_list(self) -> None:
        """list_bundled_packs should return a list."""
        packs = PackLoader.list_bundled_packs()
        assert isinstance(packs, list)


# =============================================================================
# Manifest Loading Tests
# =============================================================================


class TestManifestLoading:
    """Tests for manifest loading."""

    def test_load_manifest_valid(self, minimal_pack: Path) -> None:
        """Load a valid manifest."""
        loader = PackLoader(minimal_pack)
        manifest = loader.load_manifest()
        assert manifest.name == "minimal-pack"
        assert manifest.version == "1.0.0"

    def test_load_manifest_full(self, full_pack: Path) -> None:
        """Load a full manifest with all fields."""
        loader = PackLoader(full_pack)
        manifest = loader.load_manifest()
        assert manifest.name == "full-pack"
        assert manifest.version == "1.0.0"
        assert manifest.author == "Test Author"
        assert "fs.read" in manifest.tools_required
        assert "http.get" in manifest.tools_required
        assert "target_directory" in manifest.inputs
        assert "output_format" in manifest.inputs
        assert "report" in manifest.outputs

    def test_load_manifest_cached(self, minimal_pack: Path) -> None:
        """Manifest should be cached after first load."""
        loader = PackLoader(minimal_pack)
        manifest1 = loader.manifest
        manifest2 = loader.manifest
        assert manifest1 is manifest2

    def test_load_manifest_missing_raises(self, temp_dir: Path) -> None:
        """Missing manifest should raise PackMissingFileError."""
        pack_dir = temp_dir / "no-manifest"
        pack_dir.mkdir()

        loader = PackLoader(pack_dir)
        with pytest.raises(PackMissingFileError) as exc_info:
            loader.load_manifest()
        assert "manifest.yaml" in str(exc_info.value)

    def test_load_manifest_invalid_raises(self, invalid_manifest_pack: Path) -> None:
        """Invalid manifest should raise PackManifestError."""
        loader = PackLoader(invalid_manifest_pack)
        with pytest.raises(PackManifestError):
            loader.load_manifest()

    def test_load_manifest_empty_raises(self, temp_dir: Path) -> None:
        """Empty manifest should raise PackManifestError."""
        pack_dir = temp_dir / "empty-manifest"
        pack_dir.mkdir()
        (pack_dir / "manifest.yaml").write_text("")

        loader = PackLoader(pack_dir)
        with pytest.raises(PackManifestError) as exc_info:
            loader.load_manifest()
        assert "Empty manifest" in str(exc_info.value)

    def test_load_manifest_invalid_yaml_raises(self, temp_dir: Path) -> None:
        """Invalid YAML should raise PackManifestError."""
        pack_dir = temp_dir / "bad-yaml"
        pack_dir.mkdir()
        (pack_dir / "manifest.yaml").write_text("name: [invalid yaml")

        loader = PackLoader(pack_dir)
        with pytest.raises(PackManifestError) as exc_info:
            loader.load_manifest()
        assert "Invalid YAML" in str(exc_info.value)


# =============================================================================
# Policy Loading Tests
# =============================================================================


class TestPolicyLoading:
    """Tests for policy loading and merging."""

    def test_load_policy(self, minimal_pack: Path) -> None:
        """Load pack policy."""
        loader = PackLoader(minimal_pack)
        policy = loader.load_policy()
        assert isinstance(policy, Policy)

    def test_load_policy_missing_raises(self, missing_policy_pack: Path) -> None:
        """Missing policy file should raise PackMissingFileError."""
        loader = PackLoader(missing_policy_pack)
        with pytest.raises(PackMissingFileError) as exc_info:
            loader.load_policy()
        assert "policy.yaml" in str(exc_info.value)

    def test_merge_policy_none_returns_pack_policy(self, minimal_pack: Path) -> None:
        """merge_policy with None returns pack policy."""
        loader = PackLoader(minimal_pack)
        policy = loader.merge_policy(None)
        assert isinstance(policy, Policy)

    def test_merge_policy_user_overrides(self, minimal_pack: Path) -> None:
        """User policy should override pack policy."""
        loader = PackLoader(minimal_pack)
        pack_policy = loader.load_policy()

        # Create a different policy
        from capsule.schema import load_policy_from_string

        user_policy = load_policy_from_string(
            """
boundary: deny_by_default
global_timeout_seconds: 999
tools: {}
"""
        )

        merged = loader.merge_policy(user_policy)
        assert merged is user_policy
        assert merged.global_timeout_seconds == 999


# =============================================================================
# Prompt Rendering Tests
# =============================================================================


class TestPromptRendering:
    """Tests for prompt template rendering."""

    def test_render_prompt_basic(self, full_pack: Path) -> None:
        """Render prompt with basic inputs."""
        loader = PackLoader(full_pack)
        inputs = {
            "target_directory": "/tmp/docs",
            "output_format": "json",
        }
        prompt = loader.render_prompt(inputs)

        assert "full-pack" in prompt
        assert "1.0.0" in prompt
        assert "/tmp/docs" in prompt
        assert "json" in prompt

    def test_render_prompt_includes_policy_summary(self, full_pack: Path) -> None:
        """Rendered prompt should include policy summary."""
        loader = PackLoader(full_pack)
        inputs = {"target_directory": "/tmp", "output_format": "json"}
        prompt = loader.render_prompt(inputs)

        assert "deny_by_default" in prompt

    def test_render_prompt_missing_template_raises(self, minimal_pack: Path) -> None:
        """Missing prompt template should raise PackMissingFileError."""
        loader = PackLoader(minimal_pack)
        with pytest.raises(PackMissingFileError):
            loader.render_prompt({"target": "/tmp"})

    def test_build_policy_summary(self, full_pack: Path) -> None:
        """build_policy_summary should return human-readable text."""
        loader = PackLoader(full_pack)
        summary = loader.build_policy_summary()

        assert "deny_by_default" in summary
        assert "fs.read" in summary
        assert "http.get" in summary
        assert "api.github.com" in summary


# =============================================================================
# Structure Validation Tests
# =============================================================================


class TestStructureValidation:
    """Tests for pack structure validation."""

    def test_validate_structure_valid(self, full_pack: Path) -> None:
        """Valid pack should have no errors."""
        loader = PackLoader(full_pack)
        errors = loader.validate_structure()
        assert errors == []

    def test_validate_structure_missing_manifest(self, temp_dir: Path) -> None:
        """Missing manifest should report error."""
        pack_dir = temp_dir / "no-manifest"
        pack_dir.mkdir()

        loader = PackLoader(pack_dir)
        errors = loader.validate_structure()
        assert any("manifest.yaml" in e for e in errors)

    def test_validate_structure_missing_policy(self, missing_policy_pack: Path) -> None:
        """Missing policy should report error."""
        loader = PackLoader(missing_policy_pack)
        errors = loader.validate_structure()
        assert any("policy.yaml" in e.lower() for e in errors)

    def test_validate_structure_missing_prompt(self, temp_dir: Path) -> None:
        """Missing prompt template should report error if specified."""
        pack_dir = temp_dir / "missing-prompt"
        pack_dir.mkdir()
        (pack_dir / "manifest.yaml").write_text(
            """
name: missing-prompt
version: "1.0.0"
prompt_template: prompts/system.txt
"""
        )
        (pack_dir / "policy.yaml").write_text("boundary: deny_by_default\ntools: {}")

        loader = PackLoader(pack_dir)
        errors = loader.validate_structure()
        assert any("prompts/system.txt" in e for e in errors)


# =============================================================================
# Input Validation Tests
# =============================================================================


class TestInputValidation:
    """Tests for input validation."""

    def test_validate_inputs_valid(self, full_pack: Path) -> None:
        """Valid inputs should pass validation."""
        loader = PackLoader(full_pack)
        inputs = {
            "target_directory": "/tmp/docs",
            "output_format": "json",
            "max_files": 50,
        }
        errors = loader.validate_inputs(inputs)
        assert errors == []

    def test_validate_inputs_missing_required(self, full_pack: Path) -> None:
        """Missing required input should fail."""
        loader = PackLoader(full_pack)
        inputs = {
            "output_format": "json",
        }
        errors = loader.validate_inputs(inputs)
        assert any("target_directory" in e for e in errors)

    def test_validate_inputs_invalid_type(self, full_pack: Path) -> None:
        """Wrong type should fail."""
        loader = PackLoader(full_pack)
        inputs = {
            "target_directory": 123,  # Should be string
        }
        errors = loader.validate_inputs(inputs)
        assert any("wrong type" in e for e in errors)

    def test_validate_inputs_invalid_enum(self, full_pack: Path) -> None:
        """Invalid enum value should fail."""
        loader = PackLoader(full_pack)
        inputs = {
            "target_directory": "/tmp",
            "output_format": "invalid",
        }
        errors = loader.validate_inputs(inputs)
        assert any("not in allowed values" in e for e in errors)

    def test_validate_inputs_unknown_input(self, full_pack: Path) -> None:
        """Unknown input should fail."""
        loader = PackLoader(full_pack)
        inputs = {
            "target_directory": "/tmp",
            "unknown_input": "value",
        }
        errors = loader.validate_inputs(inputs)
        assert any("Unknown input" in e for e in errors)

    def test_validate_inputs_below_min(self, full_pack: Path) -> None:
        """Value below minimum should fail."""
        loader = PackLoader(full_pack)
        inputs = {
            "target_directory": "/tmp",
            "max_files": 0,  # min is 1
        }
        errors = loader.validate_inputs(inputs)
        assert any("less than minimum" in e for e in errors)

    def test_validate_inputs_above_max(self, full_pack: Path) -> None:
        """Value above maximum should fail."""
        loader = PackLoader(full_pack)
        inputs = {
            "target_directory": "/tmp",
            "max_files": 9999,  # max is 1000
        }
        errors = loader.validate_inputs(inputs)
        assert any("greater than maximum" in e for e in errors)

    def test_get_validated_inputs_applies_defaults(self, full_pack: Path) -> None:
        """get_validated_inputs should apply defaults."""
        loader = PackLoader(full_pack)
        inputs = {
            "target_directory": "/tmp",
        }
        validated = loader.get_validated_inputs(inputs)
        assert validated["target_directory"] == "/tmp"
        assert validated["output_format"] == "json"  # default
        assert validated["max_files"] == 100  # default

    def test_get_validated_inputs_raises_on_invalid(self, full_pack: Path) -> None:
        """get_validated_inputs should raise PackInputError on invalid."""
        loader = PackLoader(full_pack)
        inputs = {}  # Missing required
        with pytest.raises(PackInputError):
            loader.get_validated_inputs(inputs)


# =============================================================================
# Plan Loading Tests
# =============================================================================


class TestPlanLoading:
    """Tests for plan loading."""

    def test_get_plan_with_yaml_entry(self, full_pack: Path) -> None:
        """get_plan should return plan when yaml_entry exists."""
        loader = PackLoader(full_pack)
        plan = loader.get_plan()
        assert plan is not None
        assert plan.name == "full-pack-plan"

    def test_get_plan_null_yaml_entry(self, minimal_pack: Path) -> None:
        """get_plan should return None when yaml_entry is null."""
        loader = PackLoader(minimal_pack)
        plan = loader.get_plan()
        assert plan is None

    def test_get_plan_missing_file_raises(self, temp_dir: Path) -> None:
        """Missing plan file should raise PackMissingFileError."""
        pack_dir = temp_dir / "missing-plan"
        pack_dir.mkdir()
        (pack_dir / "manifest.yaml").write_text(
            """
name: missing-plan
version: "1.0.0"
yaml_entry: plans/missing.yaml
"""
        )
        (pack_dir / "policy.yaml").write_text("boundary: deny_by_default\ntools: {}")

        loader = PackLoader(pack_dir)
        with pytest.raises(PackMissingFileError):
            loader.get_plan()
