# Implementation Plan - Capsule (v0.1)

## Goal
Build an open-source, local-first runtime that executes "agent tool calls" under strict policy controls, with full audit logs and deterministic replay.
"Agent Sandbox OS" in Python.

## User Review Required
> [!IMPORTANT]
> **Repo Name**: `capsule` (Assumed based on request)
> **Scope**: v0.1 (Local-first, CPU-only, No LLM required yet)
> **Safety**: Deny-by-default policy for all tools.

## Tech Stack Rationale (For Learning)
We chose this stack to balance simplicity, type safety, and "production-grade" practices:
*   **Typer (CLI)**: Best-in-class developer experience for building CLIs in Python. Teaches how to build robust command-line tools.
*   **Pydantic (Schema)**: Strict data validation. Essential for defining safe schemas for Tools and Policies.
*   **SQLite (Storage)**: Built-in, zero-conf ACID database. Perfect for audit logs without needing a separate server.
*   **Rich (Output)**: Beautiful terminal formatting. Shows how to build professional-looking developer tools.

## Proposed Architecture

### Core Components
1.  **CLI (`cli.py`)**: Typer-based entry point.
2.  **Schema (`schema.py`)**: Pydantic models for Plans, Policies, ToolCalls, Results.
3.  **Policy Engine (`policy.py`)**: Central evaluator `evaluate(tool, args) -> Decision`.
4.  **Engine (`engine.py`)**: Main execution loop (Plan -> Policy -> Tool -> Store).
5.  **Tools (`tools/`)**: Standardized tool interface (FS, HTTP, Shell).
6.  **Store (`store/db.py`)**: SQLite storage for runs and replay.
7.  **Report (`report/`)**: Console output and JSON/Timeline generation.

### Data Model (SQLite)

#### Table: `runs`
- `run_id` (TEXT PK)
- `created_at` (ISO8601)
- `plan_hash` (TEXT)
- `policy_hash` (TEXT)
- `mode` (TEXT) - e.g., 'run', 'replay'
- `status` (TEXT) - e.g., 'pending', 'completed', 'failed'

#### Table: `tool_calls`
- `call_id` (TEXT PK)
- `run_id` (TEXT FK)
- `step_index` (INT)
- `tool_name` (TEXT)
- `args_json` (JSON TEXT)
- `created_at` (ISO8601)

#### Table: `tool_results`
- `call_id` (TEXT FK)
- `run_id` (TEXT FK)
- `status` (TEXT) - 'success', 'error', 'denied'
- `output_json` (JSON TEXT)
- `error_json` (JSON TEXT) - Nullable
- `policy_decision_json` (JSON TEXT) - Reason for denial if applicable
- `started_at` (ISO8601)
- `ended_at` (ISO8601)
- `input_hash` (TEXT)
- `output_hash` (TEXT)

### Interfaces

#### Tool Interface
```python
class Tool(ABC):
    name: str
    
    @abstractmethod
    def execute(self, args: Dict, context: ToolContext) -> ToolOutput:
        pass
```

#### Policy Interface
```python
class PolicyEngine:
    def evaluate(self, tool_name: str, args: Dict) -> PolicyDecision:
        # Returns ALLOW or DENY with reason
        pass
```

### Plan Format (YAML)
```yaml
version: "1.0"
steps:
  - tool: fs.read
    args:
      path: "./README.md"
  - tool: shell.run
    args:
      cmd: ["echo", "hello"]
```

### Policy Format (YAML)
```yaml
boundary: deny_by_default
tools:
  fs.read:
    allow_paths: ["/Users/me/projects/**"]
    max_size_bytes: 1024
  shell.run:
    allow_executables: ["echo", "git"]
```

## Verification Plan

### Automated Tests
- **Unit Tests**:
    - Policy evaluation logic (Path matching, Domain filtering).
    - Schema validation.
- **Integration Tests**:
    - End-to-end execution of a sample plan.
    - Replay verification (Compare output against stored db).
    - Security regression tests (Access denied for restricted paths).

### Manual Verification
- Run the "5-minute demo" scenario.
- Inspect SQLite DB manually to ensure log integrity.
- Verify CLI output formatting (Timeline view).
