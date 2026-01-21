"""
Tests for the Ollama planner adapter.

Tests:
    - OllamaConfig creation and defaults
    - OllamaPlanner initialization
    - propose_next with mocked HTTP
    - Error handling (connection, timeout, parse errors)
    - check_connection
"""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest

from capsule.errors import (
    PlannerConnectionError,
    PlannerInvalidResponseError,
    PlannerModelNotFoundError,
    PlannerParseError,
    PlannerTimeoutError,
)
from capsule.planner.base import Done, PlannerState
from capsule.planner.ollama import DEFAULT_SYSTEM_PROMPT, OllamaConfig, OllamaPlanner
from capsule.schema import PlannerConfig, PolicyDecision, ToolCall, ToolCallStatus, ToolResult


def make_tool_result(
    call_id: str,
    run_id: str,
    status: ToolCallStatus,
    output=None,
    error=None,
) -> ToolResult:
    """Helper to create a ToolResult with all required fields."""
    now = datetime.now(UTC)
    return ToolResult(
        call_id=call_id,
        run_id=run_id,
        status=status,
        output=output,
        error=error,
        policy_decision=PolicyDecision(allowed=status == ToolCallStatus.SUCCESS, reason="test"),
        started_at=now,
        ended_at=now,
        input_hash="test_input_hash",
        output_hash="test_output_hash",
    )


