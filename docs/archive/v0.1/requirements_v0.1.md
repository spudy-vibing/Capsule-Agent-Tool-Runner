# Product Requirements Document: Capsule

**Version**: 0.1
**Status**: Draft

## 1. Introduction

### 1.1 Goal
Build an open-source, local-first runtime that executes "agent tool calls" under strict policy controls, with full audit logs and deterministic replay.
Capsule serves as the missing layer between "LLM agent frameworks" and "safe, reproducible execution."

### 1.2 Target Audience
*   **Engineers**: Building agentic workflows (LLM optional).
*   **Security Teams**: Prototyping internal automation with strict controls.
*   **Open Source Contributors**: Seeking a safe tool-running standard.
*   **Learners**: Developers who want to understand the internals of agent runtimes, sandboxing, and policy engines.

### 1.3 Educational Goals
*   **Transparent Architecture**: Codebase should be structured as a reference implementation for learning.
*   **Documentation-Driven**: Extensive inline comments and architectural decision records (ADRs) to explain *why* decisions were made.
*   **Clear Patterns**: Demonstrate Python best practices for CLI tools, plugin systems, and secure I/O handling.
*   **Step-by-Step Build**: The project will be built incrementally (Milestone 1 -> 2 -> 3) to demonstrate how to layer complexity.
*   **Architectural Deep Dives**: Documentation will explain the rationale behind the tech stack (Typer, Pydantic, SQLite) and design patterns (Policy Engine, Middleware).

### 1.4 Scope (v0.1)
*   **In Scope**: Local CLI, reproducible execution, strict policy enforcement, basic tools (FS, HTTP, Shell).
*   **Out of Scope**: Hosted SaaS, complex UI dashboards, fully autonomous agent loops (planning is external/scripted).

## 2. Core User Stories

### 2.1 Safe Execution
"As a developer, I want to run a YAML plan that calls tools (fs/http/shell) but is constrained by a policy, so the run is safe and predictable."

### 2.2 Transparency
"As a developer, I want a readable report of each tool call, what was allowed/denied, and why."

### 2.3 Deterministic Replay
"As a developer, I want to replay a previous run without hitting the filesystem/network again, so results are reproducible."

### 2.4 Extensibility
"As a contributor, I want a clear plugin interface to add tools, with minimal boilerplate."

## 3. Functional Requirements

### 3.1 CLI Interface
The `capsule` CLI is the primary entry point.
*   `capsule run <plan.yaml> --policy <policy.yaml> [--out run.db]`
*   `capsule replay <run_id> [--out replay.db]`
*   `capsule report <run_id> [--format console|json]`
*   `capsule list-runs`
*   `capsule show-run <run_id>`

### 3.2 Input Formats
*   **Plan (YAML)**: Sequence of steps. Each step defines: `tool`, `args`, optional `id`/`name`.
*   **Policy (YAML)**: Security constraints.
    *   Global default: `deny`.
    *   Per-tool: `allow`/`deny`, quotas, bounds.

### 3.3 Core Tools (MVP)
1.  **`fs.read`**: Read text/binary. Constraints: path allowlist, size cap.
2.  **`fs.write`**: Write to files. Constraints: path allowlist.
3.  **`http.get`**: GET requests. Constraints: domain allowlist, max bytes, block private IPs.
4.  **`shell.run`**: Execute commands. Constraints: strict executable allowlist, denied tokens, timeout.

### 3.4 Policy Enforcement (MVP)
*   **Deny-by-default**: Everything is blocked unless explicitly allowed.
*   **Filesystem**: Glob pattern allowlists (e.g., `~/projects/**`). Option to deny hidden files (`.ssh`, `.env`).
*   **Network**: Domain allowlist. Deny private IP ranges. Cap response body size.
*   **Shell**: Allowlist by executable name. Deny specific tokens/args. Cap runtime and output size.

### 3.5 Logging & Storage
*   **Technology**: SQLite.
*   **Data Stored**:
    *   `runs`: Metadata about the execution.
    *   `tool_calls`: Input arguments and tool names.
    *   `tool_results`: Outputs, errors, timestamps, policy decisions (allowed/denied + reason).
    *   **Integrity**: Store input/output hashes.

### 3.6 Replay System
*   Replays use stored `tool_results` instead of executing tools.
*   Verifies that the plan matches the original execution flow.

### 3.7 Reporting
*   **Console Output**: Rich timeline view with status icons.
*   **Summary**: Files accessed, domains contacted, shell commands run, total duration, policy denials.

## 4. Non-Functional Requirements

### 4.1 Security
*   **Fail-Closed**: Policy defaults to deny.
*   **Safe Defaults**: Block sensitive paths (dotfiles) and private networks out-of-the-box.
*   **Shell Safety**: No arbitrary shell execution (must use list-form commands).

### 4.2 Reliability
*   **Reproducibility**: Replay must be bit-exact based on stored results.
*   **Error Handling**: Distinct classes for Policy Denial vs. Tool Error vs. Runtime Error.
*   **Timeouts**: Strict timeouts for all I/O operations.

### 4.3 Developer Experience
*   **Installation**: `pipx install capsule` or `pip install .`
*   **Documentation**: "5-minute demo" in README.
*   **Testing**: High coverage for policy logic and replay mechanics.
