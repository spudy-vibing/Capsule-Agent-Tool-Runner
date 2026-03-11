"""
Tests for engine.py coverage gaps:
- Global timeout enforcement
- ToolNotFoundError path in _execute_step
- tool.execute() exception handler
"""

import tempfile
import time
from pathlib import Path

import pytest
import yaml

from capsule.engine import Engine
from capsule.schema import RunStatus, ToolCallStatus, load_plan, load_policy


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def db_path(temp_dir):
    return temp_dir / "test.db"


class TestGlobalTimeout:
    def test_global_timeout_stops_execution(self, temp_dir, db_path):
        """Plans exceeding global_timeout_seconds are aborted."""
        # Create a plan with a slow command
        plan_yaml = {
            "version": "1.0",
            "steps": [
                {"tool": "shell.run", "args": {"cmd": ["sleep", "5"]}},
                {"tool": "shell.run", "args": {"cmd": ["echo", "should not run"]}},
            ],
        }
        plan_path = temp_dir / "slow.yaml"
        plan_path.write_text(yaml.dump(plan_yaml))

        # Policy with very short global timeout
        policy_yaml = {
            "boundary": "deny_by_default",
            "tools": {
                "shell.run": {
                    "allow_executables": ["sleep", "echo"],
                    "timeout_seconds": 10,
                },
            },
            "global_timeout_seconds": 1,
        }
        policy_path = temp_dir / "timeout_policy.yaml"
        policy_path.write_text(yaml.dump(policy_yaml))

        plan = load_plan(plan_path)
        policy = load_policy(policy_path)

        with Engine(db_path=db_path, working_dir=temp_dir) as engine:
            result = engine.run(plan, policy, fail_fast=False)

        # Should have timed out
        assert not result.success
        # At least one step should show timeout/error
        error_steps = [s for s in result.steps if s.status == ToolCallStatus.ERROR]
        assert len(error_steps) >= 1


class TestUnknownToolInPlan:
    def test_unknown_tool_denied(self, temp_dir, db_path):
        """A plan referencing an unknown tool gets denied by policy."""
        plan_yaml = {
            "version": "1.0",
            "steps": [
                {"tool": "unknown.tool", "args": {"foo": "bar"}},
            ],
        }
        plan_path = temp_dir / "unknown.yaml"
        plan_path.write_text(yaml.dump(plan_yaml))

        policy_yaml = {
            "boundary": "deny_by_default",
            "tools": {},
        }
        policy_path = temp_dir / "policy.yaml"
        policy_path.write_text(yaml.dump(policy_yaml))

        plan = load_plan(plan_path)
        policy = load_policy(policy_path)

        with Engine(db_path=db_path, working_dir=temp_dir) as engine:
            result = engine.run(plan, policy)

        assert not result.success
        # Step should be denied (unknown tool)
        assert result.steps[0].status == ToolCallStatus.DENIED


class TestToolExecutionFailure:
    def test_file_not_found_error_recorded(self, temp_dir, db_path):
        """fs.read of missing file produces an ERROR step, not a crash."""
        plan_yaml = {
            "version": "1.0",
            "steps": [
                {"tool": "fs.read", "args": {"path": str(temp_dir / "nonexistent.txt")}},
            ],
        }
        plan_path = temp_dir / "missing.yaml"
        plan_path.write_text(yaml.dump(plan_yaml))

        policy_yaml = {
            "boundary": "deny_by_default",
            "tools": {
                "fs.read": {"allow_paths": [str(temp_dir / "**")]},
            },
        }
        policy_path = temp_dir / "policy.yaml"
        policy_path.write_text(yaml.dump(policy_yaml))

        plan = load_plan(plan_path)
        policy = load_policy(policy_path)

        with Engine(db_path=db_path, working_dir=temp_dir) as engine:
            result = engine.run(plan, policy)

        # Error should be recorded, not crash
        assert result.steps[0].status == ToolCallStatus.ERROR

    def test_fail_fast_continues_recording(self, temp_dir, db_path):
        """With fail_fast=False, subsequent steps run after an error."""
        (temp_dir / "good.txt").write_text("good content")

        plan_yaml = {
            "version": "1.0",
            "steps": [
                {"tool": "fs.read", "args": {"path": str(temp_dir / "missing.txt")}},
                {"tool": "fs.read", "args": {"path": str(temp_dir / "good.txt")}},
            ],
        }
        plan_path = temp_dir / "multi.yaml"
        plan_path.write_text(yaml.dump(plan_yaml))

        policy_yaml = {
            "boundary": "deny_by_default",
            "tools": {
                "fs.read": {"allow_paths": [str(temp_dir / "**")]},
            },
        }
        policy_path = temp_dir / "policy.yaml"
        policy_path.write_text(yaml.dump(policy_yaml))

        plan = load_plan(plan_path)
        policy = load_policy(policy_path)

        with Engine(db_path=db_path, working_dir=temp_dir) as engine:
            result = engine.run(plan, policy, fail_fast=False)

        assert len(result.steps) == 2
        assert result.steps[0].status == ToolCallStatus.ERROR
        assert result.steps[1].status == ToolCallStatus.SUCCESS
