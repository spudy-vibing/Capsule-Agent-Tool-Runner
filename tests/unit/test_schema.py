"""
Unit tests for schema validation.

Tests cover:
- Plan/PlanStep parsing and validation
- Policy parsing and validation
- YAML loading helpers
- Edge cases and error handling
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from capsule.schema import (
    FsPolicy,
    HttpPolicy,
    Plan,
    PlanStep,
    Policy,
    PolicyBoundary,
    PolicyDecision,
    Run,
    RunMode,
    RunStatus,
    ShellPolicy,
    ToolCall,
    ToolCallStatus,
    ToolResult,
    load_plan,
    load_plan_from_string,
    load_policy,
    load_policy_from_string,
)


# =============================================================================
# PlanStep Tests
# =============================================================================


class TestPlanStep:
    """Tests for PlanStep model."""

    def test_minimal_step(self) -> None:
        """A step only needs a tool name."""
        step = PlanStep(tool="fs.read")
        assert step.tool == "fs.read"
        assert step.args == {}
        assert step.id is None
        assert step.name is None

    def test_full_step(self) -> None:
        """Step with all fields populated."""
        step = PlanStep(
            tool="fs.read",
            args={"path": "./file.txt"},
            id="step-1",
            name="Read file",
        )
        assert step.tool == "fs.read"
        assert step.args == {"path": "./file.txt"}
        assert step.id == "step-1"
        assert step.name == "Read file"

    def test_empty_tool_rejected(self) -> None:
        """Empty tool name should be rejected."""
        with pytest.raises(ValidationError):
            PlanStep(tool="")

    def test_invalid_tool_format_rejected(self) -> None:
        """Tool names with invalid characters should be rejected."""
        with pytest.raises(ValidationError):
            PlanStep(tool="fs/read")  # slash not allowed

    def test_valid_tool_formats(self) -> None:
        """Various valid tool name formats."""
        assert PlanStep(tool="read").tool == "read"
        assert PlanStep(tool="fs.read").tool == "fs.read"
        assert PlanStep(tool="my_tool.do_thing").tool == "my_tool.do_thing"
        assert PlanStep(tool="a.b.c").tool == "a.b.c"

    def test_step_is_immutable(self) -> None:
        """Steps should be immutable (frozen)."""
        step = PlanStep(tool="fs.read")
        with pytest.raises(ValidationError):
            step.tool = "fs.write"  # type: ignore

    def test_extra_fields_rejected(self) -> None:
        """Unknown fields should be rejected."""
        with pytest.raises(ValidationError):
            PlanStep(tool="fs.read", unknown_field="value")  # type: ignore


# =============================================================================
# Plan Tests
# =============================================================================


class TestPlan:
    """Tests for Plan model."""

    def test_minimal_plan(self) -> None:
        """Plan with just steps."""
        plan = Plan(steps=[PlanStep(tool="fs.read")])
        assert plan.version == "1.0"
        assert len(plan.steps) == 1
        assert plan.name is None
        assert plan.description is None

    def test_full_plan(self) -> None:
        """Plan with all fields."""
        plan = Plan(
            version="1.0",
            name="test-plan",
            description="A test plan",
            steps=[
                PlanStep(tool="fs.read", args={"path": "./a.txt"}),
                PlanStep(tool="fs.read", args={"path": "./b.txt"}),
            ],
        )
        assert plan.name == "test-plan"
        assert plan.description == "A test plan"
        assert len(plan.steps) == 2

    def test_empty_steps_rejected(self) -> None:
        """Plans must have at least one step."""
        with pytest.raises(ValidationError):
            Plan(steps=[])

    def test_plan_is_immutable(self) -> None:
        """Plans should be immutable."""
        plan = Plan(steps=[PlanStep(tool="fs.read")])
        with pytest.raises(ValidationError):
            plan.name = "new-name"  # type: ignore


# =============================================================================
# Policy Tests
# =============================================================================


class TestFsPolicy:
    """Tests for filesystem policy."""

    def test_default_values(self) -> None:
        """Default policy values."""
        policy = FsPolicy()
        assert policy.allow_paths == []
        assert policy.deny_paths == []
        assert policy.max_size_bytes == 10 * 1024 * 1024
        assert policy.allow_hidden is False

    def test_custom_values(self) -> None:
        """Custom policy values."""
        policy = FsPolicy(
            allow_paths=["./**"],
            deny_paths=["./.env"],
            max_size_bytes=1024,
            allow_hidden=True,
        )
        assert policy.allow_paths == ["./**"]
        assert policy.deny_paths == ["./.env"]
        assert policy.max_size_bytes == 1024
        assert policy.allow_hidden is True

    def test_zero_max_size_allowed(self) -> None:
        """max_size_bytes=0 means disabled (valid)."""
        policy = FsPolicy(max_size_bytes=0)
        assert policy.max_size_bytes == 0

    def test_negative_max_size_rejected(self) -> None:
        """max_size_bytes must be non-negative."""
        with pytest.raises(ValidationError):
            FsPolicy(max_size_bytes=-1)


class TestHttpPolicy:
    """Tests for HTTP policy."""

    def test_default_values(self) -> None:
        """Default policy values."""
        policy = HttpPolicy()
        assert policy.allow_domains == []
        assert policy.deny_private_ips is True
        assert policy.max_response_bytes == 10 * 1024 * 1024
        assert policy.timeout_seconds == 30

    def test_custom_values(self) -> None:
        """Custom policy values."""
        policy = HttpPolicy(
            allow_domains=["api.github.com"],
            deny_private_ips=False,
            max_response_bytes=1024,
            timeout_seconds=60,
        )
        assert policy.allow_domains == ["api.github.com"]
        assert policy.deny_private_ips is False

    def test_timeout_limits(self) -> None:
        """Timeout must be within valid range."""
        with pytest.raises(ValidationError):
            HttpPolicy(timeout_seconds=0)
        with pytest.raises(ValidationError):
            HttpPolicy(timeout_seconds=301)


class TestShellPolicy:
    """Tests for shell policy."""

    def test_default_values(self) -> None:
        """Default policy values include deny tokens."""
        policy = ShellPolicy()
        assert policy.allow_executables == []
        assert "sudo" in policy.deny_tokens
        assert policy.timeout_seconds == 60
        assert policy.max_output_bytes == 1024 * 1024

    def test_custom_executables(self) -> None:
        """Custom allowed executables."""
        policy = ShellPolicy(allow_executables=["git", "echo"])
        assert policy.allow_executables == ["git", "echo"]


class TestPolicy:
    """Tests for complete Policy model."""

    def test_default_policy(self) -> None:
        """Default policy is deny-by-default."""
        policy = Policy()
        assert policy.boundary == PolicyBoundary.DENY_BY_DEFAULT
        assert policy.global_timeout_seconds == 300
        assert policy.max_calls_per_tool == 100

    def test_policy_with_tools(self) -> None:
        """Policy with tool configurations."""
        policy = Policy(
            tools={
                "fs.read": FsPolicy(allow_paths=["./**"]),
            }
        )
        assert policy.tools.fs_read.allow_paths == ["./**"]


# =============================================================================
# PolicyDecision Tests
# =============================================================================


class TestPolicyDecision:
    """Tests for PolicyDecision model."""

    def test_allow_decision(self) -> None:
        """Create an allow decision."""
        decision = PolicyDecision.allow("Path matches pattern", "allow_paths[0]")
        assert decision.allowed is True
        assert decision.reason == "Path matches pattern"
        assert decision.rule_matched == "allow_paths[0]"

    def test_deny_decision(self) -> None:
        """Create a deny decision."""
        decision = PolicyDecision.deny("Path blocked", "deny_paths[0]")
        assert decision.allowed is False
        assert decision.reason == "Path blocked"
        assert decision.rule_matched == "deny_paths[0]"

    def test_decision_is_immutable(self) -> None:
        """Decisions should be immutable."""
        decision = PolicyDecision.allow("test")
        with pytest.raises(ValidationError):
            decision.allowed = False  # type: ignore


# =============================================================================
# ToolCall and ToolResult Tests
# =============================================================================


class TestToolCall:
    """Tests for ToolCall model."""

    def test_create_tool_call(self) -> None:
        """Create a tool call record."""
        call = ToolCall(
            call_id="call-1",
            run_id="run-1",
            step_index=0,
            tool_name="fs.read",
            args={"path": "./file.txt"},
        )
        assert call.call_id == "call-1"
        assert call.run_id == "run-1"
        assert call.step_index == 0
        assert call.tool_name == "fs.read"
        assert call.created_at is not None

    def test_negative_step_index_rejected(self) -> None:
        """Step index must be non-negative."""
        with pytest.raises(ValidationError):
            ToolCall(
                call_id="call-1",
                run_id="run-1",
                step_index=-1,
                tool_name="fs.read",
            )


class TestToolResult:
    """Tests for ToolResult model."""

    def test_success_result(self) -> None:
        """Create a successful result."""
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        result = ToolResult(
            call_id="call-1",
            run_id="run-1",
            status=ToolCallStatus.SUCCESS,
            output="file contents",
            policy_decision=PolicyDecision.allow("allowed"),
            started_at=now,
            ended_at=now,
            input_hash="abc123",
            output_hash="def456",
        )
        assert result.status == ToolCallStatus.SUCCESS
        assert result.output == "file contents"
        assert result.error is None

    def test_denied_result(self) -> None:
        """Create a denied result."""
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        result = ToolResult(
            call_id="call-1",
            run_id="run-1",
            status=ToolCallStatus.DENIED,
            policy_decision=PolicyDecision.deny("path blocked"),
            started_at=now,
            ended_at=now,
            input_hash="abc123",
            output_hash="",
        )
        assert result.status == ToolCallStatus.DENIED
        assert result.output is None


# =============================================================================
# Run Tests
# =============================================================================


class TestRun:
    """Tests for Run model."""

    def test_create_run(self) -> None:
        """Create a run record."""
        run = Run(
            run_id="run-1",
            plan_hash="abc123",
            policy_hash="def456",
        )
        assert run.run_id == "run-1"
        assert run.mode == RunMode.RUN
        assert run.status == RunStatus.PENDING
        assert run.total_steps == 0
        assert run.completed_steps == 0

    def test_replay_run(self) -> None:
        """Create a replay run."""
        run = Run(
            run_id="run-2",
            plan_hash="abc123",
            policy_hash="def456",
            mode=RunMode.REPLAY,
        )
        assert run.mode == RunMode.REPLAY


# =============================================================================
# YAML Loading Tests
# =============================================================================


class TestYamlLoading:
    """Tests for YAML loading helpers."""

    def test_load_plan_from_string(self) -> None:
        """Load a plan from YAML string."""
        yaml_content = """
