"""
CLI integration tests using typer.testing.CliRunner.

Covers all major CLI commands: run, replay, report, list-runs, show-run,
doctor, pack list/info/validate, eval run/score/list.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from capsule.cli import app

runner = CliRunner()


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def plan_file(temp_dir):
    plan = {
        "version": "1.0",
        "steps": [
            {"tool": "fs.read", "args": {"path": str(temp_dir / "hello.txt")}},
        ],
    }
    (temp_dir / "hello.txt").write_text("hello world")
    plan_path = temp_dir / "plan.yaml"
    plan_path.write_text(yaml.dump(plan))
    return plan_path


@pytest.fixture
def policy_file(temp_dir):
    policy = {
        "boundary": "deny_by_default",
        "tools": {
            "fs.read": {"allow_paths": [str(temp_dir / "**")]},
        },
    }
    policy_path = temp_dir / "policy.yaml"
    policy_path.write_text(yaml.dump(policy))
    return policy_path


@pytest.fixture
def strict_policy_file(temp_dir):
    """Policy that denies everything."""
    policy = {
        "boundary": "deny_by_default",
        "tools": {},
    }
    policy_path = temp_dir / "strict_policy.yaml"
    policy_path.write_text(yaml.dump(policy))
    return policy_path


@pytest.fixture
def db_path(temp_dir):
    return temp_dir / "test.db"


# =============================================================================
# Version & Help
# =============================================================================


class TestVersionAndHelp:
    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.2.0b1" in result.output

    def test_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "run" in result.output
        assert "replay" in result.output
        assert "eval" in result.output

    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        # Typer returns exit code 0 or 2 depending on no_args_is_help config
        assert result.exit_code in (0, 2)
        assert "Usage" in result.output or "usage" in result.output.lower()


# =============================================================================
# capsule run
# =============================================================================


class TestRunCommand:
    def test_run_success(self, plan_file, policy_file, db_path):
        result = runner.invoke(app, [
            "run", str(plan_file),
            "--policy", str(policy_file),
            "--out", str(db_path),
        ])
        assert result.exit_code == 0
        assert "fs.read" in result.output

    def test_run_json_output(self, plan_file, policy_file, db_path):
        result = runner.invoke(app, [
            "run", str(plan_file),
            "--policy", str(policy_file),
            "--out", str(db_path),
            "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "run_id" in data
        assert data["success"] is True

    def test_run_verbose(self, plan_file, policy_file, db_path):
        result = runner.invoke(app, [
            "run", str(plan_file),
            "--policy", str(policy_file),
            "--out", str(db_path),
            "--verbose",
        ])
        assert result.exit_code == 0
        assert "Loaded plan" in result.output

    def test_run_denied_step(self, plan_file, strict_policy_file, db_path):
        result = runner.invoke(app, [
            "run", str(plan_file),
            "--policy", str(strict_policy_file),
            "--out", str(db_path),
        ])
        assert result.exit_code == 1

    def test_run_json_denied(self, plan_file, strict_policy_file, db_path):
        result = runner.invoke(app, [
            "run", str(plan_file),
            "--policy", str(strict_policy_file),
            "--out", str(db_path),
            "--json",
        ])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["success"] is False

    def test_run_invalid_plan_path(self, policy_file, db_path):
        result = runner.invoke(app, [
            "run", "/nonexistent/plan.yaml",
            "--policy", str(policy_file),
            "--out", str(db_path),
        ])
        assert result.exit_code != 0

    def test_run_no_fail_fast(self, temp_dir, strict_policy_file, db_path):
        """With --no-fail-fast, continues after denials."""
        plan = {
            "version": "1.0",
            "steps": [
                {"tool": "fs.read", "args": {"path": "/etc/passwd"}},
                {"tool": "fs.read", "args": {"path": "/etc/hosts"}},
            ],
        }
        plan_path = temp_dir / "multi.yaml"
        plan_path.write_text(yaml.dump(plan))

        result = runner.invoke(app, [
            "run", str(plan_path),
            "--policy", str(strict_policy_file),
            "--out", str(db_path),
            "--no-fail-fast",
        ])
        assert result.exit_code == 1
        # Both steps should appear in output
        assert "denied" in result.output.lower() or "DENIED" in result.output


# =============================================================================
# capsule replay
# =============================================================================


class TestReplayCommand:
    def _run_first(self, plan_file, policy_file, db_path):
        """Helper: execute a run and return the run_id."""
        result = runner.invoke(app, [
            "run", str(plan_file),
            "--policy", str(policy_file),
            "--out", str(db_path),
            "--json",
        ])
        return json.loads(result.output)["run_id"]

    def test_replay_success(self, plan_file, policy_file, db_path):
        run_id = self._run_first(plan_file, policy_file, db_path)
        result = runner.invoke(app, [
            "replay", run_id, "--db", str(db_path),
        ])
        assert result.exit_code == 0

    def test_replay_json(self, plan_file, policy_file, db_path):
        run_id = self._run_first(plan_file, policy_file, db_path)
        result = runner.invoke(app, [
            "replay", run_id, "--db", str(db_path), "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        # Replay JSON uses replay_run_id and original_run_id
        assert "replay_run_id" in data
        assert data["original_run_id"] == run_id

    def test_replay_verify(self, plan_file, policy_file, db_path):
        run_id = self._run_first(plan_file, policy_file, db_path)
        result = runner.invoke(app, [
            "replay", run_id, "--db", str(db_path), "--verify",
        ])
        assert result.exit_code == 0

    def test_replay_nonexistent_run(self, db_path):
        # Create db first
        from capsule.store.db import CapsuleDB
        CapsuleDB(db_path).close()

        result = runner.invoke(app, [
            "replay", "nonexist", "--db", str(db_path),
        ])
        assert result.exit_code == 1

    def test_replay_nonexistent_db(self, temp_dir):
        # --db with exists=True in typer causes exit 2 when file doesn't exist
        result = runner.invoke(app, [
            "replay", "abc123", "--db", str(temp_dir / "nope.db"),
        ])
        assert result.exit_code != 0


# =============================================================================
# capsule report
# =============================================================================


class TestReportCommand:
    def test_report_console(self, plan_file, policy_file, db_path):
        # Run first
        res = runner.invoke(app, [
            "run", str(plan_file), "--policy", str(policy_file),
            "--out", str(db_path), "--json",
        ])
        run_id = json.loads(res.output)["run_id"]

        result = runner.invoke(app, [
            "report", run_id, "--db", str(db_path),
        ])
        assert result.exit_code == 0

    def test_report_json(self, plan_file, policy_file, db_path):
        res = runner.invoke(app, [
            "run", str(plan_file), "--policy", str(policy_file),
            "--out", str(db_path), "--json",
        ])
        run_id = json.loads(res.output)["run_id"]

        result = runner.invoke(app, [
            "report", run_id, "--db", str(db_path), "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "run" in data

    def test_report_nonexistent_run(self, db_path):
        # The report command with console format prints "Run not found" but exits 0
        # because generate_console_report returns None silently
        from capsule.store.db import CapsuleDB
        CapsuleDB(db_path).close()

        result = runner.invoke(app, [
            "report", "nonexist", "--db", str(db_path),
        ])
        assert result.exit_code == 0
        assert "not found" in result.output.lower()


# =============================================================================
# capsule list-runs / show-run
# =============================================================================


class TestListAndShowCommands:
    def test_list_runs_empty(self, db_path):
        from capsule.store.db import CapsuleDB
        CapsuleDB(db_path).close()

        result = runner.invoke(app, ["list-runs", "--db", str(db_path)])
        assert result.exit_code == 0

    def test_list_runs_with_data(self, plan_file, policy_file, db_path):
        runner.invoke(app, [
            "run", str(plan_file), "--policy", str(policy_file),
            "--out", str(db_path),
        ])
        result = runner.invoke(app, ["list-runs", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "completed" in result.output.lower() or "COMPLETED" in result.output

    def test_show_run(self, plan_file, policy_file, db_path):
        res = runner.invoke(app, [
            "run", str(plan_file), "--policy", str(policy_file),
            "--out", str(db_path), "--json",
        ])
        run_id = json.loads(res.output)["run_id"]

        result = runner.invoke(app, ["show-run", run_id, "--db", str(db_path)])
        assert result.exit_code == 0
        assert run_id in result.output

    def test_show_run_nonexistent(self, db_path):
        from capsule.store.db import CapsuleDB
        CapsuleDB(db_path).close()

        result = runner.invoke(app, ["show-run", "nonexist", "--db", str(db_path)])
        assert result.exit_code == 1


# =============================================================================
# capsule doctor
# =============================================================================


class TestDoctorCommand:
    def test_doctor_basic(self):
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "Python" in result.output

    def test_doctor_json(self):
        result = runner.invoke(app, ["doctor", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        # Doctor JSON has "checks" array and "ok" bool
        assert "checks" in data
        assert "ok" in data


# =============================================================================
# capsule pack
# =============================================================================


class TestPackCommands:
    def test_pack_list(self):
        result = runner.invoke(app, ["pack", "list"])
        assert result.exit_code == 0
        assert "local_doc_auditor" in result.output or "Available" in result.output

    def test_pack_list_json(self):
        result = runner.invoke(app, ["pack", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "packs" in data
        assert data["count"] >= 2

    def test_pack_info(self):
        result = runner.invoke(app, ["pack", "info", "local-doc-auditor"])
        assert result.exit_code == 0
        assert "local-doc-auditor" in result.output

    def test_pack_info_json(self):
        result = runner.invoke(app, ["pack", "info", "local-doc-auditor", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "local-doc-auditor"

    def test_pack_info_not_found(self):
        result = runner.invoke(app, ["pack", "info", "nonexistent-pack"])
        assert result.exit_code == 1

    def test_pack_validate(self):
        from capsule.pack.loader import PackLoader
        loader = PackLoader.resolve_pack("local-doc-auditor")
        result = runner.invoke(app, ["pack", "validate", str(loader.pack_path)])
        assert result.exit_code == 0

    def test_pack_validate_json(self):
        from capsule.pack.loader import PackLoader
        loader = PackLoader.resolve_pack("local-doc-auditor")
        result = runner.invoke(app, ["pack", "validate", str(loader.pack_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["valid"] is True


# =============================================================================
# capsule eval
# =============================================================================


class TestEvalCommands:
    def test_eval_run_deterministic(self):
        result = runner.invoke(app, [
            "eval", "run", "local-doc-auditor",
            "--category", "deterministic",
        ])
        assert result.exit_code == 0
        assert "PASS" in result.output

    def test_eval_run_json(self):
        result = runner.invoke(app, [
            "eval", "run", "local-doc-auditor",
            "--category", "deterministic",
            "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["pack_name"] == "local-doc-auditor"
        assert data["passed"] >= 1

    def test_eval_run_with_db(self, db_path):
        result = runner.invoke(app, [
            "eval", "run", "local-doc-auditor",
            "--category", "deterministic",
            "--db", str(db_path),
            "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "eval_id" in data

    def test_eval_list_empty(self, db_path):
        from capsule.store.db import CapsuleDB
        CapsuleDB(db_path).close()

        result = runner.invoke(app, [
            "eval", "list", "--db", str(db_path),
        ])
        assert result.exit_code == 0

    def test_eval_list_with_data(self, db_path):
        # Run an eval first
        runner.invoke(app, [
            "eval", "run", "local-doc-auditor",
            "--category", "deterministic",
            "--db", str(db_path),
        ])
        # Use --json to get the pack name without Rich table truncation
        result = runner.invoke(app, [
            "eval", "list", "--db", str(db_path), "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] >= 1
        assert any("local-doc-auditor" in r["pack_name"] for r in data["eval_runs"])

    def test_eval_list_json(self, db_path):
        runner.invoke(app, [
            "eval", "run", "local-doc-auditor",
            "--category", "deterministic",
            "--db", str(db_path),
        ])
        result = runner.invoke(app, [
            "eval", "list", "--db", str(db_path), "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] >= 1

    def test_eval_score(self, db_path):
        res = runner.invoke(app, [
            "eval", "run", "local-doc-auditor",
            "--category", "deterministic",
            "--db", str(db_path),
            "--json",
        ])
        eval_id = json.loads(res.output)["eval_id"]

        result = runner.invoke(app, [
            "eval", "score", eval_id, "--db", str(db_path),
        ])
        assert result.exit_code == 0
        assert "Score" in result.output

    def test_eval_score_json(self, db_path):
        res = runner.invoke(app, [
            "eval", "run", "local-doc-auditor",
            "--category", "deterministic",
            "--db", str(db_path),
            "--json",
        ])
        eval_id = json.loads(res.output)["eval_id"]

        result = runner.invoke(app, [
            "eval", "score", eval_id, "--db", str(db_path), "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["eval_id"] == eval_id

    def test_eval_score_not_found(self, db_path):
        from capsule.store.db import CapsuleDB
        CapsuleDB(db_path).close()

        result = runner.invoke(app, [
            "eval", "score", "nonexist", "--db", str(db_path),
        ])
        assert result.exit_code == 1

    def test_eval_run_nonexistent_pack(self):
        result = runner.invoke(app, [
            "eval", "run", "nonexistent-pack",
        ])
        assert result.exit_code == 1

    def test_eval_list_with_pack_filter(self, db_path):
        runner.invoke(app, [
            "eval", "run", "local-doc-auditor",
            "--category", "deterministic",
            "--db", str(db_path),
        ])
        result = runner.invoke(app, [
            "eval", "list",
            "--db", str(db_path),
            "--pack", "local-doc-auditor",
            "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert all(r["pack_name"] == "local-doc-auditor" for r in data["eval_runs"])
