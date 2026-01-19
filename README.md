# Capsule

**Local-first runtime for executing agent tool calls under strict policy controls.**

Capsule serves as the missing layer between "LLM agent frameworks" and "safe, reproducible execution."

## Features

- **Deny-by-default policy enforcement** - Everything is blocked unless explicitly allowed
- **Full audit logging** - All tool calls and results stored in SQLite
- **Deterministic replay** - Reproduce exact behavior from past executions
- **Extensible tool interface** - Easy to add new tools

## Quick Start (5-minute demo)

### Installation

```bash
pip install capsule
# or
pipx install capsule
```

### 1. Create a plan

Create `plan.yaml`:

```yaml
version: "1.0"
steps:
  - tool: fs.read
    args:
      path: "./README.md"
  - tool: shell.run
    args:
      cmd: ["echo", "Hello from Capsule!"]
```

### 2. Create a policy

Create `policy.yaml`:

```yaml
boundary: deny_by_default
tools:
  fs.read:
    allow_paths:
      - "./**"
    max_size_bytes: 1048576
  shell.run:
    allow_executables:
      - "echo"
    timeout_seconds: 30
```

### 3. Run the plan

```bash
capsule run plan.yaml --policy policy.yaml
```

### 4. View the results

```bash
capsule list-runs
capsule report <run_id>
```

### 5. Replay a run

```bash
capsule replay <run_id>
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `capsule run <plan> --policy <policy>` | Execute a plan under policy constraints |
| `capsule replay <run_id>` | Replay a previous run |
| `capsule report <run_id>` | Generate a report |
| `capsule list-runs` | List all recorded runs |
| `capsule show-run <run_id>` | Show details of a run |

## Built-in Tools (v0.1)

| Tool | Description | Policy Controls |
|------|-------------|-----------------|
| `fs.read` | Read file contents | Path allowlist, size limit |
| `fs.write` | Write to files | Path allowlist, size limit |
| `http.get` | HTTP GET requests | Domain allowlist, private IP blocking |
| `shell.run` | Execute commands | Executable allowlist, token blocklist |

## Development

```bash
# Clone and install
git clone https://github.com/capsule-dev/capsule.git
cd capsule
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy src/capsule

# Linting
ruff check src tests
```

## Documentation

- [Requirements](docs/requirements.md)
- [Implementation Plan](docs/implementation_plan.md)
- [Development Plan](docs/development_plan.md)

## License

MIT
