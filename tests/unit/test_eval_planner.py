"""
Tests for eval planner case (_run_planner_case) with mocked planner.
Also covers _check_expected history-based output collection.
"""

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from capsule.pack.eval import (
    CaseResult,
    CheckResult,
    EvalExpected,
    EvalHarness,
    EvalTestCase,
    InjectToolCall,
    SetupFile,
)


@pytest.fixture
def harness():
    return EvalHarness()


class TestCheckExpectedWithHistory:
    """Test _check_expected when result uses history instead of final_output."""

    def test_output_from_history(self, harness):
        """When final_output is None, output is gathered from history."""

        @dataclass
        class MockToolResult:
            output: str = ""

        @dataclass
        class MockToolCall:
            tool_name: str = ""

        @dataclass
        class MockResult:
            final_output: str = ""
            completed: bool = True
            history: list = field(default_factory=list)

        result = MockResult(
            final_output="",
            completed=True,
            history=[
                (MockToolCall("fs.read"), MockToolResult("Found AKIA key")),
                (MockToolCall("fs.read"), MockToolResult("Found github token")),
            ],
        )

        expected = EvalExpected(output_contains=["AKIA", "github"])
        checks = harness._check_expected(expected, result)

        assert len(checks) == 2
        assert all(c.passed for c in checks)

    def test_empty_history_no_crash(self, harness):
        """Empty history doesn't crash."""

        @dataclass
        class MockResult:
            final_output: str = ""
            completed: bool = False
            history: list = field(default_factory=list)

        expected = EvalExpected(task_completed=False)
        checks = harness._check_expected(expected, MockResult())
        assert checks[0].passed is True


class TestRunPlannerCaseSetupFiles:
    """Test setup file creation and cleanup in _run_planner_case."""

    def test_setup_files_created_and_cleaned(self, tmp_path):
        """Verify setup files are created before test and cleaned after."""
        harness = EvalHarness()

        # Create minimal pack
        pack_dir = tmp_path / "test_pack"
        pack_dir.mkdir()
        manifest = {
            "name": "test-pack",
            "version": "1.0.0",
            "inputs": {
                "target_directory": {"type": "string", "required": True},
            },
            "prompt_template": "prompts/system.txt",
        }
        (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest))
        (pack_dir / "policy.yaml").write_text(
            yaml.dump({"boundary": "deny_by_default", "tools": {}})
        )
        prompts = pack_dir / "prompts"
        prompts.mkdir()
        (prompts / "system.txt").write_text("Analyze {{ input.target_directory }}")

        from capsule.pack.loader import PackLoader
        loader = PackLoader(pack_dir)

        setup_dir = tmp_path / "setup_test"
        setup_file_path = setup_dir / "test_file.txt"

        case = EvalTestCase(
            name="setup_test",
            input={"target_directory": str(setup_dir)},
            setup_files=[
                SetupFile(path=str(setup_file_path), content="secret data"),
            ],
            expected=EvalExpected(task_completed=True),
        )

        # Mock the agent loop to avoid needing Ollama
        mock_result = MagicMock()
        mock_result.final_output = "Found secret"
        mock_result.completed = True

        with patch("capsule.agent.loop.AgentLoop") as mock_loop_cls, \
             patch("capsule.store.db.CapsuleDB") as mock_db_cls, \
             patch("capsule.policy.engine.PolicyEngine"), \
             patch("capsule.tools.registry.default_registry"):
            mock_loop = MagicMock()
            mock_loop.run.return_value = mock_result
            mock_loop_cls.return_value = mock_loop

            # Mock CapsuleDB as context manager
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db_cls.return_value = mock_db

            mock_planner = MagicMock()
            result = harness._run_planner_case(case, loader, mock_planner)

        assert result.category == "planner"
        # File should have been cleaned up
        assert not setup_file_path.exists()

    def test_setup_file_size_kb(self, tmp_path):
        """Setup files with size_kb create files of correct size."""
        harness = EvalHarness()

        pack_dir = tmp_path / "size_pack"
        pack_dir.mkdir()
        manifest = {
            "name": "size-pack",
            "version": "1.0.0",
            "inputs": {
                "target_directory": {"type": "string", "required": True},
            },
            "prompt_template": "prompts/system.txt",
        }
        (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest))
        (pack_dir / "policy.yaml").write_text(
            yaml.dump({"boundary": "deny_by_default", "tools": {}})
        )
        prompts = pack_dir / "prompts"
        prompts.mkdir()
        (prompts / "system.txt").write_text("Check {{ input.target_directory }}")

        from capsule.pack.loader import PackLoader
        loader = PackLoader(pack_dir)

        setup_dir = tmp_path / "size_test"
        large_file = setup_dir / "large.bin"

        case = EvalTestCase(
            name="size_test",
            input={"target_directory": str(setup_dir)},
            setup_files=[
                SetupFile(path=str(large_file), size_kb=5),
            ],
            expected=EvalExpected(task_completed=True),
        )

        mock_result = MagicMock()
        mock_result.final_output = "skipped"
        mock_result.completed = True

        with patch("capsule.agent.loop.AgentLoop") as mock_loop_cls, \
             patch("capsule.store.db.CapsuleDB") as mock_db_cls, \
             patch("capsule.policy.engine.PolicyEngine"), \
             patch("capsule.tools.registry.default_registry"):
            mock_loop = MagicMock()
            mock_loop_cls.return_value = mock_loop

            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db_cls.return_value = mock_db

            # Verify the file is created during execution
            def check_file_exists(*args, **kwargs):
                assert large_file.exists()
                assert large_file.stat().st_size == 5 * 1024
                return mock_result

            mock_loop.run.side_effect = check_file_exists

            mock_planner = MagicMock()
            result = harness._run_planner_case(case, loader, mock_planner)

        assert result.category == "planner"


