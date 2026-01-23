"""
Ollama planner adapter.

This module implements the Planner interface using Ollama as the backend.
Ollama runs local LLMs and provides a simple HTTP API for completions.

Requirements:
    - Ollama must be installed and running (`ollama serve`)
    - A model must be pulled (`ollama pull qwen2.5:0.5b`)

Usage:
    from capsule.planner.ollama import OllamaPlanner
    from capsule.schema import PlannerConfig

    config = PlannerConfig(model="qwen2.5:0.5b")
    planner = OllamaPlanner(config)

    result = planner.propose_next(state, last_result=None)
"""

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from capsule.errors import (
    PlannerConnectionError,
    PlannerInvalidResponseError,
    PlannerModelNotFoundError,
    PlannerParseError,
    PlannerTimeoutError,
)
from capsule.planner.base import Done, Planner, PlannerState
from capsule.planner.json_repair import parse_json_safely, validate_tool_call_json
from capsule.schema import PlannerConfig, PlannerProposal, ToolCall, ToolResult

# Default system prompt for tool-calling SLMs
# Note: Double braces {{ and }} are escape sequences for literal braces in .format()
DEFAULT_SYSTEM_PROMPT = """You are a helpful assistant that completes tasks by calling tools.

IMPORTANT RULES:
1. You must respond with ONLY a JSON object, no other text
2. To call a tool, respond with: {{"tool": "<tool_name>", "args": {{...}}}}
3. When the task is complete, respond with: {{"done": true, "reason": "task_complete"}}
4. If you cannot proceed, respond with: {{"done": true, "reason": "cannot_proceed"}}

Available tools:
{tool_schemas}

Policy constraints:
{policy_summary}

Remember: Respond with ONLY valid JSON. No explanations, no markdown, just JSON."""


@dataclass
class OllamaConfig:
    """
    Configuration specific to Ollama adapter.

    This extends PlannerConfig with Ollama-specific settings.
    """

    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:0.5b"
    timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    temperature: float = 0.1
    max_tokens: int = 1024
    system_prompt: str | None = None

    @classmethod
    def from_planner_config(cls, config: PlannerConfig) -> "OllamaConfig":
        """Create OllamaConfig from generic PlannerConfig."""
        return cls(
            base_url=config.base_url,
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
            retry_delay_seconds=config.retry_delay_seconds,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )


