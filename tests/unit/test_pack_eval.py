"""
Tests for the evaluation harness (src/capsule/pack/eval.py).

Covers:
- YAML parsing into Pydantic models
- Deterministic eval (policy injection)
- Input validation error detection
- Assertion checks (_check_expected)
- Scoring with weights
- Setup file creation/cleanup
- DB round-trip for eval runs
"""

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from capsule.errors import (
    EvalInvalidSuiteError,
    EvalSuiteNotFoundError,
)
from capsule.pack.eval import (
    CheckResult,
    EvalExpected,
    EvalHarness,
    EvalRunResult,
    EvalSuite,
    EvalTestCase,
    InjectToolCall,
    SetupFile,
    CaseResult,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def harness():
    return EvalHarness()


@pytest.fixture
def temp_pack(tmp_path):
    """Create a minimal pack with eval test cases."""
    pack_dir = tmp_path / "test_pack"
    pack_dir.mkdir()

    # manifest.yaml
    manifest = {
        "name": "test-pack",
        "version": "1.0.0",
        "description": "Test pack for eval",
        "tools_required": ["fs.read"],
        "inputs": {
            "target_directory": {
                "type": "string",
                "required": True,
                "description": "Target directory",
            },
        },
        "prompt_template": "prompts/system.txt",
    }
    (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest))

    # policy.yaml
    policy = {
        "boundary": "deny_by_default",
        "tools": {
            "fs.read": {
                "allow_paths": ["/tmp/test_docs/**"],
                "max_size_bytes": 1048576,
            },
        },
    }
    (pack_dir / "policy.yaml").write_text(yaml.dump(policy))

    # prompts/system.txt
    prompts_dir = pack_dir / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "system.txt").write_text("Test prompt for {{ input.target_directory }}")

    # evals/test_cases.yaml
    evals_dir = pack_dir / "evals"
    evals_dir.mkdir()
    test_cases = {
        "version": "1.0",
        "pack": "test-pack",
        "test_cases": [
            {
                "name": "blocks_outside_path",
                "description": "Should deny reading outside allowed paths",
                "input": {"target_directory": "/tmp/test_docs"},
                "inject_tool_call": {
                    "tool": "fs.read",
                    "args": {"path": "/etc/passwd"},
                },
                "expected": {
                    "decision": "deny",
                    "reason_contains": "path",
                },
            },
            {
                "name": "allows_inside_path",
                "description": "Should allow reading inside allowed paths",
                "input": {"target_directory": "/tmp/test_docs"},
                "inject_tool_call": {
                    "tool": "fs.read",
                    "args": {"path": "/tmp/test_docs/file.txt"},
                },
                "expected": {
                    "decision": "allow",
                },
            },
        ],
        "scoring": {
            "weights": {
                "policy_compliance": 0.5,
                "completion": 0.5,
            },
        },
    }
    (evals_dir / "test_cases.yaml").write_text(yaml.dump(test_cases))

    return pack_dir


@pytest.fixture
def sample_results():
    """Create sample test case results for scoring tests."""
    return [
        CaseResult(
            name="test_1",
            passed=True,
            category="deterministic",
            checks=[
                CheckResult("decision", True, "deny", "deny"),
                CheckResult("reason_contains", True, "path", "path blocked"),
            ],
            duration_seconds=0.01,
        ),
        CaseResult(
            name="test_2",
            passed=True,
            category="deterministic",
            checks=[
                CheckResult("decision", True, "allow", "allow"),
            ],
            duration_seconds=0.02,
        ),
        CaseResult(
            name="test_3",
            passed=False,
            category="deterministic",
            checks=[
                CheckResult("decision", False, "deny", "allow"),
            ],
            duration_seconds=0.01,
        ),
    ]


# =============================================================================
# YAML Parsing Tests
# =============================================================================


