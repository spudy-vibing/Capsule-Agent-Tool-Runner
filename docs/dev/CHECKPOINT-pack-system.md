# Pack System Implementation Checkpoint

**Date:** 2026-01-22
**Version:** v0.2.0-alpha.3 (in progress)
**Status:** Debugging pack run integration

---

## Completed Work

### Core Infrastructure ✓

| File | Description |
|------|-------------|
| `src/capsule/pack/__init__.py` | Module exports |
| `src/capsule/pack/manifest.py` | Pydantic models: PackInputSchema, PackOutputSchema, PackManifest |
| `src/capsule/pack/loader.py` | PackLoader class for loading/validating packs |
| `src/capsule/errors.py` | Added pack error codes (7001-7006) |
| `pyproject.toml` | Added `jinja2>=3.0.0` dependency |

### CLI Commands ✓

```bash
capsule pack list [--json]           # List available packs
capsule pack info <name> [--json]    # Show pack details
capsule pack validate <path>         # Validate pack structure
capsule pack run <name> [options]    # Execute pack
```

**pack run options:**
- `--input key=value` (repeatable)
- `--policy <path>` - Override policy
- `--mode agent|yaml` - Execution mode
- `--model <name>` - Model for planner
- `--max-iterations N`
- `--json`, `--verbose`, `--debug`

### Built-in Packs ✓

**local-doc-auditor** (`packs/local_doc_auditor/`)
- Purpose: Scan directories for secrets, credentials, PII
- Tools: fs.read, shell.run (find, ls only)
- Inputs: target_directory, file_patterns, sensitivity, output_format, max_file_size_kb

**repo-analyst** (`packs/repo_analyst/`)
- Purpose: Analyze GitHub repository health metrics
- Tools: http.get
- Inputs: repo_url, include_sections, output_format

### Tests ✓

- **634 tests passing**
- `tests/unit/test_pack_manifest.py` - 31 tests
- `tests/unit/test_pack_loader.py` - 39 tests
- `tests/integration/test_pack_integration.py` - 27 tests

---

## Current Issue

### Symptom

```bash
capsule pack run local-doc-auditor --input target_directory=src --model qwen2.5:7b
```

- First iteration: **SUCCESS** (shell.run executes)
- Second iteration: **ERROR** `'tool'` (KeyError)

### Investigation Done

1. **Changed OllamaPlanner to use `.replace()` instead of `.format()`**
   - File: `src/capsule/planner/ollama.py:195-198`
   - Reason: `.format()` interprets all `{...}` as placeholders, breaking regex patterns like `{16}`

2. **Restructured combined system prompt**
   - Put JSON format instructions at the TOP (models pay more attention to start)
   - File: `src/capsule/cli.py:1825-1846`

3. **Verified model returns valid JSON when tested directly**
   - Direct Ollama API calls work correctly
   - Model returns `{"tool": "...", "args": {...}}` as expected

4. **The KeyError `'tool'` source not yet found**
   - Not from `.format()` (we use `.replace()` now)
   - Not from JSON parsing (validation checks for 'tool' key)
   - Occurs on second iteration, after first succeeds

### Suspects

- Something in the history processing on iteration 2
- Possibly in `_build_prompt` or response parsing
- Need to add debug logging to trace exact location

---

## Key Code Locations

### Pack prompt integration (CLI)
```
src/capsule/cli.py:1821-1856
```
- Builds `combined_system_prompt` with pack prompt + JSON format instructions
- Passes to `OllamaConfig.system_prompt`

### OllamaPlanner prompt building
```
src/capsule/planner/ollama.py:186-238
```
- `_build_prompt()` creates messages for Ollama
- Uses `.replace()` for `{tool_schemas}` and `{policy_summary}`

### Agent loop iteration
```
src/capsule/agent/loop.py:311-443
```
- `_run_iteration()` calls planner, evaluates policy, executes tool

---

## Next Steps

1. Add debug logging to trace where `'tool'` KeyError originates
2. Check if error is in:
   - Response parsing (`_parse_response`)
   - History building (`_build_prompt` with history)
   - Somewhere else in agent loop
3. Test with simpler prompts to isolate
4. Consider testing with different models

---

## Commands to Resume

```bash
# Run tests
cd "/Users/shubhamupadhyay/Documents/Capsule - Agent tool runner"
python -m pytest tests/ --tb=short

# Test pack run (use 7b model, 0.5b too small)
capsule pack run local-doc-auditor --input target_directory=docs --model qwen2.5:7b --verbose

# Quick Ollama test
curl http://localhost:11434/api/tags  # List models
```

---

## Reference: Original Plan

See: `.claude/plans/async-riding-eich.md`
