# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2025-01-20

### Added

#### Core Features
- **Execution Engine**: Run agent tool call plans under policy constraints
- **Policy Engine**: Deny-by-default policy enforcement with granular controls
- **Storage System**: SQLite-based audit logging with cryptographic hashes
- **Replay System**: Deterministic replay of past executions
- **Reporting**: Rich console and JSON report generation

#### Built-in Tools
- `fs.read`: Read file contents with path allowlist, size limits, dotfile blocking
- `fs.write`: Write to files with path allowlist and size limits
- `http.get`: HTTP GET requests with domain allowlist and private IP blocking
- `shell.run`: Execute commands with executable allowlist and token blocklist

#### CLI Commands
- `capsule run`: Execute a plan under policy constraints
- `capsule replay`: Replay a previous run using stored results
- `capsule report`: Generate console or JSON reports
- `capsule list-runs`: List all recorded runs
- `capsule show-run`: Show details of a specific run

#### Policy Controls
- Path glob patterns for filesystem access
- Domain allowlists for HTTP requests
- Private IP range blocking (10.x, 172.16.x, 192.168.x, localhost)
- Executable allowlists for shell commands
- Token blocklists for dangerous shell patterns
- Global timeout and per-tool quotas
- Size limits for files and responses

#### Security Features
- Deny-by-default policy boundary
- Path normalization (symlink resolution, `..` traversal blocking)
- DNS resolution before HTTP to prevent rebinding attacks
- Shell commands use list form only (no shell injection)
- Full audit trail with SHA256 hashes

#### Developer Experience
- Typer-based CLI with rich help text
- Pydantic models for strict validation
- Rich terminal output with tables and status icons
- JSON output mode for all commands
- Verbose and debug modes
- 397 tests with comprehensive coverage

### Documentation
- Comprehensive README with 5-minute quickstart
- Architecture documentation with diagrams
- Example plans and policies
- Inline code documentation

### Infrastructure
- GitHub Actions CI for testing across Python 3.11-3.13
- Pre-commit hooks configuration
- Type checking with mypy
- Linting with ruff

[Unreleased]: https://github.com/capsule-dev/capsule/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/capsule-dev/capsule/releases/tag/v0.1.0