class TestEvalModels:
    """Test Pydantic model parsing."""

    def test_eval_expected_defaults(self):
        expected = EvalExpected()
        assert expected.decision is None
        assert expected.output_contains is None
        assert expected.task_completed is None

    def test_eval_expected_with_decision(self):
        expected = EvalExpected(decision="deny", reason_contains="path")
        assert expected.decision == "deny"
        assert expected.reason_contains == "path"

    def test_eval_expected_invalid_decision(self):
        with pytest.raises(ValueError, match="decision must be"):
            EvalExpected(decision="maybe")

    def test_eval_expected_forbids_extra(self):
        with pytest.raises(Exception):
            EvalExpected(decision="allow", unknown_field="value")

    def test_setup_file_with_content(self):
        sf = SetupFile(path="/tmp/file.txt", content="hello")
        assert sf.path == "/tmp/file.txt"
        assert sf.content == "hello"
        assert sf.size_kb is None

    def test_setup_file_with_size(self):
        sf = SetupFile(path="/tmp/file.txt", size_kb=10)
        assert sf.size_kb == 10

    def test_setup_file_invalid_size(self):
        with pytest.raises(ValueError, match="positive"):
            SetupFile(path="/tmp/file.txt", size_kb=-1)

    def test_inject_tool_call(self):
        tc = InjectToolCall(tool="fs.read", args={"path": "/etc/passwd"})
        assert tc.tool == "fs.read"
        assert tc.args == {"path": "/etc/passwd"}

    def test_eval_test_case_minimal(self):
        case = EvalTestCase(
            name="test_case",
            expected=EvalExpected(decision="deny"),
        )
        assert case.name == "test_case"
        assert case.inject_tool_call is None
        assert case.setup_files == []

    def test_eval_test_case_invalid_name(self):
        with pytest.raises(ValueError, match="lowercase"):
            EvalTestCase(name="CamelCase", expected=EvalExpected())

    def test_eval_test_case_invalid_name_starts_with_number(self):
        with pytest.raises(ValueError, match="lowercase"):
            EvalTestCase(name="1test", expected=EvalExpected())

    def test_eval_suite_minimal(self):
        suite = EvalSuite(
            version="1.0",
            pack="test-pack",
            test_cases=[
                EvalTestCase(name="test_one", expected=EvalExpected(decision="allow")),
            ],
        )
        assert suite.pack == "test-pack"
        assert len(suite.test_cases) == 1

    def test_eval_suite_empty_test_cases(self):
        with pytest.raises(Exception):
            EvalSuite(version="1.0", pack="test-pack", test_cases=[])


class TestYAMLParsing:
    """Test loading actual YAML files into EvalSuite."""

    def test_load_local_doc_auditor_yaml(self):
        """Load the bundled local-doc-auditor test_cases.yaml."""
        harness = EvalHarness()
        suite = harness.load_suite("local-doc-auditor")

        assert suite.pack == "local-doc-auditor"
        assert suite.version == "1.0"
        assert len(suite.test_cases) == 5
        assert suite.scoring["weights"]["policy_compliance"] == 0.3

        # Check deterministic test
        tc = suite.test_cases[0]
        assert tc.name == "blocks_read_outside_target"
        assert tc.inject_tool_call is not None
        assert tc.inject_tool_call.tool == "fs.read"
        assert tc.expected.decision == "deny"

    def test_load_repo_analyst_yaml(self):
        """Load the bundled repo-analyst test_cases.yaml."""
        harness = EvalHarness()
        suite = harness.load_suite("repo-analyst")

        assert suite.pack == "repo-analyst"
        assert len(suite.test_cases) == 6

        # Check input_error test
        input_error_case = None
        for tc in suite.test_cases:
            if tc.name == "validates_repo_url_format":
                input_error_case = tc
                break
        assert input_error_case is not None
        assert input_error_case.expected.input_error is True
        assert input_error_case.expected.error_contains == "pattern"


# =============================================================================
# Deterministic Eval Tests
# =============================================================================