version: "1.0"
steps:
  - tool: fs.read
    args:
      path: "./README.md"
"""
        plan = load_plan_from_string(yaml_content)
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "fs.read"
        assert plan.steps[0].args["path"] == "./README.md"

    def test_load_policy_from_string(self) -> None:
        """Load a policy from YAML string."""
        yaml_content = """
boundary: deny_by_default
tools:
  fs.read:
    allow_paths:
      - "./**"
    max_size_bytes: 1024
"""
        policy = load_policy_from_string(yaml_content)
        assert policy.boundary == PolicyBoundary.DENY_BY_DEFAULT
        assert policy.tools.fs_read.allow_paths == ["./**"]
        assert policy.tools.fs_read.max_size_bytes == 1024

    def test_load_plan_from_file(self, temp_dir: Path) -> None:
        """Load a plan from YAML file."""
        plan_file = temp_dir / "plan.yaml"
        plan_file.write_text("""
version: "1.0"
steps:
  - tool: shell.run
    args:
      cmd: ["echo", "hello"]
""")
        plan = load_plan(plan_file)
        assert plan.steps[0].tool == "shell.run"

    def test_load_policy_from_file(self, temp_dir: Path) -> None:
        """Load a policy from YAML file."""
        policy_file = temp_dir / "policy.yaml"
        policy_file.write_text("""