class TestOllamaConfig:
    """Tests for OllamaConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = OllamaConfig()
        assert config.base_url == "http://localhost:11434"
        assert config.model == "qwen2.5:0.5b"
        assert config.timeout_seconds == 30.0
        assert config.max_retries == 3
        assert config.retry_delay_seconds == 1.0
        assert config.temperature == 0.1
        assert config.max_tokens == 1024
        assert config.system_prompt is None

    def test_custom_config(self):
        """Test custom configuration values."""
        config = OllamaConfig(
            base_url="http://192.168.1.100:11434",
            model="llama2:7b",
            timeout_seconds=60.0,
            max_retries=5,
            temperature=0.5,
            max_tokens=2048,
        )
        assert config.base_url == "http://192.168.1.100:11434"
        assert config.model == "llama2:7b"
        assert config.timeout_seconds == 60.0
        assert config.max_retries == 5
        assert config.temperature == 0.5
        assert config.max_tokens == 2048

    def test_from_planner_config(self):
        """Test creating OllamaConfig from PlannerConfig."""
        planner_config = PlannerConfig(
            backend="ollama",
            base_url="http://custom:11434",
            model="custom-model",
            timeout_seconds=45.0,
            temperature=0.3,
        )
        ollama_config = OllamaConfig.from_planner_config(planner_config)
        assert ollama_config.base_url == "http://custom:11434"
        assert ollama_config.model == "custom-model"
        assert ollama_config.timeout_seconds == 45.0
        assert ollama_config.temperature == 0.3


class TestOllamaPlannerInit:
    """Tests for OllamaPlanner initialization."""

    def test_init_with_default_config(self):
        """Test initialization with default config."""
        planner = OllamaPlanner()
        assert planner.config.model == "qwen2.5:0.5b"
        assert planner._client is None

    def test_init_with_ollama_config(self):
        """Test initialization with OllamaConfig."""
        config = OllamaConfig(model="llama2:7b")
        planner = OllamaPlanner(config)
        assert planner.config.model == "llama2:7b"

    def test_init_with_planner_config(self):
        """Test initialization with PlannerConfig."""
        config = PlannerConfig(model="mistral:7b")
        planner = OllamaPlanner(config)
        assert planner.config.model == "mistral:7b"

    def test_context_manager(self):
        """Test context manager protocol."""
        with OllamaPlanner() as planner:
            assert planner is not None
        # Client should be closed after context exit

    def test_get_name(self):
        """Test get_name returns descriptive string."""
        config = OllamaConfig(model="qwen2.5:0.5b")
        planner = OllamaPlanner(config)
        assert planner.get_name() == "OllamaPlanner(qwen2.5:0.5b)"

    def test_get_config(self):
        """Test get_config returns config dict."""
        config = OllamaConfig(model="test-model", temperature=0.5)
        planner = OllamaPlanner(config)
        cfg = planner.get_config()
        assert cfg["backend"] == "ollama"
        assert cfg["model"] == "test-model"
        assert cfg["temperature"] == 0.5


class TestOllamaPlannerProposeNext:
    """Tests for OllamaPlanner.propose_next with mocked HTTP."""

    def _create_mock_response(self, content: str, status_code: int = 200):
        """Create a mock HTTP response."""
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.text = json.dumps({"message": {"content": content}})
        mock_response.json.return_value = {"message": {"content": content}}
        return mock_response

    def _create_state(self, task: str = "Test task") -> PlannerState:
        """Create a test PlannerState."""
        return PlannerState(
            task=task,
            tool_schemas=[
                {
                    "name": "fs.read",
                    "description": "Read a file",
                    "args": {"path": {"type": "string", "required": True}},
                },
            ],
            policy_summary="Can read ./**",
            history=[],
            iteration=0,
        )

    @patch.object(httpx.Client, "post")
    def test_propose_next_returns_tool_call(self, mock_post):
        """Test propose_next returns ToolCall for tool response."""
        mock_post.return_value = self._create_mock_response(
            '{"tool": "fs.read", "args": {"path": "/test/file.txt"}}'
        )

        with OllamaPlanner() as planner:
            state = self._create_state("Read the config file")
            result = planner.propose_next(state, None)

        assert isinstance(result, ToolCall)
        assert result.tool_name == "fs.read"
        assert result.args["path"] == "/test/file.txt"

    @patch.object(httpx.Client, "post")
    def test_propose_next_returns_done(self, mock_post):
        """Test propose_next returns Done for done response."""
        mock_post.return_value = self._create_mock_response(
            '{"done": true, "reason": "task_complete"}'
        )

        with OllamaPlanner() as planner:
            state = self._create_state()
            result = planner.propose_next(state, None)

        assert isinstance(result, Done)
        assert result.reason == "task_complete"

    @patch.object(httpx.Client, "post")
    def test_propose_next_with_history(self, mock_post):
        """Test propose_next includes history in prompt."""
        mock_post.return_value = self._create_mock_response(
            '{"done": true, "reason": "task_complete"}'
        )

        # Create state with history
        call = ToolCall(
            call_id="call-1",
            run_id="run-1",
            step_index=0,
            tool_name="fs.read",
            args={"path": "/test"},
        )
        result = make_tool_result(
            call_id="call-1",
            run_id="run-1",
            status=ToolCallStatus.SUCCESS,
            output="file content",
        )

        with OllamaPlanner() as planner:
            state = PlannerState(
                task="Analyze file",
                tool_schemas=[],
                policy_summary="",
                history=[(call, result)],
                iteration=1,
            )
            planner.propose_next(state, None)

        # Verify the call was made with messages including history
        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]
        messages = payload["messages"]

        # Should have system, user (task), assistant (tool call), user (result)
        assert len(messages) >= 4

    @patch.object(httpx.Client, "post")
    def test_propose_next_extracts_from_markdown(self, mock_post):
        """Test propose_next extracts JSON from markdown."""
        mock_post.return_value = self._create_mock_response(
            """Here's my response:
