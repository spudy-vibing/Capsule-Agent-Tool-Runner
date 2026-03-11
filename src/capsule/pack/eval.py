"""
Evaluation harness for Capsule packs.

This module provides:
- Pydantic models for parsing test case YAML files
- EvalHarness for running deterministic and planner-based evaluations
- Scoring system with weighted metrics

Test cases are loaded from packs/<name>/evals/test_cases.yaml.
Deterministic tests (inject_tool_call) run without an LLM.
Planner tests require an Ollama-backed planner.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from capsule.errors import (
    EvalInvalidSuiteError,
    EvalPlannerRequiredError,
    EvalSuiteNotFoundError,
    PackInputError,
)

if TYPE_CHECKING:
    from capsule.planner.base import Planner


# =============================================================================
# Schema Models
# =============================================================================


class EvalExpected(BaseModel):
    """Expected outcomes for a test case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: str | None = Field(default=None, description="Expected policy decision: allow or deny")
    reason_contains: str | None = Field(
        default=None, description="Substring expected in policy reason"
    )
    output_contains: list[str] | None = Field(
        default=None, description="Substrings expected in output"
    )
    output_not_contains: list[str] | None = Field(
        default=None, description="Substrings that must NOT appear in output"
    )
    output_is_json: bool | None = Field(default=None, description="Output must be valid JSON")
    task_completed: bool | None = Field(default=None, description="Task must complete successfully")
    input_error: bool | None = Field(
        default=None, description="Input validation should raise an error"
    )
    error_contains: str | None = Field(
        default=None, description="Substring expected in error message"
    )

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v: str | None) -> str | None:
        if v is not None and v not in ("allow", "deny"):
            msg = f"decision must be 'allow' or 'deny', got '{v}'"
            raise ValueError(msg)
        return v


class SetupFile(BaseModel):
    """File to create before a test case runs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(..., description="Path where file should be created")
    content: str | None = Field(default=None, description="File content")
    size_kb: int | None = Field(default=None, description="Generate file of this size in KB")

    @field_validator("size_kb")
    @classmethod
    def validate_size_kb(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            msg = "size_kb must be positive"
            raise ValueError(msg)
        return v


class InjectToolCall(BaseModel):
    """Tool call to inject for deterministic policy testing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str = Field(..., description="Tool name (e.g. fs.read)")
    args: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class EvalTestCase(BaseModel):
    """Single evaluation test case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1, description="Test case name")
    description: str = Field(default="", description="Test case description")
    input: dict[str, Any] = Field(default_factory=dict, description="Pack inputs")
    inject_tool_call: InjectToolCall | None = Field(
        default=None, description="Tool call to inject for deterministic testing"
    )
    setup_files: list[SetupFile] = Field(
        default_factory=list, description="Files to create before test"
    )
    expected: EvalExpected = Field(..., description="Expected outcomes")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        import re

        if not re.match(r"^[a-z][a-z0-9_]*$", v):
            msg = f"Test case name must be lowercase alphanumeric with underscores, got '{v}'"
            raise ValueError(msg)
        return v


class EvalSuite(BaseModel):
    """Full evaluation suite loaded from YAML."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(..., description="Suite format version")
    pack: str = Field(..., description="Pack name this suite tests")
    test_cases: list[EvalTestCase] = Field(..., min_length=1, description="Test cases")
    scoring: dict[str, Any] = Field(default_factory=dict, description="Scoring configuration")


# =============================================================================
# Result Dataclasses
# =============================================================================


@dataclass
class CheckResult:
    """Result of a single assertion check."""

    check_type: str
    passed: bool
    expected: str
    actual: str
    message: str = ""


@dataclass
class CaseResult:
    """Result of running a single test case."""

    name: str
    passed: bool
    category: str  # "deterministic" or "planner"
    checks: list[CheckResult] = field(default_factory=list)
    duration_seconds: float = 0.0
    error: str | None = None


@dataclass
class EvalRunResult:
    """Result of running a full evaluation suite."""

    pack_name: str
    total: int
    passed: int
    failed: int
    skipped: int
    results: list[CaseResult] = field(default_factory=list)
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    duration_seconds: float = 0.0


# =============================================================================
# Eval Harness
# =============================================================================


