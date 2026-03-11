"""
Tests for errors.py coverage gaps:
- Error classes never instantiated in existing tests
- __post_init__ branch coverage
"""

import pytest

from capsule.errors import (
    ERROR_EVAL_INVALID_SUITE,
    ERROR_EVAL_PLANNER_REQUIRED,
    ERROR_EVAL_SUITE_NOT_FOUND,
    ERROR_PACK_TEMPLATE_ERROR,
    ERROR_PACK_TOOL_NOT_AVAILABLE,
    ERROR_PLAN_INVALID_TOOL,
    ERROR_PLAN_MISSING_ARGS,
    ERROR_STORAGE_INTEGRITY,
    ERROR_STORAGE_READ,
    ERROR_TOOL_INVALID_ARGS,
    EvalError,
    EvalInvalidSuiteError,
    EvalPlannerRequiredError,
    EvalSuiteNotFoundError,
    PackTemplateError,
    PackToolNotAvailableError,
    PlanInvalidToolError,
    PlanValidationError,
    StorageIntegrityError,
    StorageReadError,
    ToolInvalidArgsError,
)


class TestToolInvalidArgsError:
    def test_auto_message(self):
        err = ToolInvalidArgsError(tool="fs.read", validation_error="path is required")
        assert err.code == ERROR_TOOL_INVALID_ARGS
        assert "fs.read" in err.message
        assert "path is required" in err.message

    def test_context(self):
        err = ToolInvalidArgsError(tool="fs.read", validation_error="bad type")
        assert err.context["validation_error"] == "bad type"
        assert err.context["tool"] == "fs.read"

    def test_str_format(self):
        err = ToolInvalidArgsError(tool="shell.run", validation_error="cmd required")
        s = str(err)
        assert f"[E{ERROR_TOOL_INVALID_ARGS}]" in s

    def test_custom_message(self):
        err = ToolInvalidArgsError(
            tool="fs.read", validation_error="x", message="Custom msg"
        )
        assert err.message == "Custom msg"


class TestPlanInvalidToolError:
    def test_auto_message(self):
        err = PlanInvalidToolError(tool="unknown.tool")
        assert err.code == ERROR_PLAN_INVALID_TOOL
        assert "unknown.tool" in err.message
        assert err.context["tool"] == "unknown.tool"

    def test_inherits_plan_validation(self):
        err = PlanInvalidToolError(tool="bad.tool", step_index=3, step_id="step_3")
        assert isinstance(err, PlanValidationError)
        assert err.context["step_index"] == 3

    def test_custom_message_preserved(self):
        err = PlanInvalidToolError(tool="x", message="My message")
        assert err.message == "My message"


class TestStorageReadError:
    def test_auto_message(self):
        err = StorageReadError(
            operation="get_run", underlying_error="table not found"
        )
        assert err.code == ERROR_STORAGE_READ
        assert "table not found" in err.message
        assert err.context["underlying_error"] == "table not found"
        assert err.context["operation"] == "get_run"

    def test_to_dict(self):
        err = StorageReadError(operation="query", underlying_error="timeout")
        d = err.to_dict()
        assert d["error_type"] == "StorageReadError"
        assert d["code"] == ERROR_STORAGE_READ


class TestStorageIntegrityError:
    def test_auto_message(self):
        err = StorageIntegrityError(operation="verify")
        assert err.code == ERROR_STORAGE_INTEGRITY
        assert "integrity" in err.message.lower()
        assert err.suggestion is not None
        assert "corrupted" in err.suggestion.lower()

    def test_context(self):
        err = StorageIntegrityError(operation="check_hash")
        assert err.context["operation"] == "check_hash"


class TestPackToolNotAvailableError:
    def test_auto_message(self):
        err = PackToolNotAvailableError(
            pack_name="my-pack",
            tool_name="http.post",
            available_tools=["fs.read", "fs.write", "http.get"],
        )
        assert err.code == ERROR_PACK_TOOL_NOT_AVAILABLE
        assert "http.post" in err.message
        assert "my-pack" in err.message

    def test_suggestion_with_tools(self):
        err = PackToolNotAvailableError(
            pack_name="p",
            tool_name="x",
            available_tools=["fs.read", "shell.run"],
        )
        assert "fs.read" in err.suggestion

    def test_suggestion_without_tools(self):
        err = PackToolNotAvailableError(
            pack_name="p", tool_name="x", available_tools=[]
        )
        assert "registered" in err.suggestion.lower()

    def test_context(self):
        err = PackToolNotAvailableError(
            pack_name="p", tool_name="x",
            available_tools=["a", "b"],
        )
        assert err.context["tool_name"] == "x"
        assert err.context["available_tools"] == ["a", "b"]


class TestPackTemplateError:
    def test_auto_message(self):
        err = PackTemplateError(
            pack_name="my-pack",
            template_path="prompts/system.txt",
            template_error="undefined variable 'foo'",
        )
        assert err.code == ERROR_PACK_TEMPLATE_ERROR
        assert "my-pack" in err.message
        assert "undefined variable" in err.message

    def test_suggestion(self):
        err = PackTemplateError(
            pack_name="p", template_path="t", template_error="e"
        )
        assert "Jinja2" in err.suggestion

    def test_context(self):
        err = PackTemplateError(
            pack_name="p",
            template_path="prompts/sys.txt",
            template_error="missing var",
        )
        assert err.context["template_path"] == "prompts/sys.txt"
        assert err.context["template_error"] == "missing var"


class TestEvalErrors:
    def test_eval_error_base(self):
        err = EvalError(pack_name="test", pack_path="/tmp/test")
        assert err.context["pack_name"] == "test"
        assert err.context["pack_path"] == "/tmp/test"

    def test_suite_not_found(self):
        err = EvalSuiteNotFoundError(pack_name="my-pack")
        assert err.code == ERROR_EVAL_SUITE_NOT_FOUND
        assert "my-pack" in err.message
        assert "evals/test_cases.yaml" in err.suggestion

    def test_invalid_suite(self):
        err = EvalInvalidSuiteError(
            pack_name="my-pack", validation_error="missing test_cases"
        )
        assert err.code == ERROR_EVAL_INVALID_SUITE
        assert "missing test_cases" in err.message
        assert err.context["validation_error"] == "missing test_cases"

    def test_planner_required(self):
        err = EvalPlannerRequiredError(pack_name="my-pack")
        assert err.code == ERROR_EVAL_PLANNER_REQUIRED
        assert "planner" in err.message.lower()
        assert "ollama" in err.suggestion.lower()

    def test_eval_error_hierarchy(self):
        """All eval errors inherit from EvalError and CapsuleError."""
        from capsule.errors import CapsuleError

        err = EvalSuiteNotFoundError(pack_name="test")
        assert isinstance(err, EvalError)
        assert isinstance(err, CapsuleError)
