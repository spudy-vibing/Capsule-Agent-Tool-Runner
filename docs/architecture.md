# Architecture - Capsule v0.1

This document describes the system architecture of Capsule, a local-first runtime for executing agent tool calls under strict policy controls.

## Overview

Capsule follows a layered architecture with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────────┐
│                         CLI Layer                           │
│                      (cli.py - Typer)                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      Orchestration Layer                    │
│              (engine.py, replay/engine.py)                  │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌───────────────────┐
│ Policy Engine │   │  Tool Registry  │   │  Storage Layer    │
│  (policy/)    │   │   (tools/)      │   │   (store/)        │
└───────────────┘   └─────────────────┘   └───────────────────┘
                              │
        ┌─────────┬───────────┼───────────┬─────────┐
        ▼         ▼           ▼           ▼         ▼
    ┌───────┐ ┌───────┐ ┌──────────┐ ┌─────────┐
    │fs.read│ │fs.write│ │ http.get │ │shell.run│
    └───────┘ └───────┘ └──────────┘ └─────────┘
```

## Core Components

### 1. CLI Layer (`cli.py`)

The CLI provides the user-facing interface using [Typer](https://typer.tiangolo.com/).

**Responsibilities:**
- Parse command-line arguments
- Load plan and policy files
- Delegate to engine/replay modules
- Format output using Rich

**Commands:**
- `run` - Execute a plan
- `replay` - Replay a previous run
- `report` - Generate reports
- `list-runs` - List recorded runs
- `show-run` - Show run details

**Design Decision:** The CLI is intentionally thin. All business logic lives in the engine modules, making the core functionality usable programmatically.

### 2. Execution Engine (`engine.py`)

The main orchestration layer that executes plans under policy constraints.

**Responsibilities:**
- Create run records in storage
- Iterate through plan steps
- Evaluate each step against policy
- Execute allowed tool calls
- Record results with timing and hashes
- Track run statistics

**Execution Flow:**
```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Load Plan   │────▶│ Create Run   │────▶│  For Each    │
│  & Policy    │     │   Record     │     │    Step:     │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                  │
                     ┌────────────────────────────┘
                     ▼
              ┌─────────────┐    DENY    ┌─────────────┐
              │  Evaluate   │───────────▶│   Record    │
              │   Policy    │            │   Denial    │
              └──────┬──────┘            └─────────────┘
                     │ ALLOW
                     ▼
              ┌─────────────┐    ERROR   ┌─────────────┐
              │   Execute   │───────────▶│   Record    │
              │    Tool     │            │   Error     │
              └──────┬──────┘            └─────────────┘
                     │ SUCCESS
                     ▼
              ┌─────────────┐
              │   Record    │
              │   Result    │
              └─────────────┘
```

### 3. Replay Engine (`replay/engine.py`)

Enables deterministic replay of past executions.

**Responsibilities:**
- Load original run from storage
- Verify plan hash (optional)
- Return stored results instead of executing
- Create new run record with `mode='replay'`
- Detect and report mismatches

**Key Features:**
- Bit-exact reproduction of past runs
- Data integrity verification via `verify_run()`
- Full audit trail for replays

### 4. Policy Engine (`policy/`)

Central policy evaluation system.

**Responsibilities:**
- Evaluate tool calls against policy rules
- Path matching with glob patterns
- Domain allowlist checking
- Private IP blocking
- Executable allowlist enforcement
- Token scanning for shell commands
- Quota enforcement

**Design Principles:**
- **Deny-by-default**: Everything blocked unless explicitly allowed
- **Fail-closed**: Errors in policy evaluation result in denial
- **Defense in depth**: Multiple layers of checks

**Policy Evaluation Flow:**
```
┌────────────────┐
│ Tool Call Args │
└───────┬────────┘
        ▼
┌────────────────┐     NO      ┌────────────────┐
│ Tool in Policy?│────────────▶│     DENY       │
└───────┬────────┘             └────────────────┘
        │ YES
        ▼
┌────────────────┐     FAIL    ┌────────────────┐
│ Check Allowlist│────────────▶│     DENY       │
│   (paths/etc)  │             │  (with reason) │
└───────┬────────┘             └────────────────┘
        │ PASS
        ▼