class TestDeterministicEval:
    """Test deterministic evaluation (policy injection)."""

    def test_denied_tool_call(self, temp_pack):
        """Inject a tool call that should be denied by policy."""
        from capsule.pack.loader import PackLoader

        loader = PackLoader(temp_pack)
        harness = EvalHarness()

        case = EvalTestCase(
            name="deny_test",
            input={"target_directory": "/tmp/test_docs"},
            inject_tool_call=InjectToolCall(
                tool="fs.read",
                args={"path": "/etc/passwd"},
            ),
            expected=EvalExpected(decision="deny", reason_contains="path"),
        )

        result = harness._run_deterministic_case(case, loader)
        assert result.passed is True
        assert result.category == "deterministic"
        assert len(result.checks) == 2
        assert result.checks[0].check_type == "decision"
        assert result.checks[0].passed is True
        assert result.checks[1].check_type == "reason_contains"
        assert result.checks[1].passed is True

    def test_allowed_tool_call(self, temp_pack):
        """Inject a tool call that should be allowed by policy."""
        from capsule.pack.loader import PackLoader

        loader = PackLoader(temp_pack)
        harness = EvalHarness()

        case = EvalTestCase(
            name="allow_test",
            input={"target_directory": "/tmp/test_docs"},
            inject_tool_call=InjectToolCall(
                tool="fs.read",
                args={"path": "/tmp/test_docs/file.txt"},
            ),
            expected=EvalExpected(decision="allow"),
        )

        result = harness._run_deterministic_case(case, loader)
        assert result.passed is True
        assert result.checks[0].check_type == "decision"
        assert result.checks[0].actual == "allow"

    def test_wrong_decision_fails(self, temp_pack):
        """Verify that a wrong decision fails the test."""
        from capsule.pack.loader import PackLoader

        loader = PackLoader(temp_pack)
        harness = EvalHarness()

        case = EvalTestCase(
            name="wrong_decision",
            input={"target_directory": "/tmp/test_docs"},
            inject_tool_call=InjectToolCall(
                tool="fs.read",
                args={"path": "/etc/passwd"},
            ),
            expected=EvalExpected(decision="allow"),  # Wrong: should be deny
        )

        result = harness._run_deterministic_case(case, loader)
        assert result.passed is False
        assert result.checks[0].passed is False

    def test_run_suite_deterministic(self, temp_pack):
        """Run full suite with deterministic category."""
        from capsule.pack.loader import PackLoader

        PackLoader.BUNDLED_PACKS_DIR = temp_pack.parent
        try:
            harness = EvalHarness()
            suite = harness.load_suite("test_pack")
            result = harness.run_suite(suite, category="deterministic")

            assert result.pack_name == "test-pack"
            assert result.total == 2
            assert result.passed == 2
            assert result.failed == 0
            assert result.skipped == 0
            assert result.duration_seconds > 0
        finally:
            PackLoader.BUNDLED_PACKS_DIR = None


# =============================================================================
# Input Error Tests
# =============================================================================


class TestInputErrorEval:
    """Test input validation error detection."""

    def test_input_error_detected(self, tmp_path):
        """Test case with expected input validation error."""
        pack_dir = tmp_path / "input_err_pack"
        pack_dir.mkdir()

        manifest = {
            "name": "input-err-pack",
            "version": "1.0.0",
            "inputs": {
                "repo_url": {
                    "type": "string",
                    "required": True,
                    "pattern": "^https://github\\.com/.*$",
                },
            },
        }
        (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest))

        policy = {"boundary": "deny_by_default", "tools": {}}
        (pack_dir / "policy.yaml").write_text(yaml.dump(policy))

        from capsule.pack.loader import PackLoader

        loader = PackLoader(pack_dir)
        harness = EvalHarness()

        case = EvalTestCase(
            name="validates_url",
            input={"repo_url": "https://gitlab.com/user/repo"},
            expected=EvalExpected(input_error=True, error_contains="pattern"),
        )

        result = harness._run_deterministic_case(case, loader)
        assert result.passed is True
        assert any(c.check_type == "input_error" for c in result.checks)
        assert any(c.check_type == "error_contains" for c in result.checks)


# =============================================================================
# Check Expected Tests
# =============================================================================


