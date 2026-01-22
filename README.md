# Capsule

**Local-first runtime for executing agent tool calls under strict policy controls.**

Capsule serves as the missing layer between "LLM agent frameworks" and "safe, reproducible execution." It provides a secure sandbox for running file, network, and shell operations with full audit logging and deterministic replay.

## Features

- **Deny-by-default policy enforcement** - Everything is blocked unless explicitly allowed
- **Full audit logging** - All tool calls and results stored in SQLite with cryptographic hashes
- **Deterministic replay** - Reproduce exact behavior from past executions
- **Rich reporting** - Timeline views and JSON export for analysis
- **Extensible tool interface** - Clean plugin architecture for adding new tools

## Quick Start (5 minutes)

### Installation

```bash
# Install from source
git clone https://github.com/capsule-dev/capsule.git
cd capsule
pip install -e .

# Or with dev dependencies
pip install -e ".[dev]"
```

### 1. Create a Plan

Plans define the sequence of tool calls to execute. Create `plan.yaml`:

```yaml
version: "1.0"
name: "hello-world"
description: "A simple demo plan"
steps:
  - tool: fs.read
    name: "Read README"
    args:
      path: "./README.md"

  - tool: shell.run
    name: "Say hello"
    args:
      cmd: ["echo", "Hello from Capsule!"]
```

### 2. Create a Policy

Policies define what's allowed. Create `policy.yaml`:

```yaml
boundary: deny_by_default

tools:
  fs.read:
    allow_paths:
      - "./**"           # Allow reading from current directory
    deny_paths:
      - "./.env"         # But block .env files
      - "**/.git/**"     # And .git directories
    max_size_bytes: 1048576  # 1MB limit
    allow_hidden: false      # Block dotfiles by default

  shell.run:
    allow_executables:
      - "echo"
      - "git"
      - "ls"
    deny_tokens:
      - "sudo"
      - "rm -rf"
    timeout_seconds: 30
    max_output_bytes: 102400  # 100KB

global_timeout_seconds: 300  # 5 minute total limit
max_calls_per_tool: 50       # Quota per tool type
```

### 3. Run the Plan

```bash
# Execute the plan
capsule run plan.yaml --policy policy.yaml

# With verbose output
capsule run plan.yaml --policy policy.yaml --verbose

# Output results as JSON
capsule run plan.yaml --policy policy.yaml --json
```

Example output:
```
✓ Run a1b2c3d4: completed

┏━━━┳━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ # ┃ Tool      ┃ Status  ┃ Details                     ┃
┡━━━╇━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1 │ fs.read   │ success │ # Capsule...                │
│ 2 │ shell.run │ success │ Hello from Capsule!         │
└───┴───────────┴─────────┴─────────────────────────────┘

Total: 2 | Completed: 2 | Denied: 0 | Failed: 0
Duration: 15.3ms
```

### 4. View Results

```bash
# List all runs
capsule list-runs

# Show detailed run info
capsule show-run <run_id>

# Generate a report (console)
capsule report <run_id>

# Generate a report (JSON)
capsule report <run_id> --format json
```

### 5. Replay a Run

Replay returns stored results without re-executing tools:

```bash
# Replay a previous run
capsule replay <run_id>

# Verify integrity before replay
capsule replay <run_id> --verify

# Output as JSON
capsule replay <run_id> --json
```

## Dynamic Agent Mode

Capsule includes a **dynamic agent mode** that uses a local LLM (via Ollama) to automatically decide which tools to call based on your task description. Instead of writing a static plan, you describe what you want and the agent figures out the steps.

### Prerequisites: Ollama Setup

1. **Install Ollama** (if not already installed):
   ```bash
   # macOS
   brew install ollama

   # Linux
   curl -fsSL https://ollama.com/install.sh | sh

   # Or download from https://ollama.com
   ```

2. **Start Ollama**:
   ```bash
   ollama serve
   ```

3. **Pull a model** (see recommendations below):
   ```bash
   ollama pull qwen2.5:7b
   ```

4. **Verify setup**:
   ```bash
   capsule doctor
   ```

### Recommended Models

| Model | Size | RAM Needed | Quality | Speed | Best For |
|-------|------|------------|---------|-------|----------|
| `qwen2.5:0.5b` | 400MB | ~2GB | Low | Fast | Testing only |
| `qwen2.5:1.5b` | 1GB | ~3GB | Fair | Fast | Simple tasks |
| `qwen2.5:3b` | 2GB | ~4GB | Good | Medium | **Recommended starter** |
| `qwen2.5:7b` | 4.5GB | ~8GB | Great | Medium | **Best balance** |
| `qwen2.5:14b` | 9GB | ~16GB | Excellent | Slow | Complex reasoning |
| `llama3.1:8b` | 4.7GB | ~8GB | Great | Medium | Alternative option |
| `mistral:7b` | 4GB | ~8GB | Great | Medium | Alternative option |

