# Development Plan - Capsule v0.1

**Status**: Phase 1 Complete ✓
**Based on**: requirements.md, implementation_plan.md, gap analysis
**Approach**: Incremental build with security-first defaults

---

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Phasing | 3 phases (Skeleton → Tools → Polish) | Allows early validation of core architecture |
| http.get | Include in Phase 2 | Network tool adds complexity; defer until core is stable |
| Shell safety | Allowlist executables + blocklist tokens | Defense in depth |
| Educational | ADRs + inline comments + architecture.md | Balance learning value vs maintenance burden |
| Test coverage | 80% core, 60% overall | Focus testing on security-critical paths |
| Plugin system | Internal-only for v0.1 | Keep scope manageable; design for future extensibility |

---

## Project Structure

```
capsule/
├── pyproject.toml              # Project metadata, dependencies
├── README.md                   # 5-minute demo
├── docs/
│   ├── requirements.md
│   ├── implementation_plan.md
│   ├── development_plan.md     # This file
│   ├── architecture.md         # System design + diagrams
│   └── adr/                    # Architectural Decision Records
│       ├── 001-cli-framework.md
│       ├── 002-policy-engine.md
│       ├── 003-storage-choice.md
│       └── ...
├── src/
│   └── capsule/
│       ├── __init__.py
│       ├── cli.py              # Typer CLI entry point
│       ├── engine.py           # Main execution loop
│       ├── schema.py           # Pydantic models
│       ├── policy/
│       │   ├── __init__.py
│       │   ├── engine.py       # PolicyEngine class
│       │   ├── rules.py        # Rule evaluation logic
│       │   └── defaults.py     # Safe default rules
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── base.py         # Tool ABC + ToolContext
│       │   ├── registry.py     # Tool registration
│       │   ├── fs.py           # fs.read, fs.write
│       │   ├── http.py         # http.get
│       │   └── shell.py        # shell.run
│       ├── store/
│       │   ├── __init__.py
│       │   ├── db.py           # SQLite operations
│       │   ├── models.py       # DB row models
│       │   └── migrations.py   # Schema versioning
│       ├── replay/
│       │   ├── __init__.py
│       │   └── engine.py       # Replay logic
│       ├── report/
│       │   ├── __init__.py
│       │   ├── console.py      # Rich terminal output
│       │   └── json.py         # JSON export
│       └── errors.py           # Exception hierarchy
├── tests/
│   ├── conftest.py             # Fixtures
│   ├── unit/
│   │   ├── test_schema.py
│   │   ├── test_policy.py
│   │   ├── test_tools_fs.py
│   │   ├── test_tools_http.py
│   │   ├── test_tools_shell.py
│   │   └── test_store.py
│   ├── integration/
│   │   ├── test_engine.py
│   │   ├── test_replay.py
│   │   └── test_cli.py
│   └── security/
│       ├── test_path_traversal.py
│       ├── test_private_ip.py
│       └── test_shell_injection.py
└── examples/
    ├── plans/
    │   ├── simple_read.yaml
    │   ├── multi_step.yaml
    │   └── network_fetch.yaml
    └── policies/
        ├── strict.yaml
        ├── permissive.yaml
        └── development.yaml
```

---

## Phase 1: Core Skeleton

**Goal**: Minimal working CLI that can execute a single `fs.read` call with policy enforcement and SQLite logging.

**Duration Estimate**: Foundation layer

### Step 1.1: Project Setup ✓

**Tasks**:
- [x] Initialize Python project with `pyproject.toml`
- [x] Configure dependencies: `typer`, `pydantic`, `rich`, `pyyaml`
- [x] Configure dev dependencies: `pytest`, `pytest-cov`, `ruff`, `mypy`
- [x] Set up `src/capsule/` package structure
- [x] Create basic `__init__.py` with version
- [x] Add `.gitignore`, `.python-version`

**Files created**:
- `pyproject.toml`
- `src/capsule/__init__.py`
- `.gitignore`
- `README.md`

**Definition of Done**: ✓
- `pip install -e .` works
- `python -c "import capsule"` succeeds

---

### Step 1.2: Schema Definitions ✓