boundary: deny_by_default
tools:
  shell.run:
    allow_executables:
      - echo
""")
        policy = load_policy(policy_file)
        assert "echo" in policy.tools.shell_run.allow_executables

    def test_load_plan_file_not_found(self) -> None:
        """Loading non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_plan(Path("/nonexistent/plan.yaml"))

    def test_load_plan_invalid_yaml(self, temp_dir: Path) -> None:
        """Loading invalid YAML raises ValidationError."""
        plan_file = temp_dir / "bad.yaml"
        plan_file.write_text("""
version: "1.0"
steps: "not a list"
""")
        with pytest.raises(ValidationError):
            load_plan(plan_file)

    def test_load_plan_missing_required_field(self, temp_dir: Path) -> None:
        """Loading YAML missing required fields raises ValidationError."""
        plan_file = temp_dir / "incomplete.yaml"
        plan_file.write_text("""
version: "1.0"
# missing steps
""")
        with pytest.raises(ValidationError):
            load_plan(plan_file)


# =============================================================================
# Example Files Tests
# =============================================================================


class TestExampleFiles:
    """Test that example files are valid."""

    @pytest.fixture
    def examples_dir(self) -> Path:
        """Path to examples directory."""
        return Path(__file__).parent.parent.parent / "examples"

    def test_load_simple_read_plan(self, examples_dir: Path) -> None:
        """Load simple_read.yaml example."""
        plan = load_plan(examples_dir / "plans" / "simple_read.yaml")
        assert plan.name == "simple-read"
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "fs.read"

    def test_load_multi_step_plan(self, examples_dir: Path) -> None:
        """Load multi_step.yaml example."""
        plan = load_plan(examples_dir / "plans" / "multi_step.yaml")
        assert plan.name == "multi-step-demo"
        assert len(plan.steps) == 4

    def test_load_network_fetch_plan(self, examples_dir: Path) -> None:
        """Load network_fetch.yaml example."""
        plan = load_plan(examples_dir / "plans" / "network_fetch.yaml")
        assert plan.name == "network-fetch"
        assert plan.steps[0].tool == "http.get"

    def test_load_strict_policy(self, examples_dir: Path) -> None:
        """Load strict.yaml policy."""
        policy = load_policy(examples_dir / "policies" / "strict.yaml")
        assert policy.boundary == PolicyBoundary.DENY_BY_DEFAULT
        assert policy.global_timeout_seconds == 60
        assert policy.tools.shell_run.allow_executables == ["echo", "date", "pwd"]

    def test_load_permissive_policy(self, examples_dir: Path) -> None:
        """Load permissive.yaml policy."""
        policy = load_policy(examples_dir / "policies" / "permissive.yaml")
        assert "api.github.com" in policy.tools.http_get.allow_domains
        assert "git" in policy.tools.shell_run.allow_executables

    def test_load_development_policy(self, examples_dir: Path) -> None:
        """Load development.yaml policy."""
        policy = load_policy(examples_dir / "policies" / "development.yaml")
        assert policy.global_timeout_seconds == 180
