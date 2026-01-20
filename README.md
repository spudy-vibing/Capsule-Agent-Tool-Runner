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

- [Requirements (v0.1)](docs/archive/v0.1/requirements_v0.1.md) - Product requirements (Archived)
- [Implementation Plan (v0.1)](docs/archive/v0.1/implementation_plan.md) - Technical design (Archived)
- [Development Plan (v0.1)](docs/archive/v0.1/development_plan.md) - Build roadmap (Archived)
- [Architecture](docs/architecture.md) - System architecture

## Security Considerations

Capsule is designed with security in mind:

- **Deny-by-default**: All operations blocked unless explicitly allowed
- **Path normalization**: Symlinks resolved, `..` traversal blocked
- **Private IP blocking**: HTTP requests to internal networks blocked by default
- **Shell safety**: Commands use list form (no shell injection), token scanning
- **Audit trail**: All operations logged with cryptographic hashes

However, Capsule is not a security sandbox. It provides policy enforcement but runs tools in the same process. For untrusted code execution, use containerization.

## License

MIT