**Recommendation**: Start with `qwen2.5:7b` for the best balance of quality and speed. Qwen models excel at structured JSON output which is critical for tool calling.

### Basic Usage

```bash
# Simple task
capsule agent run "List all Python files in src/" \
  --policy policy.yaml \
  --model qwen2.5:7b

# Read and analyze a file
capsule agent run "Read pyproject.toml and tell me the project dependencies" \
  --policy policy.yaml \
  --model qwen2.5:7b \
  --pretty

# Multi-step task
capsule agent run "Find all TODO comments in the codebase" \
  --policy policy.yaml \
  --model qwen2.5:7b \
  --pretty
```

### Output Formats

| Flag | Description | Use Case |
|------|-------------|----------|
| (none) | Compact table | Quick overview |
| `--verbose` | Table with metadata | Debugging |
| `--json` | Full JSON output | Scripting/parsing |
| `--pretty` | Human-readable panels | **Best for interactive use** |

**Example with `--pretty`:**
```
╭──────────────────────────── Task ────────────────────────────╮
│ List files in src/capsule                                    │
╰──────────────────────────────────────────────────────────────╯

✓ Status: Completed | Duration: 5.24s

Step 1: shell.run(cmd=['ls', 'src/capsule'])
  ✓ Success (4.37s)

╭────────────────────── Output (exit 0) ───────────────────────╮
│ __init__.py                                                  │
│ agent                                                        │
│ cli.py                                                       │
│ engine.py                                                    │
│ ...                                                          │
╰──────────────────────────────────────────────────────────────╯

Step 2: Done
  Reason: task_complete

─── 2 steps, 1 successful ───
```

### Accessing Results