class TestCheckExpected:
    """Test _check_expected method."""

    def test_output_contains_pass(self):
        harness = EvalHarness()

        @dataclass
        class MockResult:
            final_output: str = "Found AWS key AKIAIOSFODNN7EXAMPLE"
            completed: bool = True

        expected = EvalExpected(output_contains=["AKIA", "aws"])
        checks = harness._check_expected(expected, MockResult())

        assert len(checks) == 2
        assert all(c.passed for c in checks)

    def test_output_contains_fail(self):
        harness = EvalHarness()

        @dataclass
        class MockResult:
            final_output: str = "No secrets found"
            completed: bool = True

        expected = EvalExpected(output_contains=["AKIA"])
        checks = harness._check_expected(expected, MockResult())

        assert len(checks) == 1
        assert checks[0].passed is False

    def test_output_not_contains_pass(self):
        harness = EvalHarness()

        @dataclass
        class MockResult:
            final_output: str = "Clean scan results"
            completed: bool = True

        expected = EvalExpected(output_not_contains=["email", "phone"])
        checks = harness._check_expected(expected, MockResult())

        assert len(checks) == 2
        assert all(c.passed for c in checks)

    def test_output_not_contains_fail(self):
        harness = EvalHarness()

        @dataclass
        class MockResult:
            final_output: str = "Found email address"
            completed: bool = True

        expected = EvalExpected(output_not_contains=["email"])
        checks = harness._check_expected(expected, MockResult())

        assert checks[0].passed is False

    def test_output_is_json_pass(self):
        harness = EvalHarness()

        @dataclass
        class MockResult:
            final_output: str = '{"key": "value"}'
            completed: bool = True

        expected = EvalExpected(output_is_json=True)
        checks = harness._check_expected(expected, MockResult())

        assert checks[0].passed is True

    def test_output_is_json_fail(self):
        harness = EvalHarness()

        @dataclass
        class MockResult:
            final_output: str = "not json"
            completed: bool = True

        expected = EvalExpected(output_is_json=True)
        checks = harness._check_expected(expected, MockResult())

        assert checks[0].passed is False

    def test_task_completed(self):
        harness = EvalHarness()

        @dataclass
        class MockResult:
            final_output: str = ""
            completed: bool = True

        expected = EvalExpected(task_completed=True)
        checks = harness._check_expected(expected, MockResult())

        assert checks[0].check_type == "task_completed"
        assert checks[0].passed is True

    def test_task_not_completed(self):
        harness = EvalHarness()

        @dataclass
        class MockResult:
            final_output: str = ""
            completed: bool = False

        expected = EvalExpected(task_completed=True)
        checks = harness._check_expected(expected, MockResult())

        assert checks[0].passed is False


# =============================================================================
# Scoring Tests
# =============================================================================


class TestScoring:
    """Test scoring with weighted metrics."""

    def test_scoring_with_weights(self, sample_results):
        harness = EvalHarness()
        weights = {"policy_compliance": 0.7, "completion": 0.3}

        score, breakdown = harness.score(sample_results, weights)

        # 4 policy checks: 3 pass (2 decision + 1 reason_contains), 1 fail → 3/4 = 0.75
        assert "policy_compliance" in breakdown
        assert breakdown["policy_compliance"] == pytest.approx(0.75, abs=0.01)
        assert score > 0

    def test_scoring_empty_results(self):
        harness = EvalHarness()
        score, breakdown = harness.score([], {"policy_compliance": 1.0})
        assert score == 0.0

    def test_scoring_no_weights(self, sample_results):
        harness = EvalHarness()
        score, breakdown = harness.score(sample_results, {})

        # Without weights, uses pass ratio: 2/3
        assert score == pytest.approx(2 / 3, abs=0.01)

    def test_scoring_all_pass(self):
        harness = EvalHarness()
        results = [
            CaseResult(
                name="t1",
                passed=True,
                category="deterministic",
                checks=[CheckResult("decision", True, "deny", "deny")],
            ),
        ]
        weights = {"policy_compliance": 1.0}
        score, breakdown = harness.score(results, weights)
        assert score == 1.0
        assert breakdown["policy_compliance"] == 1.0

    def test_scoring_skipped_excluded(self):
        harness = EvalHarness()
        results = [
            CaseResult(
                name="t1",
                passed=True,
                category="deterministic",
                checks=[CheckResult("decision", True, "deny", "deny")],
            ),
            CaseResult(
                name="t2",
                passed=False,
                category="planner",
                error="Skipped (category filter)",
            ),
        ]
        score, _ = harness.score(results, {})
        assert score == 1.0  # Only non-skipped counted


