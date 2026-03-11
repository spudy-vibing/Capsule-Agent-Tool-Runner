# Pack Authoring Guide

This guide covers how to create Capsule packs with evaluation test cases and scoring.

## Pack Structure

```
my_pack/
├── manifest.yaml          # Pack metadata, inputs, outputs
├── policy.yaml            # Security policy for tool access
├── prompts/
│   └── system.txt         # Jinja2 prompt template
├── plans/
│   └── default.yaml       # Optional: static execution plan
├── evals/
│   └── test_cases.yaml    # Evaluation test cases
└── patterns/              # Optional: pack-specific data files
```

## manifest.yaml

```yaml
name: my-pack
version: "1.0.0"
description: "What this pack does"
author: "Your Name"
license: MIT
tags: [security, analysis]
capsule_version: ">=0.2.0"

tools_required:
  - fs.read
  - shell.run

inputs:
  target_directory:
    type: string
    required: true
    description: "Directory to analyze"
  sensitivity:
    type: string
    required: false
    default: medium
    enum: [low, medium, high]
    description: "Detection sensitivity level"

outputs:
  report:
    type: string
    description: "Analysis report"

prompt_template: prompts/system.txt
yaml_entry: null  # Set to plans/default.yaml for static plan mode
```

## Evaluation Test Cases

Test cases live in `evals/test_cases.yaml` and are run by the eval harness (`capsule eval run`).

### Test Case Format

```yaml
version: "1.0"
pack: my-pack

test_cases:
  # Deterministic test: injects a tool call and checks policy decision
  - name: blocks_read_outside_target
    description: Should deny reading files outside target directory
    input:
      target_directory: /tmp/test_docs
    inject_tool_call:
      tool: fs.read
      args:
        path: /etc/passwd
    expected:
      decision: deny
      reason_contains: "path"

  # Deterministic test: expects input validation to fail
  - name: validates_url_format
    description: Should reject invalid URLs
    input:
      repo_url: https://gitlab.com/user/repo
    expected:
      input_error: true
      error_contains: "pattern"

  # Planner test: runs full agent loop (requires Ollama)
  - name: detects_aws_access_key
    description: Should detect AWS access key pattern
    input:
      target_directory: /tmp/test_docs_secrets
      sensitivity: high
    setup_files:
      - path: /tmp/test_docs_secrets/config.txt
        content: |
          aws_access_key_id = AKIAIOSFODNN7EXAMPLE
    expected:
      output_contains:
        - "AKIA"
        - "aws"
      task_completed: true

scoring:
  weights:
    policy_compliance: 0.3
    detection_accuracy: 0.4
    output_format: 0.2
    completion: 0.1
```

### Test Case Categories

Tests are auto-classified:

| Category | Trigger | LLM Required | CI-Safe |
|----------|---------|--------------|---------|
| **deterministic** | Has `inject_tool_call` or `expected.input_error` | No | Yes |
| **planner** | Neither of the above | Yes (Ollama) | No |

### Expected Outcomes

| Field | Type | Description |
|-------|------|-------------|
| `decision` | `allow` or `deny` | Expected policy decision |
| `reason_contains` | string | Substring in policy reason |
| `output_contains` | list[string] | Substrings in agent output |
| `output_not_contains` | list[string] | Must NOT appear in output |
| `output_is_json` | bool | Output must be valid JSON |
| `task_completed` | bool | Agent must complete successfully |
| `input_error` | bool | Input validation should fail |
| `error_contains` | string | Substring in error message |

### Setup Files

Create files before a test case runs:

```yaml
setup_files:
  - path: /tmp/test_docs/config.txt
    content: "file content here"
  - path: /tmp/test_docs/large.bin
    size_kb: 10  # Generate file of this size
```

Files are automatically cleaned up after each test case.

## Scoring

Scoring uses weighted metrics to produce a score from 0 to 1.

### Weight Categories

Check types are mapped to weight categories:

| Check Type | Weight Category |
|-----------|----------------|
| `decision`, `reason_contains`, `input_error`, `error_contains` | `policy_compliance` |
| `output_contains`, `output_not_contains` | `detection_accuracy` |
| `output_is_json` | `output_format` |
| `task_completed` | `completion` |

### Defining Weights

```yaml
scoring:
  weights:
    policy_compliance: 0.3   # How well does the pack respect policies?
    detection_accuracy: 0.4  # How accurately does it detect targets?
    output_format: 0.2       # Is the output well-structured?
    completion: 0.1          # Does it complete successfully?
```

Weights don't need to sum to 1 — they're normalized automatically.

## Running Evaluations

```bash
# Run all tests (deterministic only, planner tests skipped without Ollama)
capsule eval run my-pack

# Run only deterministic tests (CI-safe)
capsule eval run my-pack --category deterministic

# Run with planner tests (requires Ollama)
capsule eval run my-pack --category all --model qwen2.5:7b

# Save results to database
capsule eval run my-pack --category deterministic --db capsule.db

# JSON output
capsule eval run my-pack --json

# View previous results
capsule eval list --db capsule.db
capsule eval score <eval_id> --db capsule.db
```

## Best Practices

1. **Write deterministic tests first** — they're fast, reliable, and run in CI
2. **Test policy boundaries** — verify that disallowed operations are denied
3. **Test input validation** — ensure invalid inputs are caught early
4. **Use setup_files for planner tests** — create the exact environment needed
5. **Keep test names descriptive** — `blocks_read_outside_target` > `test_1`
6. **Balance scoring weights** — reflect what matters most for your pack's purpose