**Tasks**:
- [x] Define `PlanStep` model (tool, args, optional id/name)
- [x] Define `Plan` model (version, steps list)
- [x] Define `PolicyRule` model (tool-specific constraints)
- [x] Define `Policy` model (boundary default, tool rules)
- [x] Define `ToolCall` model (runtime representation)
- [x] Define `ToolResult` model (output, error, status, timing)
- [x] Define `PolicyDecision` model (allowed: bool, reason: str)
- [x] Add YAML loading helpers with validation

**Files created**:
- `src/capsule/schema.py` (553 lines, 44 tests)

**Definition of Done**: ✓
- Can parse `examples/plans/simple_read.yaml`
- Can parse `examples/policies/strict.yaml`
- Invalid YAML raises `ValidationError` with clear message

---

### Step 1.3: Error Hierarchy ✓

**Tasks**:
- [x] Create base `CapsuleError` exception
- [x] Create `PolicyDeniedError` (tool, args, reason)
- [x] Create `ToolExecutionError` (tool, args, underlying error)
- [x] Create `PlanValidationError` (step index, message)
- [x] Create `ReplayMismatchError` (expected, actual)
- [x] Create `StorageError` (operation, underlying error)

**Files created**:
- `src/capsule/errors.py` (27 tests)

**Definition of Done**: ✓
- All errors inherit from `CapsuleError`
- Each error has `__str__` with actionable message
- Errors are importable from `capsule.errors`

---

### Step 1.4: Tool Interface & Registry ✓

**Tasks**:
- [x] Define `Tool` ABC with `name`, `execute(args, context) -> ToolOutput`
- [x] Define `ToolContext` (run_id, policy reference, store reference)
- [x] Define `ToolOutput` (success: bool, data: Any, error: Optional[str])
- [x] Create `ToolRegistry` class with `register()` and `get()` methods
- [x] Create global `default_registry` instance

**Files created**:
- `src/capsule/tools/__init__.py`
- `src/capsule/tools/base.py`
- `src/capsule/tools/registry.py`
- 33 tests in `test_tools_base.py`

**Definition of Done**: ✓
- Can define a mock tool implementing the interface
- Registry lookup by name works
- Unknown tool raises clear error

---

### Step 1.5: fs.read & fs.write Tools ✓

**Tasks**:
- [x] Implement `FsReadTool` class
- [x] Implement `FsWriteTool` class
- [x] Accept `path` argument (required)
- [x] Read file contents as text (UTF-8 default)
- [x] Support encoding parameter
- [x] Support append mode for writes
- [x] Return file contents in `ToolOutput.data`
- [x] Handle file-not-found gracefully
- [x] Handle permission errors gracefully
- [x] Register in default registry

**Files created**:
- `src/capsule/tools/fs.py`
- 33 tests in `test_tools_fs.py`

**Definition of Done**: ✓
- `fs.read` and `fs.write` registered and callable
- Returns file contents or clear error
- Unit tests pass

---

### Step 1.6: Policy Engine (Basic) ✓

**Tasks**:
- [x] Create `PolicyEngine` class
- [x] Implement `evaluate(tool_name, args) -> PolicyDecision`
- [x] Support deny-by-default boundary
- [x] Support `allow_paths` glob matching for fs tools
- [x] Support `max_size_bytes` constraint
- [x] Implement path normalization (resolve `..`, `~`)
- [x] Block hidden files (dotfiles) by default unless explicitly allowed
- [x] Support HTTP domain allowlist and private IP blocking
- [x] Support shell executable allowlist and token blocklist

**Files created**:
- `src/capsule/policy/__init__.py`
- `src/capsule/policy/engine.py`
- 33 tests in `test_policy.py`
- 19 tests in `test_path_traversal.py`

**Definition of Done**: ✓
- Policy engine returns ALLOW/DENY with reason
- All path traversal attacks blocked
- Symlink resolution works on macOS

---

### Step 1.7: SQLite Storage ✓

**Tasks**:
- [x] Create database initialization with schema
- [x] Implement `runs` table operations (create, get, list, update status)
- [x] Implement `tool_calls` table operations (insert, get by run)
- [x] Implement `tool_results` table operations (insert, get by call)
- [x] Implement SHA256 hashing for inputs/outputs
- [x] Add transaction support for atomic writes
- [x] Store plan and policy JSON for replay

