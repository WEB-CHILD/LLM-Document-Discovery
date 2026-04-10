# Reproducible Demo Pipeline Implementation Plan

**Goal:** Database preparation, document processing, and results import working as package modules, callable via Typer CLI subcommands.

**Architecture:** Four modules adapted from FirstRun (`/home/brian/people/Helle-Aarhus/20251104-FirstRun/`): prep_db, preflight_check, unified_processor, import_results. Each module exposes library functions; CLI subcommands in cli.py wrap them. No argparse — Typer is the single CLI interface. HPC scripts call `llm-discovery prep-db` etc.

**Tech Stack:** SQLite, pyyaml, langchain-text-splitters (RecursiveCharacterTextSplitter), Rich, Typer, urllib.request (for vLLM API)

**Scope:** 8 phases from original design (phases 1-8)

**Codebase verified:** 2026-04-10

---

## Acceptance Criteria Coverage

This phase implements and tests:

### reproducible-demo.AC2: Smoke test fetch and process
- **reproducible-demo.AC2.2 Success:** Each fetched file passes `preflight_check` validation
- **reproducible-demo.AC2.3 Success:** Full pipeline (prep_db -> vLLM -> unified_processor -> import_results) completes on the 5 demo documents
- **reproducible-demo.AC2.4 Success:** `corpus.db` contains results for all 5 documents x 21 categories = 105 result_category rows (design says 22/110 but FirstRun confirms only 21 categories exist — numbers 01 and 12 intentionally excluded)

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Adapt prep_db.py from FirstRun

**Files:**
- Create: `src/llm_discovery/prep_db.py` (adapted from `/home/brian/people/Helle-Aarhus/20251104-FirstRun/prep_db.py`)
- Modify: `src/llm_discovery/cli.py` (add `prep-db` subcommand)

**Implementation:**

Copy `prep_db.py` from FirstRun and adapt:

