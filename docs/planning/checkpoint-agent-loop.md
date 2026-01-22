# Checkpoint: v0.2.0-alpha.2 Agent Loop Implementation

**Date:** 2026-01-21
**Status:** ✅ COMPLETED - All implementation done, tests passing

## Summary

Implementing the Agent Loop that integrates the Planner (from v0.2.0-alpha.1) with policy evaluation and tool execution, creating a dynamic propose → evaluate → execute → learn cycle.

## Completed Work

### 1. Plan Approved
- Plan file: `/Users/shubhamupadhyay/.claude/plans/dazzling-growing-aurora.md`
- Architecture designed with propose → evaluate → execute → learn cycle
- All files to create/modify identified

### 2. Agent Package Created
- Created directory: `src/capsule/agent/`
- Created `src/capsule/agent/__init__.py` with exports:
  - `AgentConfig`
  - `AgentLoop`
  - `AgentResult`
  - `IterationResult`

## Completed Work (Todo List)

| # | Task | Status |
|---|------|--------|
| 1 | Create src/capsule/agent/__init__.py package | ✅ Completed |
| 2 | Create src/capsule/agent/loop.py with data classes | ✅ Completed |
| 3 | Implement AgentLoop.run() with full loop logic | ✅ Completed |
| 4 | Add planner_proposals table to store/db.py | ✅ Completed |
| 5 | Add capsule agent run CLI command | ✅ Completed |
| 6 | Write unit tests for AgentLoop | ✅ Completed (24 tests) |
| 7 | Write integration tests | ✅ Completed (7 tests) |
| 8 | Run full test suite and verify | ✅ Completed (537 tests passing) |

## Files Created/Modified

| File | Action | Status |
|------|--------|--------|
| `src/capsule/agent/__init__.py` | Create | ✅ Done |
| `src/capsule/agent/loop.py` | Create | ✅ Done (665 lines) |
| `src/capsule/store/db.py` | Modify | ✅ Done |
| `src/capsule/cli.py` | Modify | ✅ Done |
| `tests/unit/test_agent_loop.py` | Create | ✅ Done (713 lines) |
| `tests/integration/test_agent_integration.py` | Create | ✅ Done (415 lines) |

## Key Design Decisions

### AgentLoop Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         AgentLoop                                │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  1. Build PlannerState (task, tool_schemas, history)     │   │
│  │  2. Call planner.propose_next(state, last_result)        │   │
│  │  3. If Done → finalize and return                        │   │
│  │  4. If ToolCall → evaluate with PolicyEngine             │   │
│  │  5. If denied → record, loop back to step 2              │   │
│  │  6. If allowed → execute with Executor                   │   │
│  │  7. Record result, update history, loop back to step 2   │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Data Classes for loop.py

```python
@dataclass
class AgentConfig:
    max_iterations: int = 20
    iteration_timeout_seconds: float = 60.0
    total_timeout_seconds: float = 300.0
    repetition_threshold: int = 3  # Same call N times = stop
    max_history_items: int = 10
    max_history_chars: int = 8000

@dataclass
class IterationResult:
    iteration: int
    proposal: PlannerProposal | None  # What planner suggested
    tool_call: ToolCall | None        # The actual call made
    tool_result: ToolResult | None    # Result of execution
    done: Done | None                 # If planner signaled done

@dataclass
class AgentResult:
    run_id: str
    task: str
    status: str  # "completed", "max_iterations", "timeout", "error", "repetition_detected"
    iterations: list[IterationResult]
    final_output: Any
    total_duration_seconds: float
    planner_name: str
```

### AgentLoop Class Structure

```python
class AgentLoop:
    def __init__(
        self,
        planner: Planner,          # From capsule.planner.base
        policy_engine: PolicyEngine,  # From capsule.policy
        registry: ToolRegistry,     # From capsule.tools.registry
        db: CapsuleDB,             # From capsule.store.db
        config: AgentConfig | None = None,
    ):
        ...

    def run(self, task: str, working_dir: str | None = None) -> AgentResult:
        """Main entry point - execute task with planner-driven loop."""
        ...

    def _build_state(self, task: str, history: list, iteration: int) -> PlannerState:
        """Build planner state with truncated history."""
        ...

    def _truncate_history(self, history: list) -> list:
        """Limit history to max items and chars."""
        ...

    def _detect_repetition(self, history: list, proposal: ToolCall) -> bool:
        """Detect if same tool call repeated too many times."""
        ...

    def _get_tool_schemas(self) -> list[dict]:
        """Get schemas from all registered tools."""
        ...

    def _execute_tool(self, tool_call: ToolCall, working_dir: str) -> ToolResult:
        """Execute a single tool call."""
        ...
```

### Database Extension (planner_proposals table)

```sql
CREATE TABLE planner_proposals (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    proposal_type TEXT NOT NULL,  -- 'tool_call' or 'done'
    tool_name TEXT,
    args_json TEXT,
    reasoning TEXT,
    raw_response TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id)
)
```

### CLI Command

```
capsule agent run <task> --policy <file> --tools <file> [options]

Options:
  --policy, -p       Policy YAML file (required)
  --tools, -t        Tools YAML file (required)
  --planner          Planner backend (default: ollama)
  --model            Model name (default: qwen2.5:0.5b)
  --max-iterations   Max iterations (default: 20)
  --working-dir      Working directory
  --json             JSON output format
```

## Key Interfaces Analyzed