class EvalHarness:
    """
    Evaluation harness for running pack test suites.

    Supports two test categories:
    - deterministic: Tests with inject_tool_call that evaluate policy directly (no LLM)
    - planner: Full agent loop tests that require an Ollama planner
    """

    def load_suite(self, pack_name: str) -> EvalSuite:
        """
        Load evaluation suite from a pack's evals/test_cases.yaml.

        Args:
            pack_name: Pack name or path

        Returns:
            Parsed EvalSuite

        Raises:
            EvalSuiteNotFoundError: If test_cases.yaml doesn't exist
            EvalInvalidSuiteError: If YAML fails validation
        """
        from capsule.pack.loader import PackLoader

        loader = PackLoader.resolve_pack(pack_name)
        suite_path = loader.pack_path / "evals" / "test_cases.yaml"

        if not suite_path.exists():
            raise EvalSuiteNotFoundError(
                pack_name=pack_name,
                pack_path=str(loader.pack_path),
            )

        try:
            with suite_path.open() as f:
                data = yaml.safe_load(f)

            if data is None:
                raise EvalInvalidSuiteError(
                    pack_name=pack_name,
                    pack_path=str(loader.pack_path),
                    validation_error="Empty test suite file",
                )

            return EvalSuite.model_validate(data)

        except yaml.YAMLError as e:
            raise EvalInvalidSuiteError(
                pack_name=pack_name,
                pack_path=str(loader.pack_path),
                validation_error=f"Invalid YAML: {e}",
            ) from e
        except ValueError as e:
            raise EvalInvalidSuiteError(
                pack_name=pack_name,
                pack_path=str(loader.pack_path),
                validation_error=str(e),
            ) from e

    def run_suite(
        self,
        suite: EvalSuite,
        category: str = "all",
        planner: Planner | None = None,
    ) -> EvalRunResult:
        """
        Run all test cases in a suite.

        Args:
            suite: Parsed evaluation suite
            category: "deterministic", "planner", or "all"
            planner: Planner instance (required for planner tests)

        Returns:
            EvalRunResult with all test case results
        """
        from capsule.pack.loader import PackLoader

        start_time = time.monotonic()
        loader = PackLoader.resolve_pack(suite.pack)
        results: list[CaseResult] = []
        passed = 0
        failed = 0
        skipped = 0

        for case in suite.test_cases:
            is_deterministic = case.inject_tool_call is not None or case.expected.input_error is True
            case_category = "deterministic" if is_deterministic else "planner"

            # Filter by category
            if category != "all" and case_category != category:
                skipped += 1
                results.append(
                    CaseResult(
                        name=case.name,
                        passed=False,
                        category=case_category,
                        error="Skipped (category filter)",
                    )
                )
                continue

            if case_category == "deterministic":
                result = self._run_deterministic_case(case, loader)
            elif planner is not None:
                result = self._run_planner_case(case, loader, planner)
            else:
                skipped += 1
                results.append(
                    CaseResult(
                        name=case.name,
                        passed=False,
                        category=case_category,
                        error="Skipped (no planner available)",
                    )
                )
                continue

            results.append(result)
            if result.passed:
                passed += 1
            else:
                failed += 1

        total_duration = time.monotonic() - start_time
        total = passed + failed + skipped

        # Calculate score
        weights = suite.scoring.get("weights", {})
        score, score_breakdown = self.score(results, weights)

        return EvalRunResult(
            pack_name=suite.pack,
            total=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            results=results,
            score=score,
            score_breakdown=score_breakdown,
            duration_seconds=total_duration,
        )

    def _run_deterministic_case(
        self,
        case: EvalTestCase,
        pack_loader: Any,
    ) -> CaseResult:
        """
        Run a deterministic test case (policy injection, no LLM).

        Handles:
        - inject_tool_call: Evaluate policy directly
        - expected.input_error: Validate inputs and expect failure
        """
        start_time = time.monotonic()
        checks: list[CheckResult] = []

        try:
            # Handle input_error test cases
            if case.expected.input_error:
                return self._run_input_error_case(case, pack_loader, start_time)

            # Policy injection test
            if case.inject_tool_call is not None:
                from capsule.policy.engine import PolicyEngine

                policy = pack_loader.load_policy()
                engine = PolicyEngine(policy)

                # Use pack inputs as working_dir context if target_directory is set
                working_dir = case.input.get("target_directory", ".")

                decision = engine.evaluate(
                    case.inject_tool_call.tool,
                    case.inject_tool_call.args,
                    working_dir=working_dir,
                )

                # Check decision
                if case.expected.decision is not None:
                    expected_allowed = case.expected.decision == "allow"
                    checks.append(
                        CheckResult(
                            check_type="decision",
                            passed=decision.allowed == expected_allowed,
                            expected=case.expected.decision,
                            actual="allow" if decision.allowed else "deny",
                            message=f"Policy decision: {decision.reason}",
                        )
                    )

                # Check reason_contains
                if case.expected.reason_contains is not None:
                    reason_lower = decision.reason.lower()
                    contains = case.expected.reason_contains.lower() in reason_lower
                    checks.append(
                        CheckResult(
                            check_type="reason_contains",
                            passed=contains,
                            expected=case.expected.reason_contains,
                            actual=decision.reason,
                            message=f"Reason {'contains' if contains else 'does not contain'} '{case.expected.reason_contains}'",
                        )
                    )

        except Exception as e:
            duration = time.monotonic() - start_time
            return CaseResult(
                name=case.name,
                passed=False,
                category="deterministic",
                checks=checks,
                duration_seconds=duration,
                error=str(e),
            )

        duration = time.monotonic() - start_time
        all_passed = all(c.passed for c in checks) and len(checks) > 0

        return CaseResult(
            name=case.name,
            passed=all_passed,
            category="deterministic",
            checks=checks,
            duration_seconds=duration,
        )

    def _run_input_error_case(
        self,
        case: EvalTestCase,
        pack_loader: Any,
        start_time: float,
    ) -> CaseResult:
        """Run a test case that expects input validation to fail."""
        checks: list[CheckResult] = []

        try:
            pack_loader.get_validated_inputs(case.input)
            # If we get here, validation didn't fail as expected
            checks.append(
                CheckResult(
                    check_type="input_error",
                    passed=False,
                    expected="input validation error",
                    actual="no error",
                    message="Expected input validation to fail but it succeeded",
                )
            )
        except PackInputError as e:
            checks.append(
                CheckResult(
                    check_type="input_error",
                    passed=True,
                    expected="input validation error",
                    actual=str(e),
                    message="Input validation correctly failed",
                )
            )

            # Check error_contains
            if case.expected.error_contains is not None:
                error_str = str(e).lower()
                contains = case.expected.error_contains.lower() in error_str
                checks.append(
                    CheckResult(
                        check_type="error_contains",
                        passed=contains,
                        expected=case.expected.error_contains,
                        actual=str(e),
                        message=f"Error {'contains' if contains else 'does not contain'} '{case.expected.error_contains}'",
                    )
                )

        duration = time.monotonic() - start_time
        all_passed = all(c.passed for c in checks) and len(checks) > 0

        return CaseResult(
            name=case.name,
            passed=all_passed,
            category="deterministic",
            checks=checks,
            duration_seconds=duration,
        )

    def _run_planner_case(
        self,
        case: EvalTestCase,
        pack_loader: Any,
        planner: Planner,
    ) -> CaseResult:
        """
        Run a planner test case (full agent loop).

        Requires an Ollama-backed planner to be available.
        """
        import tempfile

        start_time = time.monotonic()
        checks: list[CheckResult] = []
        created_files: list[Path] = []

        try:
            # Set up temp files
            for setup_file in case.setup_files:
                file_path = Path(setup_file.path)
                file_path.parent.mkdir(parents=True, exist_ok=True)

                if setup_file.content is not None:
                    file_path.write_text(setup_file.content)
                elif setup_file.size_kb is not None:
                    file_path.write_bytes(b"x" * (setup_file.size_kb * 1024))

                created_files.append(file_path)

            # Render prompt and run agent loop
            validated_inputs = pack_loader.get_validated_inputs(case.input)
            prompt = pack_loader.render_prompt(validated_inputs)
            policy = pack_loader.load_policy()

            from capsule.agent.loop import AgentConfig, AgentLoop
            from capsule.policy.engine import PolicyEngine
            from capsule.store.db import CapsuleDB
            from capsule.tools.registry import default_registry

            policy_engine = PolicyEngine(policy)
            config = AgentConfig(max_iterations=10, total_timeout_seconds=120)

            with tempfile.TemporaryDirectory() as tmp_db_dir:
                db_path = Path(tmp_db_dir) / "eval.db"
                with CapsuleDB(db_path) as db:
                    loop = AgentLoop(
                        planner=planner,
                        policy_engine=policy_engine,
                        registry=default_registry(),
                        db=db,
                        config=config,
                    )

                    working_dir = case.input.get("target_directory", ".")
                    result = loop.run(task=prompt, working_dir=working_dir)

            # Check expected outcomes
            checks = self._check_expected(case.expected, result)

        except EvalPlannerRequiredError:
            raise
        except Exception as e:
            duration = time.monotonic() - start_time
            return CaseResult(
                name=case.name,
                passed=False,
                category="planner",
                checks=checks,
                duration_seconds=duration,
                error=str(e),
            )
        finally:
            # Clean up created files
            for file_path in created_files:
                try:
                    file_path.unlink(missing_ok=True)
                except Exception:
                    pass

        duration = time.monotonic() - start_time
        all_passed = all(c.passed for c in checks) and len(checks) > 0

        return CaseResult(
            name=case.name,
            passed=all_passed,
            category="planner",
            checks=checks,
            duration_seconds=duration,
        )

    def _check_expected(self, expected: EvalExpected, result: Any) -> list[CheckResult]:
        """Check an AgentResult against expected outcomes."""
        checks: list[CheckResult] = []

        # Collect all output text from the result
        output_text = ""
        if hasattr(result, "final_output") and result.final_output:
            output_text = str(result.final_output)
        elif hasattr(result, "history"):
            # Gather outputs from tool results
            parts = []
            for _, tool_result in result.history:
                if tool_result.output:
                    parts.append(str(tool_result.output))
            output_text = "\n".join(parts)

        # task_completed
        if expected.task_completed is not None:
            completed = getattr(result, "completed", False)
            checks.append(
                CheckResult(
                    check_type="task_completed",
                    passed=completed == expected.task_completed,
                    expected=str(expected.task_completed),
                    actual=str(completed),
                )
            )

        # output_contains
        if expected.output_contains is not None:
            output_lower = output_text.lower()
            for substring in expected.output_contains:
                contains = substring.lower() in output_lower
                checks.append(
                    CheckResult(
                        check_type="output_contains",
                        passed=contains,
                        expected=substring,
                        actual=output_text[:200],
                        message=f"Output {'contains' if contains else 'does not contain'} '{substring}'",
                    )
                )

        # output_not_contains
        if expected.output_not_contains is not None:
            output_lower = output_text.lower()
            for substring in expected.output_not_contains:
                not_contains = substring.lower() not in output_lower
                checks.append(
                    CheckResult(
                        check_type="output_not_contains",
                        passed=not_contains,
                        expected=f"NOT {substring}",
                        actual=output_text[:200],
                        message=f"Output {'does not contain' if not_contains else 'contains'} '{substring}'",
                    )
                )

        # output_is_json
        if expected.output_is_json is not None and expected.output_is_json:
            import json as json_mod

            try:
                json_mod.loads(output_text)
                is_json = True
            except (json_mod.JSONDecodeError, ValueError):
                is_json = False

            checks.append(
                CheckResult(
                    check_type="output_is_json",
                    passed=is_json,
                    expected="valid JSON",
                    actual="valid JSON" if is_json else "invalid JSON",
                )
            )

        return checks

    def score(
        self,
        results: list[CaseResult],
        weights: dict[str, float],
    ) -> tuple[float, dict[str, float]]:
        """
        Calculate weighted score from test results.

        Args:
            results: List of test case results
            weights: Category weights (e.g. {"policy_compliance": 0.3, ...})

        Returns:
            Tuple of (overall_score, score_breakdown)
        """
        if not results or not weights:
            non_skipped = [r for r in results if r.error != "Skipped (category filter)"
                          and r.error != "Skipped (no planner available)"]
            if non_skipped:
                passed = sum(1 for r in non_skipped if r.passed)
                return passed / len(non_skipped), {}
            return 0.0, {}

        # Categorize checks by type
        check_type_results: dict[str, list[bool]] = {}
        for result in results:
            if result.error and "Skipped" in (result.error or ""):
                continue
            for check in result.checks:
                if check.check_type not in check_type_results:
                    check_type_results[check.check_type] = []
                check_type_results[check.check_type].append(check.passed)

        # Map check types to weight categories
        check_to_weight: dict[str, str] = {
            "decision": "policy_compliance",
            "reason_contains": "policy_compliance",
            "input_error": "policy_compliance",
            "error_contains": "policy_compliance",
            "output_contains": "detection_accuracy",
            "output_not_contains": "detection_accuracy",
            "output_is_json": "output_format",
            "task_completed": "completion",
        }

        # Calculate per-category scores
        category_scores: dict[str, list[bool]] = {}
        for check_type, passes in check_type_results.items():
            category = check_to_weight.get(check_type, "output_quality")
            if category not in category_scores:
                category_scores[category] = []
            category_scores[category].extend(passes)

        # Calculate weighted average
        breakdown: dict[str, float] = {}
        total_weight = 0.0
        weighted_sum = 0.0

        for category, weight in weights.items():
            if category in category_scores:
                passes = category_scores[category]
                ratio = sum(1 for p in passes if p) / len(passes) if passes else 0.0
                breakdown[category] = round(ratio, 3)
                weighted_sum += ratio * weight
                total_weight += weight
            else:
                breakdown[category] = 0.0

        overall = weighted_sum / total_weight if total_weight > 0 else 0.0
        return round(overall, 3), breakdown
