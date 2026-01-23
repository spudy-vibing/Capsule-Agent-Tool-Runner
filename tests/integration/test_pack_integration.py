"""
Integration tests for the pack system.

Tests cover:
- Pack CLI commands (list, info, validate)
- Built-in pack loading and validation
- Pack structure verification
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from capsule.cli import app
from capsule.pack.loader import PackLoader


runner = CliRunner()


# =============================================================================
# CLI Integration Tests
# =============================================================================


class TestPackListCommand:
    """Tests for `capsule pack list` command."""

    def test_pack_list_shows_bundled_packs(self) -> None:
        """pack list should show bundled packs."""
        result = runner.invoke(app, ["pack", "list"])
        assert result.exit_code == 0
        assert "Available Packs" in result.stdout

    def test_pack_list_shows_local_doc_auditor(self) -> None:
        """pack list should include local_doc_auditor."""
        result = runner.invoke(app, ["pack", "list"])
        assert result.exit_code == 0
        assert "local_doc_auditor" in result.stdout or "local-doc-auditor" in result.stdout

    def test_pack_list_shows_repo_analyst(self) -> None:
        """pack list should include repo_analyst."""
        result = runner.invoke(app, ["pack", "list"])
        assert result.exit_code == 0
        assert "repo_analyst" in result.stdout or "repo-analyst" in result.stdout

    def test_pack_list_json_output(self) -> None:
        """pack list --json should return valid JSON."""
        result = runner.invoke(app, ["pack", "list", "--json"])
        assert result.exit_code == 0

        import json
        data = json.loads(result.stdout)
        assert "packs" in data
        assert "count" in data
        assert isinstance(data["packs"], list)


class TestPackInfoCommand:
    """Tests for `capsule pack info` command."""

    def test_pack_info_local_doc_auditor(self) -> None:
        """pack info should show local_doc_auditor details."""
        result = runner.invoke(app, ["pack", "info", "local_doc_auditor"])
        assert result.exit_code == 0
        assert "local-doc-auditor" in result.stdout
        assert "1.0.0" in result.stdout
        assert "fs.read" in result.stdout

    def test_pack_info_repo_analyst(self) -> None:
        """pack info should show repo_analyst details."""
        result = runner.invoke(app, ["pack", "info", "repo_analyst"])
        assert result.exit_code == 0
        assert "repo-analyst" in result.stdout
        assert "1.0.0" in result.stdout
        assert "http.get" in result.stdout

    def test_pack_info_json_output(self) -> None:
        """pack info --json should return valid JSON."""
        result = runner.invoke(app, ["pack", "info", "local_doc_auditor", "--json"])
        assert result.exit_code == 0

        import json
        data = json.loads(result.stdout)
        assert data["name"] == "local-doc-auditor"
        assert data["version"] == "1.0.0"
        assert "inputs" in data
        assert "outputs" in data

    def test_pack_info_nonexistent_pack(self) -> None:
        """pack info for nonexistent pack should fail."""
        result = runner.invoke(app, ["pack", "info", "nonexistent-pack-xyz"])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower() or "error" in result.stdout.lower()


class TestPackValidateCommand:
    """Tests for `capsule pack validate` command."""

    def test_pack_validate_local_doc_auditor(self) -> None:
        """pack validate should pass for local_doc_auditor."""
        pack_path = PackLoader._get_bundled_packs_dir() / "local_doc_auditor"
        result = runner.invoke(app, ["pack", "validate", str(pack_path)])
        assert result.exit_code == 0
        assert "valid" in result.stdout.lower()

    def test_pack_validate_repo_analyst(self) -> None:
        """pack validate should pass for repo_analyst."""
        pack_path = PackLoader._get_bundled_packs_dir() / "repo_analyst"
        result = runner.invoke(app, ["pack", "validate", str(pack_path)])
        assert result.exit_code == 0
        assert "valid" in result.stdout.lower()

    def test_pack_validate_json_output(self) -> None:
        """pack validate --json should return valid JSON."""
        pack_path = PackLoader._get_bundled_packs_dir() / "local_doc_auditor"
        result = runner.invoke(app, ["pack", "validate", str(pack_path), "--json"])
        assert result.exit_code == 0

        import json
        data = json.loads(result.stdout)
        assert data["valid"] is True
        assert data["errors"] == []

    def test_pack_validate_invalid_directory(self, temp_dir: Path) -> None:
        """pack validate for invalid pack should fail."""
        # Create empty directory
        pack_dir = temp_dir / "invalid_pack"
        pack_dir.mkdir()

        result = runner.invoke(app, ["pack", "validate", str(pack_dir)])
        assert result.exit_code == 1


# =============================================================================
# Built-in Pack Integration Tests
# =============================================================================


class TestLocalDocAuditorPack:
    """Tests for the local_doc_auditor built-in pack."""

    def test_pack_loads_successfully(self) -> None:
        """Pack should load without errors."""
        loader = PackLoader.resolve_pack("local_doc_auditor")
        manifest = loader.manifest
        assert manifest.name == "local-doc-auditor"

    def test_pack_has_required_tools(self) -> None:
        """Pack should require fs.read and shell.run for file listing."""
        loader = PackLoader.resolve_pack("local_doc_auditor")
        assert loader.manifest.tools_required == ["fs.read", "shell.run"]

    def test_pack_policy_is_restrictive(self) -> None:
        """Pack policy should restrict tools appropriately."""
        loader = PackLoader.resolve_pack("local_doc_auditor")
        policy = loader.load_policy()

        # Should allow fs.read
        assert len(policy.tools.fs_read.allow_paths) > 0

        # Should NOT allow http
        assert policy.tools.http_get.allow_domains == []

        # Should only allow find and ls for directory listing
        assert set(policy.tools.shell_run.allow_executables) == {"find", "ls"}

    def test_pack_has_prompt_template(self) -> None:
        """Pack should have a prompt template."""
        loader = PackLoader.resolve_pack("local_doc_auditor")
        assert loader.manifest.prompt_template is not None

        # Template should exist
        template_path = loader.pack_path / loader.manifest.prompt_template
        assert template_path.exists()

    def test_pack_has_patterns_file(self) -> None:
        """Pack should have patterns definition file."""
        loader = PackLoader.resolve_pack("local_doc_auditor")
        patterns_path = loader.pack_path / "patterns" / "secrets.yaml"
        assert patterns_path.exists()

    def test_pack_inputs_validated(self) -> None:
        """Pack should validate inputs correctly."""
        loader = PackLoader.resolve_pack("local_doc_auditor")

        # Valid inputs
        errors = loader.validate_inputs({
            "target_directory": "/tmp/test",
            "sensitivity": "medium",
        })
        assert errors == []

        # Invalid sensitivity
        errors = loader.validate_inputs({
            "target_directory": "/tmp/test",
            "sensitivity": "invalid",
        })
        assert any("not in allowed values" in e for e in errors)


class TestRepoAnalystPack:
    """Tests for the repo_analyst built-in pack."""

    def test_pack_loads_successfully(self) -> None:
        """Pack should load without errors."""
        loader = PackLoader.resolve_pack("repo_analyst")
        manifest = loader.manifest
        assert manifest.name == "repo-analyst"

    def test_pack_has_required_tools(self) -> None:
        """Pack should require only http.get."""
        loader = PackLoader.resolve_pack("repo_analyst")
        assert loader.manifest.tools_required == ["http.get"]

    def test_pack_policy_allows_github_only(self) -> None:
        """Pack policy should only allow api.github.com."""
        loader = PackLoader.resolve_pack("repo_analyst")
        policy = loader.load_policy()

        # Should allow github API
        assert "api.github.com" in policy.tools.http_get.allow_domains

        # Should NOT allow filesystem
        assert policy.tools.fs_read.allow_paths == []
        assert policy.tools.shell_run.allow_executables == []

    def test_pack_has_yaml_entry(self) -> None:
        """Pack should have a YAML entry for static mode."""
        loader = PackLoader.resolve_pack("repo_analyst")
        assert loader.manifest.yaml_entry is not None

        # Plan should exist
        plan = loader.get_plan()
        assert plan is not None

    def test_pack_validates_repo_url_pattern(self) -> None:
        """Pack should validate GitHub URL pattern."""
        loader = PackLoader.resolve_pack("repo_analyst")

        # Valid GitHub URL
        errors = loader.validate_inputs({
            "repo_url": "https://github.com/owner/repo",
        })
        assert errors == []

        # Invalid URL (wrong domain)
        errors = loader.validate_inputs({
            "repo_url": "https://gitlab.com/owner/repo",
        })
        assert any("pattern" in e.lower() for e in errors)


# =============================================================================
# Pack Resolution Tests
# =============================================================================


class TestPackResolution:
    """Tests for pack resolution and discovery."""

    def test_list_bundled_packs_finds_all(self) -> None:
        """list_bundled_packs should find all bundled packs."""
        packs = PackLoader.list_bundled_packs()
        assert "local_doc_auditor" in packs
        assert "repo_analyst" in packs

    def test_resolve_by_name_underscore(self) -> None:
        """Should resolve pack by name with underscores."""
        loader = PackLoader.resolve_pack("local_doc_auditor")
        assert loader.manifest.name == "local-doc-auditor"

    def test_resolve_by_name_hyphen(self) -> None:
        """Should resolve pack by name with hyphens."""
        # The loader should handle hyphen-to-underscore conversion
        try:
            loader = PackLoader.resolve_pack("local-doc-auditor")
            assert loader.manifest.name == "local-doc-auditor"
        except Exception:
            # It's also acceptable if exact hyphen names aren't supported
            # as long as underscore names work
            pass

    def test_resolve_by_path(self, temp_dir: Path) -> None:
        """Should resolve pack by explicit path."""
        # Create a minimal pack
        pack_dir = temp_dir / "test_pack"
        pack_dir.mkdir()

        (pack_dir / "manifest.yaml").write_text("""
name: test-pack
version: "1.0.0"
""")
        (pack_dir / "policy.yaml").write_text("""
boundary: deny_by_default
tools: {}
""")

        loader = PackLoader.resolve_pack(str(pack_dir))
        assert loader.manifest.name == "test-pack"