```json
{"tool": "fs.read", "args": {"path": "/config.yaml"}}
```
Let me know if you need more."""
        )

        with OllamaPlanner() as planner:
            state = self._create_state()
            result = planner.propose_next(state, None)

        assert isinstance(result, ToolCall)
        assert result.tool_name == "fs.read"

    @patch.object(httpx.Client, "post")
    def test_propose_next_repairs_malformed_json(self, mock_post):
        """Test propose_next repairs malformed JSON."""
        mock_post.return_value = self._create_mock_response(
            '{tool: "fs.read", args: {path: "/test"},}'
        )

        with OllamaPlanner() as planner:
            state = self._create_state()
            result = planner.propose_next(state, None)

        assert isinstance(result, ToolCall)
        assert result.tool_name == "fs.read"


class TestOllamaPlannerErrors:
    """Tests for OllamaPlanner error handling."""

    def _create_state(self) -> PlannerState:
        return PlannerState(
            task="Test",
            tool_schemas=[],
            policy_summary="",
            history=[],
            iteration=0,
        )

    @patch.object(httpx.Client, "post")
    def test_connection_error(self, mock_post):
        """Test handling of connection error."""
        mock_post.side_effect = httpx.ConnectError("Connection refused")

        config = OllamaConfig(max_retries=0)  # No retries for faster test
        with OllamaPlanner(config) as planner, pytest.raises(PlannerConnectionError) as exc_info:
            planner.propose_next(self._create_state(), None)

        assert exc_info.value.planner == "ollama"
        assert exc_info.value.model == "qwen2.5:0.5b"

    @patch.object(httpx.Client, "post")
    def test_timeout_error(self, mock_post):
        """Test handling of timeout error."""
        mock_post.side_effect = httpx.TimeoutException("Request timed out")

        config = OllamaConfig(max_retries=0)
        with OllamaPlanner(config) as planner, pytest.raises(PlannerTimeoutError) as exc_info:
            planner.propose_next(self._create_state(), None)

        assert exc_info.value.planner == "ollama"
        assert exc_info.value.timeout_seconds == 30.0

    @patch.object(httpx.Client, "post")
    @patch.object(httpx.Client, "get")
    def test_model_not_found_error(self, mock_get, mock_post):
        """Test handling of model not found error."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "model not found"
        mock_post.return_value = mock_response

        # Mock the list models call
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "llama2:7b"}, {"name": "mistral:7b"}]},
        )

        with OllamaPlanner() as planner, pytest.raises(PlannerModelNotFoundError) as exc_info:
            planner.propose_next(self._create_state(), None)

        assert exc_info.value.model == "qwen2.5:0.5b"
        assert "llama2:7b" in exc_info.value.available_models

    @patch.object(httpx.Client, "post")
    def test_parse_error_invalid_json(self, mock_post):
        """Test handling of unparseable response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"message": {"content": "This is not JSON at all"}}'
        mock_response.json.return_value = {"message": {"content": "This is not JSON at all"}}
        mock_post.return_value = mock_response

        with OllamaPlanner() as planner, pytest.raises(PlannerParseError) as exc_info:
            planner.propose_next(self._create_state(), None)

        assert exc_info.value.planner == "ollama"

    @patch.object(httpx.Client, "post")
    def test_invalid_response_error(self, mock_post):
        """Test handling of invalid tool call structure."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        # Valid JSON but missing required fields
        mock_response.text = '{"message": {"content": "{\\"not_a_tool\\": true}"}}'
        mock_response.json.return_value = {"message": {"content": '{"not_a_tool": true}'}}
        mock_post.return_value = mock_response

        with OllamaPlanner() as planner, pytest.raises(PlannerInvalidResponseError) as exc_info:
            planner.propose_next(self._create_state(), None)

        assert "Missing 'tool' field" in exc_info.value.validation_error

    @patch.object(httpx.Client, "post")
    def test_empty_response_error(self, mock_post):
        """Test handling of empty response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"message": {"content": ""}}'
        mock_response.json.return_value = {"message": {"content": ""}}
        mock_post.return_value = mock_response

        with OllamaPlanner() as planner, pytest.raises(PlannerParseError) as exc_info:
            planner.propose_next(self._create_state(), None)

        assert "Empty response" in exc_info.value.parse_error

    @patch.object(httpx.Client, "post")
    def test_retry_on_connection_error(self, mock_post):
        """Test that connection errors trigger retries."""
        # First two calls fail, third succeeds
        mock_post.side_effect = [
            httpx.ConnectError("Connection refused"),
            httpx.ConnectError("Connection refused"),
            MagicMock(
                status_code=200,
                json=lambda: {"message": {"content": '{"done": true, "reason": "ok"}'}},
            ),
        ]

        config = OllamaConfig(max_retries=3, retry_delay_seconds=0.01)
        with OllamaPlanner(config) as planner:
            result = planner.propose_next(self._create_state(), None)

        assert isinstance(result, Done)
        assert mock_post.call_count == 3


class TestOllamaPlannerCheckConnection:
    """Tests for OllamaPlanner.check_connection."""

    @patch.object(httpx.Client, "get")
    def test_check_connection_success(self, mock_get):
        """Test successful connection check."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "qwen2.5:0.5b"}, {"name": "llama2:7b"}]},
        )

        with OllamaPlanner() as planner:
            ok, message = planner.check_connection()

        assert ok
        assert "Connected" in message
        assert "qwen2.5:0.5b" in message

    @patch.object(httpx.Client, "get")
    def test_check_connection_no_models(self, mock_get):
        """Test connection check with no models available."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": []},
        )

        with OllamaPlanner() as planner:
            ok, message = planner.check_connection()

        assert not ok
        assert "No models available" in message

    @patch.object(httpx.Client, "get")
    def test_check_connection_model_not_found(self, mock_get):
        """Test connection check when specific model not available."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "llama2:7b"}]},
        )

        with OllamaPlanner() as planner:
            ok, message = planner.check_connection()

        assert not ok
        assert "not found" in message

    @patch.object(httpx.Client, "get")
    def test_check_connection_refused(self, mock_get):
        """Test connection check when Ollama not running."""
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        with OllamaPlanner() as planner:
            ok, message = planner.check_connection()

        assert not ok
        assert "Cannot connect" in message

    @patch.object(httpx.Client, "get")
    def test_check_connection_http_error(self, mock_get):
        """Test connection check with HTTP error."""
        mock_get.return_value = MagicMock(status_code=500, text="Internal error")

        with OllamaPlanner() as planner:
            ok, message = planner.check_connection()

        assert not ok
        assert "HTTP 500" in message