### 1. Planner Interface (`src/capsule/planner/base.py`)
- `PlannerState`: task, tool_schemas, policy_summary, history, iteration, metadata
- `Done`: final_output, reason (sentinel for completion)
- `Planner.propose_next(state, last_result) -> ToolCall | Done`

### 2. PolicyEngine Interface (`src/capsule/policy/engine.py`)
- `PolicyEngine.evaluate(tool_name, args, working_dir) -> PolicyDecision`
- `PolicyDecision.allowed: bool`, `PolicyDecision.reason: str`

### 3. Tool Interface (`src/capsule/tools/base.py`)
- `Tool.name: str` - unique identifier
- `Tool.description: str` - human-readable description
- `Tool.execute(args, context) -> ToolOutput`
- `ToolOutput.success: bool`, `ToolOutput.data`, `ToolOutput.error`
- `ToolContext(run_id, policy, working_dir)`

### 4. ToolRegistry Interface (`src/capsule/tools/registry.py`)
- `registry.get(name) -> Tool`
- `registry.list_tools() -> list[str]`
- Iteration: `for tool in registry`

### 5. CapsuleDB Interface (`src/capsule/store/db.py`)
- `generate_id() -> str` (8-char UUID)
- `compute_hash(data) -> str` (SHA256)
- `now_iso() -> str` (ISO timestamp)
- `db.create_run(plan, policy, mode) -> run_id`
- `db.record_call(run_id, step_index, tool_name, args) -> call_id`
- `db.record_result(call_id, run_id, status, output, error, ...)`
- `db.update_run_status(run_id, status, ...)`

### 6. Engine Pattern (`src/capsule/engine.py`)
- `Engine._execute_step()` shows pattern for:
  - Recording calls before execution
  - Evaluating policy
  - Handling denials
  - Executing tools
  - Recording results

## Tool Schema Format Expected by Planner

Based on `src/capsule/planner/ollama.py:_format_tool_schemas()`:

```python
{
    "name": "fs.read",
    "description": "Read file contents",
    "args": {
        "path": {
            "type": "string",
            "required": True
        }
    }
}
```

## Security Features to Implement

1. **Repetition Detection**: Stop if same tool call appears 3+ times consecutively
2. **History Truncation**: Limit history to 10 items / 8000 chars to prevent context overflow
3. **Timeout Protection**: Per-iteration and total execution timeouts
4. **Policy Enforcement**: All proposals validated before execution

## Test Plan

### Unit Tests (`tests/unit/test_agent_loop.py`)
- `test_agent_loop_init` - Initialize with all components
- `test_agent_loop_simple_task` - Complete task in few iterations
- `test_agent_loop_handles_done` - Stop on Done sentinel
- `test_agent_loop_max_iterations` - Stop at limit
- `test_agent_loop_policy_denial` - Re-prompt on denial
- `test_agent_loop_repetition_detection` - Detect loops
- `test_agent_loop_history_truncation` - Limit history size
- `test_agent_loop_records_proposals` - Database recording

### Integration Tests (`tests/integration/test_agent_integration.py`)
- `test_agent_with_mock_planner` - Full flow with mock
- `test_agent_file_operations` - Real file tool calls
- `test_agent_respects_policy` - Policy enforcement

## Related Files (Already Read)

These files were analyzed to understand the patterns:

1. `src/capsule/store/db.py` - Database patterns, table structures
2. `src/capsule/planner/base.py` - PlannerState, Done, Planner ABC
3. `src/capsule/planner/ollama.py` - OllamaPlanner implementation
4. `src/capsule/planner/json_repair.py` - JSON parsing utilities
5. `src/capsule/engine.py` - Execution patterns
6. `src/capsule/policy/engine.py` - Policy evaluation
7. `src/capsule/tools/base.py` - Tool, ToolContext, ToolOutput
8. `src/capsule/tools/registry.py` - ToolRegistry

## Git Status

- Branch: `main`
- Last commit: `6e91969` - docs: Update README to reflect archival of older documentation links
- Working tree: Clean (agent/__init__.py created but not committed)

## Implementation Complete

All components have been implemented and tested:

1. **`src/capsule/agent/loop.py`** - Full implementation with:
   - AgentConfig dataclass
   - IterationResult dataclass
   - AgentResult dataclass
   - AgentLoop class with run(), _run_iteration(), and helper methods

2. **`src/capsule/store/db.py`** - Updated with:
   - planner_proposals table in CREATE_TABLES_SQL
   - `record_planner_proposal()` method
   - `get_proposals_for_run()` method

3. **`src/capsule/cli.py`** - Updated with:
   - `agent_app` Typer subcommand
   - `capsule agent run` command with full options

4. **Tests**:
   - 24 unit tests in `tests/unit/test_agent_loop.py`
   - 7 integration tests in `tests/integration/test_agent_integration.py`
   - All 537 tests passing

## Verification Commands (Completed)

```bash
# All tests pass
pytest tests/ -v  # 537 passed

# Type checking passes
mypy src/capsule/agent/  # Success: no issues found

# Linting passes
ruff check src/capsule/agent/  # All checks passed!
```

## Bugs Fixed During Implementation

1. **Foreign key reference in db.py** - `planner_proposals` table was referencing `runs(id)` instead of `runs(run_id)`
2. **Run ID mismatch in loop.py** - AgentLoop was generating its own run_id instead of using the one returned by `db.create_run()`
3. **Call ID mismatch in loop.py** - Similar issue where local call_id wasn't matching the one returned by `db.record_call()`