class OllamaPlanner(Planner):
    """
    Planner implementation using Ollama.

    This planner connects to a local Ollama instance to generate
    tool call proposals using small language models.

    Features:
        - Automatic retry on transient failures
        - JSON repair for malformed SLM output
        - Structured prompts for reliable tool calling

    Example:
        config = PlannerConfig(model="qwen2.5:0.5b")
        planner = OllamaPlanner(config)

        state = PlannerState(
            task="List files in current directory",
            tool_schemas=[...],
            policy_summary="Can read ./**",
            history=[],
            iteration=0,
        )

        result = planner.propose_next(state, last_result=None)
    """

    def __init__(self, config: PlannerConfig | OllamaConfig | None = None):
        """
        Initialize the Ollama planner.

        Args:
            config: Configuration for the planner. If None, uses defaults.
        """
        if config is None:
            self.config = OllamaConfig()
        elif isinstance(config, OllamaConfig):
            self.config = config
        else:
            self.config = OllamaConfig.from_planner_config(config)

        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.config.base_url,
                timeout=self.config.timeout_seconds,
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "OllamaPlanner":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def propose_next(
        self,
        state: PlannerState,
        last_result: ToolResult | None,
    ) -> ToolCall | Done:
        """
        Propose the next tool call using Ollama.

        Builds a prompt from the state, sends it to Ollama, and parses
        the response into either a ToolCall or Done signal.

        Args:
            state: Current planner state
            last_result: Result of previous tool call, or None

        Returns:
            ToolCall or Done

        Raises:
            PlannerConnectionError: Cannot connect to Ollama
            PlannerTimeoutError: Request timed out
            PlannerParseError: Cannot parse response
            PlannerModelNotFoundError: Model not available
        """
        # Build the prompt
        prompt = self._build_prompt(state, last_result)

        # Call Ollama with retries
        response_text = self._call_ollama_with_retries(prompt)

        # Parse and validate the response
        return self._parse_response(response_text, state.iteration)

    def _build_prompt(
        self,
        state: PlannerState,
        last_result: ToolResult | None,
    ) -> list[dict[str, str]]:
        """Build the message list for Ollama."""
        messages = []

        # System message with tool schemas and policy
        # Use safe string replacement instead of .format() to avoid issues
        # with braces in pack prompts (e.g., regex patterns like {16})
        system_template = self.config.system_prompt or DEFAULT_SYSTEM_PROMPT
        tool_schemas_str = self._format_tool_schemas(state.tool_schemas)
        system_content = system_template.replace(
            "{tool_schemas}", tool_schemas_str
        ).replace("{policy_summary}", state.policy_summary)
        messages.append({"role": "system", "content": system_content})

        # User's task
        messages.append({"role": "user", "content": f"Task: {state.task}"})

        # History of previous calls and results
        for tool_call, tool_result in state.history:
            # Assistant's tool call
            messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "tool": tool_call.tool_name,
                            "args": tool_call.args,
                        }
                    ),
                }
            )

            # Tool result
            result_summary = self._summarize_result(tool_result)
            messages.append(
                {
                    "role": "user",
                    "content": f"Tool result: {result_summary}",
                }
            )

        # If there's a last_result not in history, add it
        if last_result and (not state.history or state.history[-1][1] != last_result):
            result_summary = self._summarize_result(last_result)
            messages.append(
                {
                    "role": "user",
                    "content": f"Tool result: {result_summary}",
                }
            )

        return messages

    def _format_tool_schemas(self, schemas: list[dict[str, Any]]) -> str:
        """Format tool schemas for the prompt."""
        if not schemas:
            return "No tools available."

        lines = []
        for schema in schemas:
            name = schema.get("name", "unknown")
            desc = schema.get("description", "No description")
            args = schema.get("args", {})

            lines.append(f"- {name}: {desc}")
            if args:
                for arg_name, arg_info in args.items():
                    arg_type = arg_info.get("type", "any")
                    required = arg_info.get("required", False)
                    req_str = " (required)" if required else ""
                    lines.append(f"    - {arg_name}: {arg_type}{req_str}")

        return "\n".join(lines)

    def _summarize_result(self, result: ToolResult) -> str:
        """Summarize a tool result for the prompt."""
        if result.status.value == "success":
            output = result.output
            if isinstance(output, dict):
                output = json.dumps(output)
            # Truncate long outputs
            if output and len(str(output)) > 500:
                output = str(output)[:500] + "..."
            return f"Success: {output}"
        elif result.status.value == "denied":
            return f"Denied by policy: {result.policy_decision}"
        else:
            return f"Error: {result.error}"

    def _call_ollama_with_retries(self, messages: list[dict[str, str]]) -> str:
        """Call Ollama API with retry logic."""
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            try:
                return self._call_ollama(messages)
            except PlannerConnectionError as e:
                last_error = e
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_delay_seconds)
            except PlannerTimeoutError as e:
                last_error = e
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_delay_seconds)
            except PlannerModelNotFoundError:
                # Don't retry model not found errors
                raise

        # All retries exhausted
        if last_error:
            raise last_error
        raise PlannerConnectionError(
            planner="ollama",
            model=self.config.model,
            url=self.config.base_url,
        )

    def _call_ollama(self, messages: list[dict[str, str]]) -> str:
        """Make a single call to Ollama API."""
        client = self._get_client()

        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }

        try:
            response = client.post("/api/chat", json=payload)
        except httpx.ConnectError as e:
            raise PlannerConnectionError(
                planner="ollama",
                model=self.config.model,
                url=self.config.base_url,
                underlying_error=str(e),
            ) from e
        except httpx.TimeoutException as e:
            raise PlannerTimeoutError(
                planner="ollama",
                model=self.config.model,
                timeout_seconds=self.config.timeout_seconds,
            ) from e

        if response.status_code == 404:
            # Model not found
            available = self._list_models()
            raise PlannerModelNotFoundError(
                planner="ollama",
                model=self.config.model,
                available_models=available,
            )

        if response.status_code != 200:
            raise PlannerConnectionError(
                planner="ollama",
                model=self.config.model,
                url=self.config.base_url,
                underlying_error=f"HTTP {response.status_code}: {response.text}",
            )

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise PlannerParseError(
                planner="ollama",
                model=self.config.model,
                raw_response=response.text[:500],
                parse_error=f"Invalid JSON from Ollama: {e}",
            ) from e

        # Extract the assistant's message
        message = data.get("message", {})
        content: str = message.get("content", "")

        if not content:
            raise PlannerParseError(
                planner="ollama",
                model=self.config.model,
                raw_response=str(data)[:500],
                parse_error="Empty response from model",
            )

        return content

    def _list_models(self) -> list[str]:
        """List available models from Ollama."""
        try:
            client = self._get_client()
            response = client.get("/api/tags")
            if response.status_code == 200:
                data = response.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        return []

    def _parse_response(
        self,
        response_text: str,
        iteration: int,
    ) -> ToolCall | Done:
        """Parse Ollama response into ToolCall or Done."""
        # Use json_repair to parse
        parsed, error = parse_json_safely(response_text)

        if error:
            raise PlannerParseError(
                planner="ollama",
                model=self.config.model,
                raw_response=response_text[:500],
                parse_error=error,
            )

        # Validate the structure
        is_valid, validation_error = validate_tool_call_json(parsed)
        if not is_valid:
            raise PlannerInvalidResponseError(
                planner="ollama",
                model=self.config.model,
                raw_response=response_text[:500],
                validation_error=validation_error or "Unknown validation error",
            )

        # Check for done signal
        if parsed.get("done"):
            return Done(
                final_output=parsed.get("output"),
                reason=parsed.get("reason", "task_complete"),
            )

        # Create ToolCall
        # Note: We create a PlannerProposal first, then convert to ToolCall
        # The actual ToolCall with IDs is created by the agent loop
        proposal = PlannerProposal(
            tool_name=parsed["tool"],
            args=parsed.get("args", {}),
            reasoning=parsed.get("reasoning"),
            raw_response=response_text,
            iteration=iteration,
        )

        # For now, return a minimal ToolCall
        # The agent loop will assign proper IDs
        return ToolCall(
            call_id="pending",  # Will be assigned by agent loop
            run_id="pending",  # Will be assigned by agent loop
            step_index=iteration,
            tool_name=proposal.tool_name,
            args=proposal.args,
        )

    def get_name(self) -> str:
        """Return planner name."""
        return f"OllamaPlanner({self.config.model})"

    def get_config(self) -> dict[str, Any]:
        """Return planner configuration."""
        return {
            "backend": "ollama",
            "base_url": self.config.base_url,
            "model": self.config.model,
            "timeout_seconds": self.config.timeout_seconds,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

    def check_connection(self) -> tuple[bool, str]:
        """
        Check if Ollama is accessible and the model is available.

        Returns:
            Tuple of (is_ok, message)
        """
        try:
            client = self._get_client()
            response = client.get("/api/tags")
            if response.status_code != 200:
                return False, f"Ollama returned HTTP {response.status_code}"

            data = response.json()
            models = [m["name"] for m in data.get("models", [])]

            if not models:
                return False, "No models available. Run: ollama pull qwen2.5:0.5b"

            # Check if our model is available
            # Handle both "model" and "model:tag" formats
            model_base = self.config.model.split(":")[0]
            available = any(
                m == self.config.model or m.startswith(f"{model_base}:") for m in models
            )

            if not available:
                return (
                    False,
                    f"Model '{self.config.model}' not found. Available: {', '.join(models[:3])}",
                )

            return True, f"Connected to Ollama, model '{self.config.model}' available"

        except httpx.ConnectError:
            return False, f"Cannot connect to Ollama at {self.config.base_url}. Is it running?"
        except Exception as e:
            return False, f"Error checking Ollama: {e}"