**Files created**:
- `src/capsule/store/__init__.py`
- `src/capsule/store/db.py`
- 30 tests in `test_store.py`

**Definition of Done**: ✓
- Can create run, log calls, log results
- Data persists across process restarts
- Hashes are computed and stored

---

### Step 1.8: Execution Engine ✓

**Tasks**:
- [x] Create `Engine` class
- [x] Implement `run(plan, policy, db_path) -> RunResult`
- [x] For each step: evaluate policy → execute tool → store result
- [x] Stop on first policy denial (fail-closed)
- [x] Stop on first tool error (configurable: fail-fast vs continue)
- [x] Track timing for each step
- [x] Return summary with all results

**Files created**:
- `src/capsule/engine.py`
- 20 tests in `tests/integration/test_engine.py`

**Definition of Done**: ✓
- Engine orchestrates policy → tool → store flow
- All steps logged to SQLite
- Policy denials stop execution

---

### Step 1.9: CLI (Basic Commands) ✓

**Tasks**:
- [x] Create Typer app
- [x] Implement `capsule run <plan.yaml> --policy <policy.yaml> [--out run.db]`
- [x] Implement `capsule list-runs [--db run.db]`
- [x] Implement `capsule show-run <run_id> [--db run.db]`
- [x] Add `--verbose` flag for debug output
- [x] Add `--version` flag
- [x] Add `--no-fail-fast` flag
- [x] Use Rich for formatted output with tables

**Files created**:
- `src/capsule/cli.py`
- `src/capsule/__main__.py`

**Definition of Done**: ✓
- `capsule run` executes a plan and stores results
- `capsule list-runs` shows past runs
- `capsule show-run` shows run details
- Error messages are user-friendly

---

### Phase 1 Milestone Checklist ✓

- [x] Can run: `capsule run plan.yaml --policy policy.yaml`
- [x] fs.read works with policy enforcement
- [x] fs.write works with policy enforcement
- [x] Results stored in SQLite
- [x] Can list and view past runs
- [x] Path traversal attacks blocked
- [x] Dotfiles blocked by default
- [x] Symlink resolution on macOS
- [x] **239 tests passing**

**Test Summary**:
| Module | Tests |
|--------|-------|
| test_schema.py | 44 |
| test_errors.py | 27 |
| test_tools_base.py | 33 |
| test_tools_fs.py | 33 |
| test_policy.py | 33 |
| test_path_traversal.py | 19 |
| test_store.py | 30 |
| test_engine.py | 20 |
| **Total** | **239** |

---

## Phase 2: Complete Tools & Policy

**Goal**: Add remaining tools (http.get, shell.run) with full policy enforcement.
**Status**: Not Started

### Step 2.1: fs.write Tool ✓ (Completed in Phase 1)

**Moved to Step 1.5** - fs.write was implemented alongside fs.read.

---

### Step 2.2: http.get Tool

**Tasks**:
- [ ] Implement `HttpGetTool` class
- [ ] Accept `url` argument (required)
- [ ] Accept `headers` argument (optional dict)
- [ ] Use `httpx` or `urllib3` for requests
- [ ] Policy: `allow_domains` list
- [ ] Policy: `deny_private_ips` (default: true)
  - Block: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8, ::1
  - Resolve hostname before request to prevent DNS rebinding
- [ ] Policy: `max_response_bytes`
- [ ] Policy: `timeout_seconds` (default: 30)
- [ ] Return response body, status code, headers in output
- [ ] Register in default registry

**Files to create**:
- `src/capsule/tools/http.py`

**Files to update**:
- `src/capsule/policy/rules.py`
- `pyproject.toml` (add httpx dependency)

**Tests**:
- `tests/unit/test_tools_http.py`
  - Fetch from allowed domain
  - Deny fetch from non-allowed domain
  - Deny fetch to private IP
  - Deny fetch to localhost
  - Timeout handling
  - Response size limit

**Security Tests**:
- `tests/security/test_private_ip.py`
  - Direct private IP blocked
  - DNS rebinding attempt blocked
  - IPv6 localhost blocked

**Definition of Done**:
- http.get registered and callable
- Cannot fetch from private networks
- Response size limited
- Timeouts enforced