The actual results are in `tool_result.output`, not `final_output` (small models don't summarize).

```bash
# Get full JSON
capsule agent run "List files" -p policy.yaml --model qwen2.5:7b --json

# Extract tool output with jq
capsule agent run "List files" -p policy.yaml --model qwen2.5:7b --json \
  | jq '.iterations[].tool_result.output'

# Get shell stdout specifically
capsule agent run "Run ls" -p policy.yaml --model qwen2.5:7b --json \
  | jq '.iterations[0].tool_result.output.stdout'
```

### How the Agent Works

```
┌─────────────────────────────────────────────────────────────────┐
│                         Agent Loop                               │
├─────────────────────────────────────────────────────────────────┤
│  1. You provide: Task description + Policy                      │
│  2. Agent builds prompt with available tools & policy summary   │
│  3. LLM outputs: {"tool": "fs.read", "args": {"path": "..."}}  │
│  4. Policy engine checks if allowed                             │
│  5. If allowed → execute tool → get result                      │
│  6. Result added to history, sent back to LLM                   │
│  7. LLM decides: call another tool OR {"done": true}            │
│  8. Repeat until done or max_iterations                         │
└─────────────────────────────────────────────────────────────────┘
```

**The LLM sees this prompt:**
```
You are a helpful assistant that completes tasks by calling tools.

IMPORTANT RULES:
1. Respond with ONLY a JSON object, no other text
2. To call a tool: {"tool": "<name>", "args": {...}}
3. When done: {"done": true, "reason": "task_complete"}

Available tools:
- fs.read: Read file contents
    - path: string (required)
- shell.run: Execute a shell command
    - cmd: array (required)

Policy constraints:
fs.read: allow_paths=[./**], shell.run: allow_executables=[ls, find, ...]

Task: <your task>
Previous results: <history>
```

### Agent Command Options

```bash
capsule agent run <task> [OPTIONS]

Arguments:
  <task>                    Task description for the agent

Options:
  -p, --policy PATH         Policy YAML file (required)
  -m, --model TEXT          Model name [default: qwen2.5:0.5b]
  --planner TEXT            Planner backend [default: ollama]
  --max-iterations INT      Max iterations [default: 20]
  -w, --working-dir PATH    Working directory
  -o, --out PATH            Output database [default: capsule.db]
  --json                    JSON output format
  --verbose                 Verbose output
  --pretty                  Human-readable output with full results
  --debug                   Show full error tracebacks
```

### Example Policy for Agent Tasks

Create `agent-policy.yaml`:

```yaml
tools:
  # File reading - allow project files
  fs_read:
    allow_paths:
      - "./**"
    deny_paths:
      - "**/.env"
      - "**/*.key"
      - "**/secrets/**"
    allow_hidden: false

  # File writing - restricted locations
  fs_write:
    allow_paths:
      - "./output/**"
      - "./tmp/**"
    max_size_bytes: 1048576

  # Shell commands - safe read-only commands
  shell_run:
    allow_executables:
      - "ls"
      - "find"
      - "wc"
      - "cat"
      - "head"
      - "tail"
      - "grep"
      - "echo"
      - "pwd"
      - "date"
    timeout_seconds: 30

  # HTTP - disabled
  http_get:
    allow_domains: []

global_timeout_seconds: 300
max_calls_per_tool: 50
```

### Tips & Best Practices

1. **Be specific in your task description**
   ```bash
   # Good
   "Read src/main.py and count the number of functions"

   # Less good
   "Analyze the code"
   ```

2. **Use larger models for complex tasks**
   - `qwen2.5:0.5b` - Only for testing, often skips tool calls
   - `qwen2.5:7b` - Good for most tasks
   - `qwen2.5:14b` - Best for multi-step reasoning

3. **Check results with `--pretty`** for interactive use

4. **Use `--json` for scripting** and pipe to `jq`

5. **Set appropriate `--max-iterations`** to prevent runaway loops

6. **Policy is enforced** - The agent can only use tools allowed by your policy

### Troubleshooting

| Issue | Solution |
|-------|----------|
| "Ollama not connected" | Run `ollama serve` and `capsule doctor` |
| "No models found" | Run `ollama pull qwen2.5:7b` |
| Model says "done" immediately | Use a larger model (3b+) |
| Stuck in a loop | Model is confused; try clearer task or larger model |
| "Blocked token found" | Policy denied the command; check `deny_tokens` |
| JSON parse errors | Model output was malformed; try again or use larger model |

### Programmatic Usage

```python
from capsule.agent import AgentLoop, AgentConfig
from capsule.planner.ollama import OllamaPlanner, OllamaConfig
from capsule.policy.engine import PolicyEngine
from capsule.schema import Policy
from capsule.store.db import CapsuleDB
from capsule.tools.registry import default_registry

# Setup
policy = Policy(tools={
    "fs_read": {"allow_paths": ["./**"]},
    "shell_run": {"allow_executables": ["ls", "find"]},
})
planner = OllamaPlanner(OllamaConfig(model="qwen2.5:7b"))
policy_engine = PolicyEngine(policy)
db = CapsuleDB("agent.db")

# Create agent loop
loop = AgentLoop(
    planner=planner,
    policy_engine=policy_engine,
    registry=default_registry,
    db=db,
    config=AgentConfig(max_iterations=10),
)

# Run task
result = loop.run("List all Python files in src/")

print(f"Status: {result.status}")
for it in result.iterations:
    if it.tool_result:
        print(f"Tool: {it.tool_call.tool_name}")
        print(f"Output: {it.tool_result.output}")

# Cleanup
db.close()
planner.close()
```

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `capsule run <plan> --policy <policy>` | Execute a plan under policy constraints |
| `capsule replay <run_id>` | Replay a previous run using stored results |
| `capsule report <run_id> [--format json]` | Generate a report for a run |
| `capsule list-runs` | List all recorded runs |
| `capsule show-run <run_id>` | Show details of a specific run |

### Common Options

| Option | Description |
|--------|-------------|
| `--db <path>` | Path to SQLite database (default: `capsule.db`) |
| `--verbose` | Enable verbose output |
| `--json` | Output results as JSON |
| `--debug` | Show full error tracebacks |

## Built-in Tools

### `fs.read` - Read Files

```yaml
- tool: fs.read
  args:
    path: "./file.txt"      # Required: file path
    encoding: "utf-8"       # Optional: encoding (default: utf-8)
```

**Policy options:**
- `allow_paths`: Glob patterns for allowed paths
- `deny_paths`: Glob patterns for denied paths (takes precedence)
- `max_size_bytes`: Maximum file size
- `allow_hidden`: Whether to allow dotfiles (default: false)

### `fs.write` - Write Files

```yaml
- tool: fs.write
  args:
    path: "./output.txt"    # Required: file path
    content: "Hello!"       # Required: content to write
    encoding: "utf-8"       # Optional: encoding
    append: false           # Optional: append mode
```

**Policy options:** Same as `fs.read`

### `http.get` - HTTP Requests

```yaml
- tool: http.get
  args:
    url: "https://api.example.com/data"  # Required: URL
    headers:                              # Optional: headers
      Authorization: "Bearer token"
```

**Policy options:**
- `allow_domains`: List of allowed domains
- `deny_private_ips`: Block private IP ranges (default: true)
- `max_response_bytes`: Maximum response size
- `timeout_seconds`: Request timeout

### `shell.run` - Execute Commands

```yaml
- tool: shell.run
  args:
    cmd: ["git", "status"]  # Required: command as list
    cwd: "./project"        # Optional: working directory
    env:                    # Optional: environment variables
      DEBUG: "1"
```

**Policy options:**
- `allow_executables`: List of allowed executable names
- `deny_tokens`: Blocked tokens in arguments
- `timeout_seconds`: Command timeout
- `max_output_bytes`: Maximum stdout/stderr size

## Policy Examples

### Strict (Production)

```yaml
boundary: deny_by_default
tools:
  fs.read:
    allow_paths:
      - "/app/data/**"
    max_size_bytes: 1048576
  http.get:
    allow_domains:
      - "api.internal.com"
    deny_private_ips: true
global_timeout_seconds: 60
```

### Permissive (Development)

```yaml
boundary: deny_by_default
tools:
  fs.read:
    allow_paths: ["./**"]
    allow_hidden: false
  fs.write:
    allow_paths: ["./output/**"]
  shell.run:
    allow_executables: ["echo", "ls", "git", "npm", "python"]
    timeout_seconds: 120
  http.get:
    allow_domains: ["*"]
    deny_private_ips: true
global_timeout_seconds: 300
```

## Programmatic Usage

```python
from capsule.engine import Engine
from capsule.schema import load_plan, load_policy

# Load plan and policy
plan = load_plan("plan.yaml")
policy = load_policy("policy.yaml")

# Execute
with Engine(db_path="capsule.db") as engine:
    result = engine.run(plan, policy)

    print(f"Run {result.run_id}: {result.status.value}")
    print(f"Completed: {result.completed_steps}/{result.total_steps}")

    for step in result.steps:
        print(f"  {step.tool_name}: {step.status.value}")
```

### Replay Programmatically

```python
from capsule.replay import ReplayEngine

with ReplayEngine(db_path="capsule.db") as engine:
    result = engine.replay("a1b2c3d4")

    print(f"Replayed {result.total_steps} steps")
    print(f"Plan verified: {result.plan_verified}")
```

### Generate Reports

```python
from capsule.report import generate_json_report, build_report_dict

# Get JSON string
json_str = generate_json_report("a1b2c3d4", "capsule.db")

# Or get as dictionary
report = build_report_dict("a1b2c3d4", "capsule.db")
print(report["summary"]["total_duration_ms"])
```

## Development

```bash
# Clone and install
git clone https://github.com/capsule-dev/capsule.git
cd capsule
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=capsule --cov-report=term-missing

# Type checking
mypy src/capsule

# Linting
ruff check src tests

# Format code
ruff format src tests
```

## Documentation

- [Architecture](docs/architecture.md) - System architecture
- [Threat Model](docs/threat_model.md) - Security threat analysis and mitigations
- [Requirements (v0.1)](docs/archive/v0.1/requirements_v0.1.md) - Product requirements (Archived)
- [Implementation Plan (v0.1)](docs/archive/v0.1/implementation_plan.md) - Technical design (Archived)
- [Development Plan (v0.1)](docs/archive/v0.1/development_plan.md) - Build roadmap (Archived)

## Security Considerations

Capsule is designed with security in mind:

- **Deny-by-default**: All operations blocked unless explicitly allowed
- **Path normalization**: Symlinks resolved, `..` traversal blocked
- **Symlink protection**: Symlink escapes detected and blocked (v0.1.1)
- **Private IP blocking**: HTTP requests to internal networks blocked by default
- **DNS rebinding protection**: IPs verified before HTTP requests
- **Shell safety**: Commands use list form (no shell injection), token scanning
- **Audit trail**: All operations logged with cryptographic hashes

**Audit Log Security:** The SQLite database (`capsule.db`) stores complete tool inputs and outputs, which may include sensitive data like API keys or file contents. Secure the database file appropriately and review contents before sharing. See [Threat Model](docs/threat_model.md) for details.

However, Capsule is not a security sandbox. It provides policy enforcement but runs tools in the same process. For untrusted code execution, use containerization.

## License

MIT
