# Reproducible Demo Pipeline Implementation Plan

**Goal:** Clean, installable repo with dependencies, Typer CLI skeleton, schema, prompts, and system prompt — verified and committed.

**Architecture:** Python package using Hatch build system with `src/` layout. Typer CLI as entry point. vLLM as optional GPU-only dependency. All scaffolding files already created by previous work session; this phase verifies and commits them.

**Tech Stack:** Python 3.12+, uv, Typer, Rich, warcio, markdownify, requests, pydantic, pyyaml, datasette, langchain-text-splitters, openai

**Scope:** 8 phases from original design (phases 1-8)

**Codebase verified:** 2026-04-10

---

## Acceptance Criteria Coverage

This phase implements and tests:

### reproducible-demo.AC1: Clean public repo
- **reproducible-demo.AC1.1 Success:** Clone + `uv sync` + `uv run llm-discovery --help` works with no manual setup beyond HF token
- **reproducible-demo.AC1.2 Success:** Repo contains no .db files, .jsonl files, sync-conflict files, or embargoed data
- **reproducible-demo.AC1.3 Failure:** `uv sync` on a machine without GPU still succeeds (vllm is optional runtime dep, not install-time)

---

<!-- START_TASK_1 -->
### Task 1: Verify and finalise pyproject.toml

**Files:**
- Verify: `pyproject.toml`

**Step 1: Verify pyproject.toml contents**

Confirm the following are present and correct:
- `[project]` section: name = "llm-discovery", version = "0.1.0", requires-python = ">=3.12"
- `dependencies`: typer>=0.12.0, rich>=14.0.0, warcio>=1.7.0, markdownify>=0.13.0, requests>=2.32.0, pydantic>=2.0, pyyaml>=6.0, datasette>=0.65.1, langchain-text-splitters>=1.1.0, openai>=2.7.1
- `[project.optional-dependencies]`: gpu = ["vllm>=0.11.0"], dev = ["pytest>=9.0.1"]
- `[project.scripts]`: llm-discovery = "llm_discovery.cli:app"
- `[build-system]`: hatchling
- `[tool.hatch.build]`: sources = ["src"]
- `[tool.pytest.ini_options]`: markers for gpu, testpaths = ["tests"]

**Step 2: Verify operational**

Run: `uv sync`
Expected: Completes without errors. vllm NOT installed (optional).

Run: `uv run llm-discovery --help`
Expected: Shows 6 subcommands: fetch, validate, deploy, status, retrieve, run

**Step 3: No commit yet** — commit after all files verified in Task 6.
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Verify and finalise .gitignore

**Files:**
- Verify/Modify: `.gitignore`

**Step 1: Verify .gitignore includes all required patterns**

Required entries:
```
# Data files
*.db
*.jsonl
input/

# Logs
*.log

# Python
__pycache__/
*.pyc
*.pyo
.venv/
dist/
build/
*.egg-info/

# Testing
.pytest_cache/
.coverage
htmlcov/

# Environment
.env
.envrc

# Syncthing
.stfolder/

# IDE
.vscode/
.idea/
```

**Step 2: Add .worktrees/ if missing**

If `.worktrees/` is not in .gitignore, add it under a "# Worktrees" section. This prevents accidental commit of worktree contents if worktrees are used later.

**Step 3: No commit yet.**
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Verify src/llm_discovery/ package

**Files:**
- Verify: `src/llm_discovery/__init__.py`
- Verify: `src/llm_discovery/cli.py`

**Step 1: Verify __init__.py**

Should contain a minimal docstring. No imports needed at this stage.

**Step 2: Verify cli.py**

Confirm Typer app with 6 stub subcommands. Each stub should:
- Print a "not yet implemented" message
- Raise `typer.Exit(1)`

Subcommands required: `fetch`, `validate`, `deploy`, `status`, `retrieve`, `run`.

`fetch` should accept optional URL arguments. `validate`, `deploy`, `status`, `retrieve` should accept `--platform` option. `run` should accept `--platform` with default "local".

**Step 3: No commit yet.**
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Verify schema.sql and system_prompt.txt

**Files:**
- Verify: `schema.sql`
- Verify: `system_prompt.txt`

**Step 1: Verify schema.sql**

Confirm the following tables exist:
- `result` (result_id, filepath, content, content_sha256, part_number, parent_result_id)
- `category` (category_id, category_filename, category_name, category_description, prompt_sha256)
- `result_category` (result_id, category_id, match, reasoning_trace)
- `result_category_blockquote` (blockquote_id, result_id, category_id, blockquote)
- `excluded_file` (filepath, reason, content_sha256)
- `run_stats` (run_id, started_at, finished_at, model, pairs_processed, etc.)

Confirm views: processing_summary, result_summary, blockquotes_by_category, category_matches, document_category_aggregate, document_blockquotes.

Confirm indexes on: result_category(match), result_category(category_id), result_category_blockquote(result_id, category_id), result(filepath), result(content_sha256), result(parent_result_id), result(part_number), category(category_filename), category(prompt_sha256).

**Step 2: Verify system_prompt.txt**

Confirm it contains instructions for the LLM to extract blockquotes with JSON output format (match: yes/maybe/no, blockquotes array). Must mention English, Danish, Korean language support.

**Step 3: No commit yet.**
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Verify and reconcile prompts/*.yaml

**Files:**
- Verify: `prompts/*.yaml` (21 files currently present)

**Step 1: Inventory existing prompt files**

Run: `ls prompts/*.yaml | sort`

Expected: 21 files with numbers 02-11, 13-23. Missing: 01 and 12.

**Step 2: Verify 21 categories is correct**

FirstRun also has exactly 21 files (same numbers present: 02-11, 13-23). Categories 01 and 12 were intentionally excluded from the original research design. The design plan's "22 categories" is incorrect — the correct count is 21.

**NOTE:** The design's AC2.4 says "5 documents x 22 categories = 110 result_category rows." This should be "5 x 21 = 105 result_category rows." Confirm this with the project owner during implementation. All implementation plan phases use 21 categories as the expected count.

**Step 3: Verify each YAML file has required structure**

Each YAML should contain at minimum: category_name, category_description, and prompt text.

**Step 4: No commit yet.**
<!-- END_TASK_5 -->

<!-- START_TASK_6 -->
### Task 6: Operational verification and commit

**Step 1: Clean verification**

Run: `uv sync`
Expected: Installs all dependencies successfully.

Run: `uv run llm-discovery --help`
Expected: Shows all 6 subcommands.

Run: `uv run python -c "import llm_discovery; print('OK')"`
Expected: Prints "OK".

Verify no .db, .jsonl, or embargoed data files present:
Run: `find . -name '*.db' -o -name '*.jsonl' | grep -v .venv`
Expected: No output.

**Step 2: Commit all Phase 1 scaffolding**

```bash
git add .gitignore pyproject.toml uv.lock schema.sql system_prompt.txt \
  src/llm_discovery/__init__.py src/llm_discovery/cli.py \
  prompts/
git commit -m "feat: add project scaffolding with Typer CLI skeleton

Includes pyproject.toml with dependencies (vllm optional),
uv.lock for reproducible installs, Typer CLI with stub
subcommands, SQLite schema, system prompt, and category
prompt YAML files from FirstRun."
```

**NOTE:** `uv.lock` must be committed for reproducibility — it pins exact dependency versions so collaborators get identical environments.

**Step 3: Verify commit**

Run: `git status`
Expected: Clean working tree (all scaffolding committed).

Run: `uv run llm-discovery --help`
Expected: Still works after commit.
<!-- END_TASK_6 -->