**ADR**: `006-network-security.md` - Private IP blocking, DNS rebinding prevention

---

### Step 2.3: shell.run Tool

**Tasks**:
- [ ] Implement `ShellRunTool` class
- [ ] Accept `cmd` argument (list of strings, NOT shell string)
- [ ] Accept `cwd` argument (optional working directory)
- [ ] Accept `env` argument (optional environment additions)
- [ ] Use `subprocess.run` with `shell=False` always
- [ ] Policy: `allow_executables` list (e.g., ["git", "echo", "ls"])
- [ ] Policy: `deny_tokens` list (e.g., ["rm", "-rf", "sudo", "|", ";", "&"])
  - Scan all arguments for denied tokens
- [ ] Policy: `timeout_seconds` (default: 60)
- [ ] Policy: `max_output_bytes` (default: 1MB)
- [ ] Capture stdout, stderr, return code
- [ ] Register in default registry

**Files to create**:
- `src/capsule/tools/shell.py`

**Files to update**:
- `src/capsule/policy/rules.py`

**Tests**:
- `tests/unit/test_tools_shell.py`
  - Run allowed command
  - Deny non-allowed executable
  - Deny command with blocked token
  - Timeout handling
  - Output truncation

**Security Tests**:
- `tests/security/test_shell_injection.py`
  - Shell metacharacters in args blocked
  - Path to disallowed executable blocked
  - Environment variable injection

**Definition of Done**:
- shell.run registered and callable
- Only allowlisted executables can run
- Dangerous tokens blocked
- Cannot escape to shell interpretation
- Timeouts enforced

**ADR**: `007-shell-safety.md` - Why list-form only, token blocking strategy

---

### Step 2.4: Policy Enhancements

**Tasks**:
- [ ] Add quota support (max calls per tool per run)
- [ ] Add global timeout (max total run duration)
- [ ] Add `deny_patterns` for flexible blocking (regex)
- [ ] Improve policy error messages (show which rule denied)
- [ ] Add policy validation on load (catch config errors early)
- [ ] Add policy "explain" mode (show what would be allowed)

**Files to update**:
- `src/capsule/policy/engine.py`
- `src/capsule/policy/rules.py`
- `src/capsule/schema.py`

**Tests**:
- Quota enforcement
- Global timeout
- Regex deny patterns
- Policy validation errors

**Definition of Done**:
- Quotas limit tool call frequency
- Policy errors are actionable
- Can "dry run" policy to see permissions

---

### Step 2.5: Enhanced Error Handling

**Tasks**:
- [ ] Add structured error output (JSON-serializable)
- [ ] Add error codes for programmatic handling
- [ ] Add suggestion text for common errors
- [ ] Ensure all errors have context (tool, step, args)
- [ ] Add `--debug` flag to CLI for full tracebacks

**Files to update**:
- `src/capsule/errors.py`
- `src/capsule/cli.py`

**Definition of Done**:
- All errors have error code
- Errors include remediation hints
- Debug mode shows full context

---

### Phase 2 Milestone Checklist

- [ ] All 4 tools implemented (fs.read, fs.write, http.get, shell.run)
- [ ] All policy constraints enforced
- [ ] Private IP blocking works
- [ ] Shell injection prevented
- [ ] Quotas and timeouts work
- [ ] Security test suite passes
- [ ] ADRs written (006-007)

---

## Phase 3: Replay, Reporting & Polish

**Goal**: Complete replay system, add reporting, documentation, and prepare for release.

### Step 3.1: Replay Engine

**Tasks**:
- [ ] Create `ReplayEngine` class
- [ ] Implement `replay(run_id, db_path) -> ReplayResult`
- [ ] Load original run from database
- [ ] For each step: return stored result instead of executing
- [ ] Verify plan hash matches original
- [ ] Verify step sequence matches original
- [ ] Detect and report any mismatches
- [ ] Store replay as new run with mode='replay'

**Files to create**:
- `src/capsule/replay/__init__.py`
- `src/capsule/replay/engine.py`

**Tests**:
- `tests/integration/test_replay.py`
  - Replay returns same results
  - Replay detects modified plan
  - Replay stores new run record
  - Output hashes verified