class TestRunPlannerCaseError:
    """Test _run_planner_case error handling."""

    def test_planner_case_exception_recorded(self, tmp_path):
        """Exceptions during planner case are recorded, not raised."""
        harness = EvalHarness()

        pack_dir = tmp_path / "err_pack"
        pack_dir.mkdir()
        manifest = {
            "name": "err-pack",
            "version": "1.0.0",
            "inputs": {
                "target_directory": {"type": "string", "required": True},
            },
            "prompt_template": "prompts/system.txt",
        }
        (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest))
        (pack_dir / "policy.yaml").write_text(
            yaml.dump({"boundary": "deny_by_default", "tools": {}})
        )
        prompts = pack_dir / "prompts"
        prompts.mkdir()
        (prompts / "system.txt").write_text("Do {{ input.target_directory }}")

        from capsule.pack.loader import PackLoader
        loader = PackLoader(pack_dir)

        case = EvalTestCase(
            name="error_test",
            input={"target_directory": "/tmp/test"},
            expected=EvalExpected(task_completed=True),
        )

        with patch("capsule.agent.loop.AgentLoop") as mock_loop_cls, \
             patch("capsule.store.db.CapsuleDB") as mock_db_cls, \
             patch("capsule.policy.engine.PolicyEngine"), \
             patch("capsule.tools.registry.default_registry"):
            mock_loop = MagicMock()
            mock_loop.run.side_effect = RuntimeError("Planner crashed")
            mock_loop_cls.return_value = mock_loop

            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db_cls.return_value = mock_db

            mock_planner = MagicMock()
            result = harness._run_planner_case(case, loader, mock_planner)

        assert result.passed is False
        assert result.error is not None
        assert "Planner crashed" in result.error


class TestSuiteSkipPlanner:
    """Test that planner tests are skipped when no planner is available."""

    def test_planner_tests_skipped_without_planner(self, tmp_path):
        """Planner test cases are skipped when planner=None."""
        harness = EvalHarness()

        pack_dir = tmp_path / "skip_pack"
        pack_dir.mkdir()
        manifest = {
            "name": "skip-pack",
            "version": "1.0.0",
            "inputs": {"target_directory": {"type": "string", "required": True}},
            "prompt_template": "prompts/system.txt",
        }
        (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest))
        (pack_dir / "policy.yaml").write_text(
            yaml.dump({"boundary": "deny_by_default", "tools": {}})
        )
        prompts = pack_dir / "prompts"
        prompts.mkdir()
        (prompts / "system.txt").write_text("Test")

        evals_dir = pack_dir / "evals"
        evals_dir.mkdir()
        suite_yaml = {
            "version": "1.0",
            "pack": "skip-pack",
            "test_cases": [
                {
                    "name": "planner_test",
                    "input": {"target_directory": "/tmp/test"},
                    "expected": {"task_completed": True},
                },
            ],
        }
        (evals_dir / "test_cases.yaml").write_text(yaml.dump(suite_yaml))

        from capsule.pack.loader import PackLoader
        PackLoader.BUNDLED_PACKS_DIR = tmp_path
        try:
            suite = harness.load_suite("skip_pack")
            result = harness.run_suite(suite, category="all", planner=None)

            assert result.skipped == 1
            assert result.passed == 0
            assert result.failed == 0
            assert "Skipped" in result.results[0].error
        finally:
            PackLoader.BUNDLED_PACKS_DIR = None