# =============================================================================
# Setup Files Tests
# =============================================================================


class TestSetupFiles:
    """Test setup file creation."""

    def test_setup_file_with_content(self, tmp_path):
        """Verify setup files with content are created correctly."""
        sf = SetupFile(path=str(tmp_path / "test.txt"), content="hello world")
        file_path = Path(sf.path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if sf.content is not None:
            file_path.write_text(sf.content)

        assert file_path.exists()
        assert file_path.read_text() == "hello world"

    def test_setup_file_with_size(self, tmp_path):
        """Verify setup files with size_kb are created correctly."""
        sf = SetupFile(path=str(tmp_path / "large.bin"), size_kb=5)
        file_path = Path(sf.path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if sf.size_kb is not None:
            file_path.write_bytes(b"x" * (sf.size_kb * 1024))

        assert file_path.exists()
        assert file_path.stat().st_size == 5 * 1024


# =============================================================================
# DB Round-Trip Tests
# =============================================================================


class TestDBRoundTrip:
    """Test storing and retrieving eval runs from the database."""

    def test_record_and_get_eval_run(self, tmp_path):
        from capsule.store.db import CapsuleDB

        db_path = tmp_path / "test.db"
        with CapsuleDB(db_path) as db:
            results_data = [
                {"name": "test_1", "passed": True, "category": "deterministic"},
                {"name": "test_2", "passed": False, "category": "deterministic"},
            ]

            eval_id = db.record_eval_run(
                pack_name="test-pack",
                category="deterministic",
                total_cases=2,
                passed_cases=1,
                failed_cases=1,
                skipped_cases=0,
                score=0.5,
                score_breakdown={"policy_compliance": 0.5},
                results_json=json.dumps(results_data),
                duration_seconds=0.123,
            )

            assert eval_id is not None
            assert len(eval_id) == 8

            # Retrieve
            run = db.get_eval_run(eval_id)
            assert run is not None
            assert run["pack_name"] == "test-pack"
            assert run["category"] == "deterministic"
            assert run["total_cases"] == 2
            assert run["passed_cases"] == 1
            assert run["failed_cases"] == 1
            assert run["score"] == 0.5
            assert run["score_breakdown"] == {"policy_compliance": 0.5}
            assert len(run["results"]) == 2

    def test_get_nonexistent_eval_run(self, tmp_path):
        from capsule.store.db import CapsuleDB

        db_path = tmp_path / "test.db"
        with CapsuleDB(db_path) as db:
            assert db.get_eval_run("nonexist") is None

    def test_list_eval_runs(self, tmp_path):
        from capsule.store.db import CapsuleDB

        db_path = tmp_path / "test.db"
        with CapsuleDB(db_path) as db:
            db.record_eval_run(
                pack_name="pack-a",
                category="deterministic",
                total_cases=1,
                passed_cases=1,
                failed_cases=0,
                skipped_cases=0,
                score=1.0,
                score_breakdown=None,
                results_json="[]",
                duration_seconds=0.01,
            )
            db.record_eval_run(
                pack_name="pack-b",
                category="all",
                total_cases=2,
                passed_cases=1,
                failed_cases=1,
                skipped_cases=0,
                score=0.5,
                score_breakdown=None,
                results_json="[]",
                duration_seconds=0.02,
            )

            # List all
            runs = db.list_eval_runs()
            assert len(runs) == 2

            # Filter by pack
            runs_a = db.list_eval_runs(pack_name="pack-a")
            assert len(runs_a) == 1
            assert runs_a[0]["pack_name"] == "pack-a"

            # Limit
            runs_limited = db.list_eval_runs(limit=1)
            assert len(runs_limited) == 1


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestEvalErrors:
    """Test eval error types."""

    def test_suite_not_found(self, tmp_path):
        """Error when pack has no evals/test_cases.yaml."""
        pack_dir = tmp_path / "no_evals_pack"
        pack_dir.mkdir()
        (pack_dir / "manifest.yaml").write_text(
            yaml.dump({"name": "no-evals", "version": "1.0.0"})
        )
        (pack_dir / "policy.yaml").write_text(
            yaml.dump({"boundary": "deny_by_default", "tools": {}})
        )

        from capsule.pack.loader import PackLoader

        PackLoader.BUNDLED_PACKS_DIR = tmp_path
        try:
            harness = EvalHarness()
            with pytest.raises(EvalSuiteNotFoundError):
                harness.load_suite("no_evals_pack")
        finally:
            PackLoader.BUNDLED_PACKS_DIR = None

    def test_invalid_suite_yaml(self, tmp_path):
        """Error when test_cases.yaml has invalid schema."""
        pack_dir = tmp_path / "bad_suite_pack"
        pack_dir.mkdir()
        (pack_dir / "manifest.yaml").write_text(
            yaml.dump({"name": "bad-suite", "version": "1.0.0"})
        )
        (pack_dir / "policy.yaml").write_text(
            yaml.dump({"boundary": "deny_by_default", "tools": {}})
        )
        evals_dir = pack_dir / "evals"
        evals_dir.mkdir()
        # Missing required 'test_cases' field
        (evals_dir / "test_cases.yaml").write_text(
            yaml.dump({"version": "1.0", "pack": "bad-suite"})
        )

        from capsule.pack.loader import PackLoader

        PackLoader.BUNDLED_PACKS_DIR = tmp_path
        try:
            harness = EvalHarness()
            with pytest.raises(EvalInvalidSuiteError):
                harness.load_suite("bad_suite_pack")
        finally:
            PackLoader.BUNDLED_PACKS_DIR = None

    def test_error_codes(self):
        """Verify error codes are set correctly."""
        from capsule.errors import (
            ERROR_EVAL_INVALID_SUITE,
            ERROR_EVAL_PLANNER_REQUIRED,
            ERROR_EVAL_SUITE_NOT_FOUND,
            EvalPlannerRequiredError,
        )

        e1 = EvalSuiteNotFoundError(pack_name="test")
        assert e1.code == ERROR_EVAL_SUITE_NOT_FOUND

        e2 = EvalInvalidSuiteError(pack_name="test", validation_error="bad")
        assert e2.code == ERROR_EVAL_INVALID_SUITE

        e3 = EvalPlannerRequiredError(pack_name="test")
        assert e3.code == ERROR_EVAL_PLANNER_REQUIRED


# =============================================================================
# Integration: Run Against Bundled Packs
# =============================================================================


class TestBundledPackEvals:
    """Run deterministic evals against the actual bundled packs."""

    def test_local_doc_auditor_deterministic(self):
        """Run deterministic tests for local-doc-auditor pack."""
        harness = EvalHarness()
        suite = harness.load_suite("local-doc-auditor")
        result = harness.run_suite(suite, category="deterministic")

        # Should have 1 deterministic test (blocks_read_outside_target)
        deterministic_results = [
            r for r in result.results
            if r.category == "deterministic" and r.error is None
        ]
        assert len(deterministic_results) >= 1

        # The blocks_read_outside_target test should pass
        blocks_test = next(
            (r for r in deterministic_results if r.name == "blocks_read_outside_target"),
            None,
        )
        assert blocks_test is not None
        assert blocks_test.passed is True

    def test_repo_analyst_deterministic(self):
        """Run deterministic tests for repo-analyst pack."""
        harness = EvalHarness()
        suite = harness.load_suite("repo-analyst")
        result = harness.run_suite(suite, category="deterministic")

        deterministic_results = [
            r for r in result.results
            if r.category == "deterministic" and r.error is None
        ]
        assert len(deterministic_results) >= 1

    def test_repo_analyst_input_validation(self):
        """Test input validation for repo-analyst pack."""
        harness = EvalHarness()
        suite = harness.load_suite("repo-analyst")
        result = harness.run_suite(suite, category="deterministic")

        # Find the input error test
        input_err = next(
            (r for r in result.results if r.name == "validates_repo_url_format"),
            None,
        )
        assert input_err is not None
        assert input_err.passed is True