**Definition of Done**:
- `capsule replay <run_id>` works
- Results are bit-exact from stored data
- Mismatches clearly reported

---

### Step 3.2: CLI - Replay & Report Commands

**Tasks**:
- [ ] Implement `capsule replay <run_id> [--db run.db] [--out replay.db]`
- [ ] Implement `capsule report <run_id> [--format console|json]`
- [ ] Console report: Rich timeline with status icons
- [ ] Console report: Summary section
  - Files accessed (read/write)
  - Domains contacted
  - Shell commands run
  - Total duration
  - Policy denials count
- [ ] JSON report: Full structured output

**Files to create**:
- `src/capsule/report/__init__.py`
- `src/capsule/report/console.py`
- `src/capsule/report/json.py`

**Files to update**:
- `src/capsule/cli.py`

**Definition of Done**:
- `capsule replay` executes deterministically
- `capsule report` shows beautiful timeline
- JSON export works

---

### Step 3.3: Documentation

**Tasks**:
- [ ] Write README.md with 5-minute demo
- [ ] Write `docs/architecture.md` with diagrams
- [ ] Complete all ADRs (001-007+)
- [ ] Add docstrings to all public APIs
- [ ] Add inline comments for complex logic
- [ ] Create example plans and policies
- [ ] Add CONTRIBUTING.md

**Files to create/update**:
- `README.md`
- `docs/architecture.md`
- `docs/adr/*.md`
- `CONTRIBUTING.md`
- `examples/plans/*.yaml`
- `examples/policies/*.yaml`

**Definition of Done**:
- New user can run demo in 5 minutes
- Architecture is documented
- All ADRs complete

---

### Step 3.4: Testing & Coverage

**Tasks**:
- [ ] Achieve 80% coverage on core modules
- [ ] Achieve 60% coverage overall
- [ ] Add property-based tests for policy (hypothesis)
- [ ] Add fuzzing for path/URL parsing
- [ ] Add CI configuration (GitHub Actions)
- [ ] Add pre-commit hooks (ruff, mypy)

**Files to create**:
- `.github/workflows/ci.yml`
- `.pre-commit-config.yaml`

**Definition of Done**:
- CI passes on all PRs
- Coverage thresholds enforced
- Type checking passes

---

### Step 3.5: Packaging & Release

**Tasks**:
- [ ] Finalize `pyproject.toml` metadata
- [ ] Add classifiers, keywords, URLs
- [ ] Test `pip install .` and `pipx install .`
- [ ] Create GitHub release workflow
- [ ] Write CHANGELOG.md
- [ ] Tag v0.1.0

**Files to create/update**:
- `pyproject.toml`
- `CHANGELOG.md`
- `.github/workflows/release.yml`

**Definition of Done**:
- `pipx install capsule` works
- Package on PyPI (or ready to publish)
- v0.1.0 tagged

---

### Phase 3 Milestone Checklist

- [ ] Replay system complete and verified
- [ ] Reports show timeline + summary
- [ ] README has working 5-minute demo
- [ ] Architecture documented
- [ ] All ADRs written
- [ ] 80% core / 60% overall coverage
- [ ] CI/CD configured
- [ ] Ready for v0.1.0 release

---

## Summary: All Phases

| Phase | Focus | Key Deliverables |
|-------|-------|------------------|
| **Phase 1** | Core Skeleton | CLI + fs.read + Policy + SQLite |
| **Phase 2** | Complete Tools | fs.write + http.get + shell.run + Security |
| **Phase 3** | Polish | Replay + Reports + Docs + Release |

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| DNS rebinding in http.get | Resolve IP before request, block private ranges |
| Path traversal in fs tools | Normalize paths, resolve symlinks, validate after resolution |
| Shell injection | List-form only, token scanning, no shell=True ever |
| Scope creep | Strict v0.1 scope, defer features to v0.2 |
| Test gaps in security | Dedicated security test suite, reviewed by security-minded contributor |

---

## Next Steps

**Phase 1 Complete!** Ready for Phase 2:

1. Implement `http.get` tool (Step 2.2)
2. Implement `shell.run` tool (Step 2.3)
3. Add quota and global timeout enforcement (Step 2.4)
4. Enhanced error handling (Step 2.5)
