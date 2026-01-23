# Pack System Implementation Checkpoint

**Date:** 2026-01-23
**Version:** v0.2.0-alpha.3 (in progress)
**Status:** Anti-hallucination fixes implemented, ready for testing

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

- **655 tests passing** (21 new validation tests)
- `tests/unit/test_pack_manifest.py` - 31 tests
- `tests/unit/test_pack_loader.py` - 39 tests
- `tests/integration/test_pack_integration.py` - 27 tests
- `tests/unit/test_agent_validation.py` - 21 tests (NEW)

---

## Issues Fixed (2026-01-23)

### Issue 1: KeyError 'tool' on Second Iteration ✓

**Root Cause:** Validation in `json_repair.py` accepted `{"done": false}` as valid, but `ollama.py` only handled `done: true` before accessing `parsed["tool"]`.

**Fix:** `src/capsule/planner/json_repair.py:256-261`
- `done: true` → valid done signal
- `done: false` → falls through to require `tool` field

### Issue 2: Model Hallucinating File Paths ✓

**Root Cause:**
1. System prompt contained example file paths that SLMs copied
2. Prompt was too long (108 lines) causing SLMs to lose focus
3. No validation that output referenced actual files

**Fixes Applied:**

1. **Rewrote system prompt** (`packs/local_doc_auditor/prompts/system.txt`)
   - Reduced from 108 lines to 54 lines
   - Anti-hallucination rules at TOP of prompt
   - Removed example file paths
   - Clear step-by-step workflow
   - Explicit "NEVER fabricate paths" instruction

2. **Added ExecutionContext tracking** (`src/capsule/agent/loop.py`)
   - Tracks files read via `fs.read`
   - Tracks commands run via `shell.run`
   - Records all tool calls for validation

3. **Added output validation** (`src/capsule/agent/validation.py`)
   - Extracts file paths from model output
   - Compares against actually accessed files
   - Reports hallucinated paths as warnings
   - Integrated into CLI display

---

## Key Code Locations

### Pack prompt (rewritten)
```
packs/local_doc_auditor/prompts/system.txt
```
- 54 lines (was 108)
- Anti-hallucination rules first
- No example file paths

### ExecutionContext tracking
```
src/capsule/agent/loop.py:97-144
```
- `ExecutionContext` dataclass
- `record_tool_call()` method
- `was_file_accessed()` validation

### Output validation
```
src/capsule/agent/validation.py
```
- `extract_file_paths()` - finds paths in output
- `validate_output()` - compares to accessed files
- `format_validation_result()` - display helper

### CLI integration
```
src/capsule/cli.py:1884-1897
```
- Validates output after agent run
- Displays warnings for hallucinated paths

---

## Next Steps

1. **Test the fix** with actual model:
   ```bash
   capsule pack run local-doc-auditor --input target_directory=docs --model qwen2.5:7b --verbose
   ```

2. **If hallucinations persist:**
   - Try larger model (qwen2.5:14b)
   - Add more explicit grounding in prompt
   - Consider model-specific prompt tuning

3. **For v0.2.0-beta.1:**
   - Update repo-analyst pack with same anti-hallucination patterns
   - Add pack authoring documentation
   - Consider adding `--strict` flag for validation

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