┌────────────────┐     FAIL    ┌────────────────┐
│ Check Denylist │────────────▶│     DENY       │
│  (patterns)    │             │  (with reason) │
└───────┬────────┘             └────────────────┘
        │ PASS
        ▼
┌────────────────┐     EXCEED  ┌────────────────┐
│  Check Quota   │────────────▶│     DENY       │
└───────┬────────┘             └────────────────┘
        │ WITHIN
        ▼
┌────────────────┐
│     ALLOW      │
└────────────────┘
```

### 5. Tool System (`tools/`)

Standardized interface for tool implementations.

**Components:**
- `base.py` - Abstract `Tool` class and `ToolContext`
- `registry.py` - `ToolRegistry` for tool lookup
- `fs.py` - `FsReadTool`, `FsWriteTool`
- `http.py` - `HttpGetTool`
- `shell.py` - `ShellRunTool`

**Tool Interface:**
```python
class Tool(ABC):
    name: str  # e.g., "fs.read"

    @abstractmethod
    def execute(self, args: dict, context: ToolContext) -> ToolOutput:
        """Execute the tool with given arguments."""
        pass
```

**ToolContext provides:**
- `run_id` - Current run identifier
- `policy` - Policy configuration
- `working_dir` - Working directory for relative paths

**ToolOutput contains:**
- `success` - Whether execution succeeded
- `data` - Result data (if successful)
- `error` - Error message (if failed)

### 6. Storage Layer (`store/`)

SQLite-based persistence for runs, calls, and results.

**Tables:**

```sql
-- Runs: execution metadata
runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT,
    completed_at TEXT,
    plan_hash TEXT,
    policy_hash TEXT,
    plan_json TEXT,      -- Full plan for replay
    policy_json TEXT,    -- Full policy for replay
    mode TEXT,           -- 'run' or 'replay'
    status TEXT,         -- 'pending', 'running', 'completed', 'failed'
    total_steps INTEGER,
    completed_steps INTEGER,
    denied_steps INTEGER,
    failed_steps INTEGER
)

-- Tool Calls: invocation records
tool_calls (
    call_id TEXT PRIMARY KEY,
    run_id TEXT,
    step_index INTEGER,
    tool_name TEXT,
    args_json TEXT,
    created_at TEXT
)

-- Tool Results: execution outcomes
tool_results (
    call_id TEXT PRIMARY KEY,
    run_id TEXT,
    status TEXT,         -- 'success', 'error', 'denied'
    output_json TEXT,
    error TEXT,
    policy_decision_json TEXT,
    started_at TEXT,
    ended_at TEXT,
    input_hash TEXT,     -- SHA256 of input
    output_hash TEXT     -- SHA256 of output
)
```

**Design Decisions:**
- Single file for portability
- Append-only for audit integrity
- Full plan/policy stored for replay
- Cryptographic hashes for verification

### 7. Report Module (`report/`)

Report generation for completed runs.

**Components:**
- `console.py` - Rich terminal output
- `json.py` - Structured JSON export

**Console Report Features:**
- Timeline view with status icons
- Timing information
- Resource access summary
- Policy denial details

**JSON Report Structure:**
```json
{
  "report_version": "1.0",
  "generated_at": "...",
  "run": { /* metadata */ },
  "plan": { /* original plan */ },
  "policy": { /* original policy */ },
  "steps": [ /* call + result details */ ],
  "summary": {
    "total_duration_ms": 123,
    "resources": {
      "files_read": [...],
      "domains_contacted": [...]
    }
  }
}
```

### 8. Schema Module (`schema.py`)

Pydantic models for all data structures.

**Key Models:**
- `Plan`, `PlanStep` - Execution plans
- `Policy`, `FsPolicy`, `HttpPolicy`, `ShellPolicy` - Policy configuration
- `ToolCall`, `ToolResult` - Runtime records
- `PolicyDecision` - Policy evaluation results
- `Run` - Run metadata

**Design Decisions:**
- Strict validation (no type coercion)
- Frozen models where possible
- YAML loading helpers included

### 9. Error Hierarchy (`errors.py`)

Structured exception system.

**Categories:**
- `PolicyDeniedError` (1xxx) - Policy blocks action
- `ToolError` (2xxx) - Tool execution failures
- `PlanValidationError` (3xxx) - Invalid plan format
- `ReplayError` (4xxx) - Replay mismatches
- `StorageError` (5xxx) - Database operations

**Design Principles:**
- All errors have numeric codes
- Errors include context (tool, args, etc.)
- Actionable suggestions where possible

## Data Flow

### Run Execution

```
User                CLI              Engine           Policy          Tool            Storage
 │                   │                  │               │              │                 │
 │ run plan.yaml     │                  │               │              │                 │
 │──────────────────▶│                  │               │              │                 │
 │                   │ run(plan,policy) │               │              │                 │
 │                   │─────────────────▶│               │              │                 │
 │                   │                  │ create_run()  │              │                 │
 │                   │                  │──────────────────────────────────────────────▶│
 │                   │                  │               │              │                 │
 │                   │                  │ For each step:│              │                 │
 │                   │                  │               │              │                 │
 │                   │                  │ evaluate()    │              │                 │
 │                   │                  │──────────────▶│              │                 │
 │                   │                  │◀──────────────│              │                 │
 │                   │                  │               │              │                 │
 │                   │                  │ execute()     │              │                 │
 │                   │                  │─────────────────────────────▶│                 │
 │                   │                  │◀─────────────────────────────│                 │
 │                   │                  │               │              │                 │
 │                   │                  │ record_result()              │                 │
 │                   │                  │──────────────────────────────────────────────▶│
 │                   │                  │               │              │                 │
 │                   │◀─────────────────│               │              │                 │
 │◀──────────────────│                  │               │              │                 │
