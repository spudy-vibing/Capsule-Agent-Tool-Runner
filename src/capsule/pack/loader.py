"""
Pack loader for loading and validating pack structures.

This module provides the PackLoader class for:
- Resolving packs by name (bundled or custom path)
- Loading and validating manifest.yaml
- Loading and merging policy.yaml
- Rendering Jinja2 prompt templates
- Validating pack structure and inputs

Design Decisions:
    - Bundled packs are in the packs/ directory at project root
    - User policy overrides pack policy (not merged)
    - Jinja2 templates support {{ input.* }}, {{ policy_summary }}
    - Validation is strict and fails fast
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import yaml

from capsule.errors import (
    PackInputError,
    PackManifestError,
    PackMissingFileError,
    PackNotFoundError,
    PackTemplateError,
)
from capsule.pack.manifest import PackManifest
from capsule.schema import Policy, load_policy

if TYPE_CHECKING:
    from jinja2 import Template


def _get_jinja2_env() -> Any:
    """Get Jinja2 environment, importing lazily to avoid hard dependency."""
    try:
        from jinja2 import Environment, StrictUndefined

        return Environment(
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )
    except ImportError as e:
        msg = "Jinja2 is required for pack templates. Install with: pip install jinja2"
        raise ImportError(msg) from e


class PackLoader:
    """
    Loads and validates pack structures.

    PackLoader provides methods to:
    - Resolve packs by name from bundled or custom locations
    - Load and validate manifest.yaml
    - Load policy.yaml and merge with user policy
    - Render Jinja2 prompt templates
    - Validate pack structure and inputs

    Attributes:
        pack_path: Absolute path to the pack directory
        manifest: Loaded PackManifest (after load_manifest() is called)

    Example:
        >>> loader = PackLoader.resolve_pack("local-doc-auditor")
        >>> manifest = loader.load_manifest()
        >>> policy = loader.load_policy()
        >>> prompt = loader.render_prompt({"target_directory": "/tmp/docs"})
    """

    # Class-level path to bundled packs directory
    # This is relative to the project root (packs/)
    BUNDLED_PACKS_DIR: ClassVar[Path | None] = None

    def __init__(self, pack_path: Path | str) -> None:
        """
        Initialize with path to pack directory.

        Args:
            pack_path: Path to the pack directory (must exist)

        Raises:
            PackNotFoundError: If the pack directory doesn't exist
        """
        self.pack_path = Path(pack_path).resolve()
        self._manifest: PackManifest | None = None

        if not self.pack_path.exists():
            raise PackNotFoundError(
                pack_name=self.pack_path.name,
                pack_path=str(self.pack_path),
            )

        if not self.pack_path.is_dir():
            raise PackNotFoundError(
                pack_name=self.pack_path.name,
                pack_path=str(self.pack_path),
                message=f"Pack path is not a directory: {self.pack_path}",
            )

    @classmethod
    def _get_bundled_packs_dir(cls) -> Path:
        """Get the path to bundled packs directory."""
        if cls.BUNDLED_PACKS_DIR is not None:
            return cls.BUNDLED_PACKS_DIR

        # Default: packs/ directory at project root (relative to this file)
        # src/capsule/pack/loader.py -> packs/
        module_dir = Path(__file__).resolve().parent
        project_root = module_dir.parent.parent.parent
        return project_root / "packs"

    @classmethod
    def resolve_pack(cls, name: str) -> PackLoader:
        """
        Resolve a pack by name.

        Searches for the pack in the following order:
        1. If name is a path and exists, use it directly
        2. Bundled packs by directory name (exact match)
        3. Bundled packs by directory name (with underscore/hyphen conversion)
        4. Bundled packs by manifest name (searches all manifests)

        Args:
            name: Pack name or path to pack directory

        Returns:
            PackLoader instance for the resolved pack

        Raises:
            PackNotFoundError: If the pack cannot be found
        """
        # Check if name is a path
        name_path = Path(name)
        if name_path.exists() and name_path.is_dir():
            return cls(name_path)

        # Search in bundled packs
        bundled_dir = cls._get_bundled_packs_dir()
        if bundled_dir.exists():
            # Try exact directory match
            pack_dir = bundled_dir / name
            if pack_dir.exists() and pack_dir.is_dir():
                return cls(pack_dir)

            # Try with underscores instead of hyphens
            alt_name = name.replace("-", "_")
            pack_dir = bundled_dir / alt_name
            if pack_dir.exists() and pack_dir.is_dir():
                return cls(pack_dir)

            # Try with hyphens instead of underscores
            alt_name = name.replace("_", "-")
            pack_dir = bundled_dir / alt_name
            if pack_dir.exists() and pack_dir.is_dir():
                return cls(pack_dir)

            # Search by manifest name (slower but more flexible)
            for item in bundled_dir.iterdir():
                if item.is_dir() and (item / "manifest.yaml").exists():
                    try:
                        loader = cls(item)
                        if loader.manifest.name == name:
                            return loader
                    except Exception:
                        continue

        raise PackNotFoundError(
            pack_name=name,
            message=f"Pack '{name}' not found in bundled packs or as a path",
            suggestion="Use `capsule pack list` to see available packs, or provide a path to a pack directory.",
        )

    @classmethod
    def list_bundled_packs(cls) -> list[str]:
        """
        List names of all bundled packs.

        Returns:
            List of pack names (directory names in packs/)
        """
        bundled_dir = cls._get_bundled_packs_dir()
        if not bundled_dir.exists():
            return []

        packs = []
        for item in bundled_dir.iterdir():
            if item.is_dir() and (item / "manifest.yaml").exists():
                packs.append(item.name)

        return sorted(packs)

    @property
    def manifest(self) -> PackManifest:
        """
        Get the loaded manifest.

        Loads the manifest if not already loaded.

        Returns:
            PackManifest instance

        Raises:
            PackManifestError: If manifest is invalid
        """
        if self._manifest is None:
            self._manifest = self.load_manifest()
        return self._manifest

    def load_manifest(self) -> PackManifest:
        """
        Load and validate manifest.yaml.

        Returns:
            PackManifest instance

        Raises:
            PackMissingFileError: If manifest.yaml doesn't exist
            PackManifestError: If manifest is invalid
        """
        manifest_path = self.pack_path / "manifest.yaml"

        if not manifest_path.exists():
            raise PackMissingFileError(
                pack_name=self.pack_path.name,
                pack_path=str(self.pack_path),
                missing_file="manifest.yaml",
            )

        try:
            with manifest_path.open() as f:
                data = yaml.safe_load(f)

            if data is None:
                raise PackManifestError(
                    pack_name=self.pack_path.name,
                    pack_path=str(self.pack_path),
                    validation_error="Empty manifest file",
                )

            return PackManifest.model_validate(data)

        except yaml.YAMLError as e:
            raise PackManifestError(
                pack_name=self.pack_path.name,
                pack_path=str(self.pack_path),
                validation_error=f"Invalid YAML: {e}",
            ) from e

        except ValueError as e:
            raise PackManifestError(
                pack_name=self.pack_path.name,
                pack_path=str(self.pack_path),
                validation_error=str(e),
            ) from e

    def load_policy(self) -> Policy:
        """
        Load policy.yaml from pack.

        Policy is always expected at pack_root/policy.yaml (convention).

        Returns:
            Policy instance

        Raises:
            PackMissingFileError: If policy file doesn't exist
            PackManifestError: If policy is invalid
        """
        policy_path = self.pack_path / "policy.yaml"

        if not policy_path.exists():
            raise PackMissingFileError(
                pack_name=self.manifest.name,
                pack_path=str(self.pack_path),
                missing_file="policy.yaml",
            )

        try:
            return load_policy(policy_path)
        except Exception as e:
            raise PackManifestError(
                pack_name=self.manifest.name,
                pack_path=str(self.pack_path),
                validation_error=f"Invalid policy: {e}",
            ) from e

    def merge_policy(self, user_policy: Policy | None) -> Policy:
        """
        Merge pack policy with user policy.

        User policy completely overrides pack policy (no partial merge).
        If user_policy is None, returns the pack's default policy.

        Args:
            user_policy: Optional user-provided policy override

        Returns:
            Policy to use for execution
        """
        if user_policy is not None:
            return user_policy
        return self.load_policy()

    def render_prompt(self, inputs: dict[str, Any]) -> str:
        """
        Render prompt template with Jinja2.

        Template variables available:
        - {{ input.<name> }} - Input values
        - {{ policy_summary }} - Human-readable policy constraints
        - {{ pack_name }} - Pack name
        - {{ pack_version }} - Pack version

        Args:
            inputs: Input values (after validation)

        Returns:
            Rendered prompt string

        Raises:
            PackMissingFileError: If prompt template doesn't exist
            PackTemplateError: If template rendering fails
        """
        if self.manifest.prompt_template is None:
            raise PackMissingFileError(
                pack_name=self.manifest.name,
                pack_path=str(self.pack_path),
                missing_file="prompt_template (not configured)",
            )

        template_path = self.pack_path / self.manifest.prompt_template

        if not template_path.exists():
            raise PackMissingFileError(
                pack_name=self.manifest.name,
                pack_path=str(self.pack_path),
                missing_file=self.manifest.prompt_template,
            )

        try:
            template_content = template_path.read_text()
            env = _get_jinja2_env()
            template: Template = env.from_string(template_content)

            # Build template context
            context = {
                "input": inputs,
                "policy_summary": self.build_policy_summary(),
                "pack_name": self.manifest.name,
                "pack_version": self.manifest.version,
            }

            return template.render(**context)

        except ImportError:
            raise
        except Exception as e:
            raise PackTemplateError(
                pack_name=self.manifest.name,
                pack_path=str(self.pack_path),
                template_path=self.manifest.prompt_template,
                template_error=str(e),
            ) from e

    def build_policy_summary(self) -> str:
        """
        Build human-readable policy summary for prompt.

        Returns:
            Human-readable policy summary string
        """
        try:
            policy = self.load_policy()
        except Exception:
            return "Policy not available"

        lines = [f"Boundary: {policy.boundary.value}"]

        # Summarize tool policies
        if policy.tools.fs_read.allow_paths:
            lines.append(f"- fs.read: allowed paths = {', '.join(policy.tools.fs_read.allow_paths)}")
        if policy.tools.fs_write.allow_paths:
            lines.append(f"- fs.write: allowed paths = {', '.join(policy.tools.fs_write.allow_paths)}")
        if policy.tools.http_get.allow_domains:
            lines.append(f"- http.get: allowed domains = {', '.join(policy.tools.http_get.allow_domains)}")
        if policy.tools.shell_run.allow_executables:
            lines.append(f"- shell.run: allowed executables = {', '.join(policy.tools.shell_run.allow_executables)}")

        lines.append(f"Global timeout: {policy.global_timeout_seconds}s")
        lines.append(f"Max calls per tool: {policy.max_calls_per_tool}")

        return "\n".join(lines)

    def validate_structure(self) -> list[str]:
        """
        Validate pack structure, return list of errors.

        Checks:
        - manifest.yaml exists and is valid
        - policy.yaml exists
        - prompt_template file exists (if specified)
        - yaml_entry file exists (if specified)

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Check manifest
        manifest_path = self.pack_path / "manifest.yaml"
        if not manifest_path.exists():
            errors.append("manifest.yaml not found")
            return errors  # Can't continue without manifest

        try:
            manifest = self.load_manifest()
        except Exception as e:
            errors.append(f"Invalid manifest: {e}")
            return errors

        # Check policy (convention: policy.yaml at pack root)
        policy_path = self.pack_path / "policy.yaml"
        if not policy_path.exists():
            errors.append("policy.yaml not found")

        # Check prompt template
        if manifest.prompt_template is not None:
            template_path = self.pack_path / manifest.prompt_template
            if not template_path.exists():
                errors.append(f"Prompt template not found: {manifest.prompt_template}")

        # Check yaml entry
        if manifest.yaml_entry is not None:
            yaml_path = self.pack_path / manifest.yaml_entry
            if not yaml_path.exists():
                errors.append(f"YAML entry not found: {manifest.yaml_entry}")

        return errors

    def validate_inputs(self, inputs: dict[str, Any]) -> list[str]:
        """
        Validate inputs against schema.

        Checks:
        - Required inputs are present
        - Input types match schema
        - Enum values are valid
        - Pattern validation passes

        Args:
            inputs: Input values to validate

        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        manifest = self.manifest

        # Check required inputs
        for name, schema in manifest.inputs.items():
            if schema.required and name not in inputs:
                if schema.default is None:
                    errors.append(f"Missing required input: {name}")

        # Validate provided inputs
        for name, value in inputs.items():
            if name not in manifest.inputs:
                errors.append(f"Unknown input: {name}")
                continue

            schema = manifest.inputs[name]
            error = self._validate_input_value(name, value, schema)
            if error:
                errors.append(error)

        return errors

    def _validate_input_value(
        self,
        name: str,
        value: Any,
        schema: Any,
    ) -> str | None:
        """Validate a single input value against its schema."""
        # Type validation
        expected_type = schema.type
        type_valid = self._check_type(value, expected_type)

        if not type_valid:
            return f"Input '{name}' has wrong type: expected {expected_type}, got {type(value).__name__}"

        # Enum validation (for strings)
        if schema.enum is not None and expected_type == "string":
            if value not in schema.enum:
                return f"Input '{name}' value '{value}' not in allowed values: {schema.enum}"

        # Pattern validation (for strings)
        if schema.pattern is not None and expected_type == "string":
            if not re.match(schema.pattern, str(value)):
                return f"Input '{name}' value '{value}' doesn't match pattern: {schema.pattern}"

        # Range validation (for numbers)
        if expected_type in ("integer", "number"):
            if schema.min_value is not None and value < schema.min_value:
                return f"Input '{name}' value {value} is less than minimum {schema.min_value}"
            if schema.max_value is not None and value > schema.max_value:
                return f"Input '{name}' value {value} is greater than maximum {schema.max_value}"

        return None

    def _check_type(self, value: Any, expected_type: str) -> bool:
        """Check if value matches expected type."""
        type_checks = {
            "string": lambda v: isinstance(v, str),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
            "array": lambda v: isinstance(v, list),
            "object": lambda v: isinstance(v, dict),
        }

        check = type_checks.get(expected_type)
        if check is None:
            return True  # Unknown type, allow anything
        return check(value)

    def get_validated_inputs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """
        Validate and return inputs with defaults applied.

        Args:
            inputs: User-provided inputs

        Returns:
            Validated inputs with defaults applied

        Raises:
            PackInputError: If validation fails
        """
        errors = self.validate_inputs(inputs)
        if errors:
            raise PackInputError(
                pack_name=self.manifest.name,
                pack_path=str(self.pack_path),
                validation_error="; ".join(errors),
            )

        # Apply defaults
        result = dict(inputs)
        for name, schema in self.manifest.inputs.items():
            if name not in result and schema.default is not None:
                result[name] = schema.default

        return result

    def get_plan(self) -> Any | None:
        """
        Load plan if yaml_entry exists.

        Returns:
            Plan instance or None if no yaml_entry

        Raises:
            PackMissingFileError: If yaml_entry is specified but file doesn't exist
        """
        if self.manifest.yaml_entry is None:
            return None

        yaml_path = self.pack_path / self.manifest.yaml_entry

        if not yaml_path.exists():
            raise PackMissingFileError(
                pack_name=self.manifest.name,
                pack_path=str(self.pack_path),
                missing_file=self.manifest.yaml_entry,
            )

        # Import here to avoid circular imports
        from capsule.schema import load_plan

        return load_plan(yaml_path)