1. **Remove argparse** — extract core logic into callable functions:
   - `create_db(db_path: Path, schema_path: Path) -> None` — creates DB from schema.sql if not exists
   - `sync_categories(db_path: Path, prompts_dir: Path, quiet: bool = False) -> int` — syncs category table with prompts/*.yaml
   - `sync_documents(db_path: Path, input_dir: Path, quiet: bool = False) -> int` — syncs result table with input directory
   - `run_prep_db(db_path: Path, input_dir: Path, prompts_dir: Path, schema_path: Path, quiet: bool = False) -> None` — orchestrates all steps

2. **Update default paths:**
   - `POC-prompts/` → `prompts/`
   - `input/markdown_corpus` → `input/demo_corpus`
   - Schema path: `schema.sql` (project root)
   - All paths should be relative to the package or configurable via function args

3. **Add Typer subcommand** in cli.py:
   ```python
   @app.command()
   def prep_db(
       db: Path = typer.Option("corpus.db", help="Database path"),
       input_dir: Path = typer.Option("input/demo_corpus", help="Corpus directory"),
       prompts_dir: Path = typer.Option("prompts", help="Prompts directory"),
       quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress per-file output"),
   ) -> None:
       """Create and populate the corpus database from documents and prompts."""
   ```

4. **Keep all existing logic:** SHA-256 change detection, document splitting (RecursiveCharacterTextSplitter), Rich output, per-file transaction scope. These are production-validated.

**Testing:**
- reproducible-demo.AC2.4: Test that prep_db creates correct number of result and category rows
- Test that `llm-discovery prep-db --help` shows correct options

**Verification:**
Run: `uv run llm-discovery prep-db --help`
Expected: Shows --db, --input-dir, --prompts-dir, --quiet options

**Commit:** `feat: adapt prep_db from FirstRun with Typer CLI`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Adapt preflight_check.py from FirstRun

**Files:**
- Create: `src/llm_discovery/preflight_check.py` (adapted from `/home/brian/people/Helle-Aarhus/20251104-FirstRun/preflight_check.py`)
- Modify: `src/llm_discovery/cli.py` (add `preflight` subcommand)

**Implementation:**

Copy `preflight_check.py` from FirstRun and adapt:

1. **Remove argparse** — extract core logic:
   - `check_document(content: str) -> tuple[bool, str]` — returns (valid, reason)
   - `run_preflight(db_path: Path, delete: bool = False) -> dict` — scans DB, returns stats

2. **Add Typer subcommand** in cli.py:
   ```python
   @app.command()
   def preflight(
       db: Path = typer.Option("corpus.db", help="Database path"),
       delete: bool = typer.Option(False, help="Delete problematic documents"),
   ) -> None:
       """Validate documents in corpus database."""
   ```

3. **Keep validation logic:** binary magic bytes detection, minimum body length, printable character ratio, content body extraction after URL header. All production-validated.

**Testing:**
- reproducible-demo.AC2.2: Test that valid markdown documents pass preflight check
- Test that binary content is rejected with clear reason
- Test that empty content is rejected

**Verification:**
Run: `uv run llm-discovery preflight --help`
Expected: Shows --db and --delete options

**Commit:** `feat: adapt preflight_check from FirstRun with Typer CLI`
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-4) -->
<!-- START_TASK_3 -->
### Task 3: Adapt unified_processor.py from FirstRun

**Files:**
- Create: `src/llm_discovery/unified_processor.py` (adapted from `/home/brian/people/Helle-Aarhus/20251104-FirstRun/unified_processor.py`)
- Modify: `src/llm_discovery/cli.py` (add `process` subcommand)

**Implementation:**

Copy `unified_processor.py` from FirstRun and adapt:

1. **Remove argparse** — extract core logic:
   - `run_processor(db_path: Path, output_dir: Path, server_url: str, system_prompt_path: Path, concurrency: int, limit: int | None, ...) -> dict` — runs the streaming processor, returns stats

2. **Add Typer subcommand** in cli.py:
   ```python
   @app.command()
   def process(
       db: Path = typer.Option("corpus.db", help="Database path"),
       output_dir: Path = typer.Option("out", help="JSON output directory"),
       server_url: str = typer.Option("http://localhost:8000", help="vLLM server URL"),
       concurrency: int = typer.Option(128, help="Number of concurrent workers"),
       limit: int = typer.Option(None, help="Limit number of pairs to process"),
   ) -> None:
       """Run LLM classification on unprocessed document-category pairs."""
   ```

3. **Update default paths:**
   - System prompt: find via package-relative path or explicit option
   - Output dir: `out/` (default)

4. **Keep all streaming architecture:** Reader thread with fetchmany(), bounded work queue (100 items), worker threads with ThreadPoolExecutor, atomic JSON file writes (temp + rename), crash-safe resumability, Rich progress display. This code is production-validated at 384 concurrency.

5. **Keep urllib.request** for vLLM API calls — the processor needs fine-grained control over request construction, timeouts, and error handling that the openai SDK's abstractions would complicate.

**Testing:**
- reproducible-demo.AC2.3: Integration test requiring a running vLLM server (mark with `@pytest.mark.gpu`)
- Unit test for atomic write logic (can test without GPU)
- Unit test for request body construction

**Verification:**
Run: `uv run llm-discovery process --help`
Expected: Shows --db, --output-dir, --server-url, --concurrency, --limit options

**Commit:** `feat: adapt unified_processor from FirstRun with Typer CLI`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Adapt import_results.py from FirstRun

**Files:**
- Create: `src/llm_discovery/import_results.py` (adapted from `/home/brian/people/Helle-Aarhus/20251104-FirstRun/import_results.py`)
- Modify: `src/llm_discovery/cli.py` (add `import-results` subcommand)

**Implementation:**

Copy `import_results.py` from FirstRun and adapt:

1. **Remove argparse** — extract core logic:
   - `import_record(cursor: sqlite3.Cursor, data: dict, stats: dict) -> int` — imports a single record (keep as-is)
   - `run_import(db_path: Path, input_dir: Path) -> dict` — reads JSON files, imports to DB, returns stats

2. **Add Typer subcommand** in cli.py:
   ```python
   @app.command()
   def import_results(
       db: Path = typer.Option("corpus.db", help="Database path"),
       input_dir: Path = typer.Option("out", help="JSON output directory to import from"),
   ) -> None:
       """Import JSON result files into corpus database."""
   ```

3. **Keep import logic:** Reads both individual `r*_c*.json` files and consolidated `results.jsonl`. INSERT OR IGNORE for idempotency. Blockquote insertion. Rich progress and statistics.

**Testing:**
- reproducible-demo.AC2.3: Test that valid JSON files are imported correctly
- Test idempotency (importing same file twice produces no duplicates)
- Test that malformed JSON is handled gracefully

**Verification:**
Run: `uv run llm-discovery import-results --help`
Expected: Shows --db and --input-dir options

**Commit:** `feat: adapt import_results from FirstRun with Typer CLI`
<!-- END_TASK_4 -->
<!-- END_SUBCOMPONENT_B -->

<!-- START_TASK_5 -->
### Task 5: Create tests directory and initial test suite

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_prep_db.py`
- Create: `tests/test_preflight.py`
- Create: `tests/test_import_results.py`

**Verifies:** reproducible-demo.AC2.2, reproducible-demo.AC2.4

**Implementation:**

1. **conftest.py** — shared fixtures:
   - `tmp_db` — creates a temporary SQLite DB from schema.sql
   - `sample_corpus_dir` — creates a temp directory with sample markdown files (with `{timestamp}/{url}` header format)
   - `sample_prompts_dir` — creates a temp directory with a subset of prompt YAML files

2. **test_prep_db.py:**
   - Test that `create_db` creates all expected tables
   - Test that `sync_categories` populates category table from YAML files
   - Test that `sync_documents` populates result table from markdown files
   - Test that large documents are split correctly
   - Test SHA-256 change detection (re-sync doesn't duplicate)

3. **test_preflight.py:**
   - Test that valid markdown passes (AC2.2)
   - Test that binary content (PNG magic bytes) is rejected
   - Test that empty content is rejected
   - Test that low printable ratio is rejected

4. **test_import_results.py:**
   - Test that valid JSON record is imported correctly
   - Test INSERT OR IGNORE idempotency
   - Test that blockquotes are inserted
   - Test that malformed JSON is handled gracefully

**Testing:**
All tests should run without GPU or network access. Use real SQLite (no mocking) with temporary databases.

**Verification:**
Run: `uv run pytest tests/ -v`
Expected: All tests pass

**Commit:** `test: add test suite for core pipeline modules`
<!-- END_TASK_5 -->