```

### Replay

```
User                CLI           ReplayEngine        Storage
 │                   │                  │                │
 │ replay run_id     │                  │                │
 │──────────────────▶│                  │                │
 │                   │ replay(run_id)   │                │
 │                   │─────────────────▶│                │
 │                   │                  │ get_run()      │
 │                   │                  │───────────────▶│
 │                   │                  │◀───────────────│
 │                   │                  │                │
 │                   │                  │ get_calls()    │
 │                   │                  │───────────────▶│
 │                   │                  │◀───────────────│
 │                   │                  │                │
 │                   │                  │ get_results()  │
 │                   │                  │───────────────▶│
 │                   │                  │◀───────────────│
 │                   │                  │                │
 │                   │                  │ create_run(replay)
 │                   │                  │───────────────▶│
 │                   │                  │                │
 │                   │◀─────────────────│                │
 │◀──────────────────│                  │                │
```

## Security Model

### Threat Model

Capsule protects against:
- Unintended file access (path traversal, symlinks)
- Network access to internal resources (private IPs)
- Shell command injection
- Resource exhaustion (timeouts, size limits)

Capsule does NOT protect against:
- Malicious code in the same process
- Kernel-level attacks
- Side-channel attacks

### Defense Layers

1. **Policy Evaluation** - First line of defense
2. **Path Normalization** - Resolve symlinks, block `..`
3. **Domain Resolution** - Check IPs before connecting
4. **Token Scanning** - Block dangerous shell patterns
5. **Audit Logging** - Full traceability

## Extension Points

### Adding New Tools

1. Create tool class implementing `Tool` ABC:
```python
class MyTool(Tool):
    name = "my.tool"

    def execute(self, args: dict, context: ToolContext) -> ToolOutput:
        # Implementation
        return ToolOutput(success=True, data=result)
```

2. Add policy model in `schema.py`
3. Add policy evaluation in `policy/engine.py`
4. Register in `tools/__init__.py`

### Future Extension Points

- Custom policy rule types
- Tool middleware/hooks
- Alternative storage backends
- Remote execution support

## Technology Choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| CLI | Typer | Best-in-class DX, automatic help |
| Validation | Pydantic | Type safety, clear errors |
| Storage | SQLite | Zero-config, ACID, portable |
| Output | Rich | Beautiful terminal formatting |
| HTTP | httpx | Modern async support, timeouts |
| Testing | pytest | Standard, extensible |

## Performance Considerations

- **Startup**: ~50ms (Python import overhead)
- **Per-step overhead**: ~1ms (policy + storage)
- **Storage**: ~1KB per step (compressed JSON)
- **Memory**: O(n) where n = number of steps

## Future Roadmap

- **v0.2**: Plugin system, remote tools
- **v0.3**: Async execution, parallel steps
- **v1.0**: Stable API, full documentation