class TestOllamaPlannerPromptBuilding:
    """Tests for prompt building internals."""

    def test_format_tool_schemas_empty(self):
        """Test formatting empty tool schemas."""
        planner = OllamaPlanner()
        result = planner._format_tool_schemas([])
        assert result == "No tools available."

    def test_format_tool_schemas_with_tools(self):
        """Test formatting tool schemas."""
        planner = OllamaPlanner()
        schemas = [
            {
                "name": "fs.read",
                "description": "Read a file",
                "args": {
                    "path": {"type": "string", "required": True},
                    "encoding": {"type": "string", "required": False},
                },
            },
        ]
        result = planner._format_tool_schemas(schemas)
        assert "fs.read" in result
        assert "Read a file" in result
        assert "path" in result
        assert "(required)" in result

    def test_summarize_result_success(self):
        """Test summarizing successful result."""
        planner = OllamaPlanner()
        result = make_tool_result(
            call_id="call-1",
            run_id="run-1",
            status=ToolCallStatus.SUCCESS,
            output="file content here",
        )
        summary = planner._summarize_result(result)
        assert "Success" in summary
        assert "file content here" in summary

    def test_summarize_result_success_truncated(self):
        """Test summarizing long successful result."""
        planner = OllamaPlanner()
        result = make_tool_result(
            call_id="call-1",
            run_id="run-1",
            status=ToolCallStatus.SUCCESS,
            output="x" * 1000,
        )
        summary = planner._summarize_result(result)
        assert len(summary) < 600  # Should be truncated
        assert "..." in summary

    def test_summarize_result_denied(self):
        """Test summarizing denied result."""
        planner = OllamaPlanner()
        now = datetime.now(UTC)
        result = ToolResult(
            call_id="call-1",
            run_id="run-1",
            status=ToolCallStatus.DENIED,
            policy_decision=PolicyDecision(allowed=False, reason="Write not allowed"),
            started_at=now,
            ended_at=now,
            input_hash="test",
            output_hash="test",
        )
        summary = planner._summarize_result(result)
        assert "Denied" in summary
        assert "policy" in summary.lower()

    def test_summarize_result_error(self):
        """Test summarizing error result."""
        planner = OllamaPlanner()
        result = make_tool_result(
            call_id="call-1",
            run_id="run-1",
            status=ToolCallStatus.ERROR,
            error="File not found",
        )
        summary = planner._summarize_result(result)
        assert "Error" in summary
        assert "File not found" in summary


class TestDefaultSystemPrompt:
    """Tests for the default system prompt."""

    def test_system_prompt_has_json_instructions(self):
        """Test that system prompt instructs JSON output."""
        assert "JSON" in DEFAULT_SYSTEM_PROMPT
        assert "tool" in DEFAULT_SYSTEM_PROMPT
        assert "done" in DEFAULT_SYSTEM_PROMPT

    def test_system_prompt_has_placeholders(self):
        """Test that system prompt has required placeholders."""
        assert "{tool_schemas}" in DEFAULT_SYSTEM_PROMPT
        assert "{policy_summary}" in DEFAULT_SYSTEM_PROMPT
