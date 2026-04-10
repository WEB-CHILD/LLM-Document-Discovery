# Reproducible Demo Pipeline Implementation Plan

**Goal:** `llm-discovery fetch` downloads 5 Kidlink/Kidpub pages from Internet Archive and converts to markdown corpus files.

**Architecture:** fetch.py parses IA URLs to extract timestamp and original URL, fetches raw HTML via the Wayback Machine's `id_` endpoint (`https://web.archive.org/web/{timestamp}id_/{url}` — returns original content without Wayback rewriting), converts HTML to markdown with markdownify, and writes files with `{timestamp}/{url}` header using atomic writes. The CDX API is used only to verify the snapshot exists before fetching. This is simpler and more reliable than WARC range-request parsing.

**Tech Stack:** requests, markdownify, Typer, Rich

**Scope:** 8 phases from original design (phases 1-8)

**Codebase verified:** 2026-04-10

---

## Acceptance Criteria Coverage

This phase implements and tests:

### reproducible-demo.AC2: Smoke test fetch and process
- **reproducible-demo.AC2.1 Success:** `llm-discovery fetch` produces 5 markdown files with correct `{timestamp}/{url}` header format
- **reproducible-demo.AC2.5 Failure:** `llm-discovery fetch` with unreachable IA URL reports clear error, does not leave partial files
- **reproducible-demo.AC2.6 Edge:** Re-running `llm-discovery fetch` skips already-fetched files (idempotent)

---

<!-- START_SUBCOMPONENT_A (tasks 1-3) -->
<!-- START_TASK_1 -->
### Task 1: Create fetch.py core module

**Verifies:** reproducible-demo.AC2.1, reproducible-demo.AC2.5, reproducible-demo.AC2.6

**Files:**
- Create: `src/llm_discovery/fetch.py`

**Implementation:**

Create `fetch.py` with the following components:

1. **`DEFAULT_DEMO_URLS`** — list of 5 hardcoded Internet Archive URLs:
   - `https://web.archive.org/web/20040701020553/http://www.kidlink.org:80/KIDFORUM/`
   - `https://web.archive.org/web/20040701022600/http://www.kidlink.org:80/KIDPROJ/Capitals97/introductions.html`
   - `https://web.archive.org/web/20040701031153/http://www.kidlink.org:80/KIDPROJ/MCC/mcc0539.html`
   - `https://web.archive.org/web/20040630084635/http://www.kidlink.org:80/spanish/`
   - `https://web.archive.org/web/19970404181846/http://www.kidpub.org:80/kidpub/kidpub-newest.html`

2. **`parse_ia_url(url: str) -> tuple[str, str]`** — Parse an Internet Archive URL into (timestamp, original_url). Expects format `https://web.archive.org/web/{timestamp}/{original_url}`. Raises `ValueError` for non-IA URLs.

3. **`verify_snapshot(original_url: str, timestamp: str) -> bool`** — Query CDX API at `http://web.archive.org/cdx/search/cdx` with parameters: `url={original_url}`, `output=json`, `from={timestamp}`, `to={timestamp}`, `limit=1`. Returns True if a matching snapshot exists, False otherwise. Used as a pre-check before fetching.

4. **`download_html(original_url: str, timestamp: str) -> str`** — Fetch the original HTML from the Wayback Machine via: `https://web.archive.org/web/{timestamp}id_/{original_url}`. The `id_` suffix returns the original content without Wayback Machine's toolbar injection or URL rewriting. Use `requests.get()` with appropriate timeout. Raise `RuntimeError` on HTTP errors (4xx, 5xx). Validate response has HTML content-type.

5. **`html_to_markdown(html: str) -> str`** — Convert HTML to markdown using `markdownify.markdownify(html)`. Return cleaned markdown string.

6. **`make_filename(original_url: str) -> str`** — Create a filesystem-safe filename from the original URL. Strip protocol, replace `/` with `_`, truncate to reasonable length, add `.md` extension. Must be deterministic (same URL = same filename) for idempotency.

7. **`fetch_single(url: str, output_dir: Path) -> Path | None`** — Orchestrate the full pipeline for one URL:
   - Parse IA URL
   - Construct output path from `make_filename(original_url)`
   - Check if output file exists (idempotency — return None if exists)
   - Optionally verify snapshot exists via CDX
   - Download HTML via Wayback Machine `id_` endpoint
   - Convert to markdown
   - Prepend `{timestamp}/{original_url}` header line
   - Atomic write: write to temp file in same directory, then `os.replace()` to final path
   - Return output path

8. **`fetch_corpus(urls: list[str] | None, output_dir: Path) -> list[Path]`** — Fetch all URLs. If `urls` is None, use `DEFAULT_DEMO_URLS`. Create `output_dir` if needed. Call `fetch_single` for each URL. Maintain two separate tracking lists:
   - `written: list[Path]` — new files successfully created this run
   - `failed: list[tuple[str, str]]` — (url, error_message) for URLs that errored
   - Skipped files (already exist, `fetch_single` returns None) go in neither list
   On error for a single URL: append to `failed`, continue to next URL. At end: if `failed` is non-empty, raise `RuntimeError` summarising failures. Return `written` (only newly created files).

**Error handling:** All network errors must be caught per-URL. No partial files on failure (atomic write handles this). Clear error messages including the URL that failed.

**Testing (unit tests with mocked network — no live IA access required):**
- reproducible-demo.AC2.1: Mock `requests.get` to return sample HTML. Test that `fetch_single` produces a markdown file with `{timestamp}/{url}` header line.
- reproducible-demo.AC2.5: Mock `requests.get` to raise `ConnectionError`. Test that error is reported clearly and no partial files remain in the output directory.
- reproducible-demo.AC2.6: Write a file to the output directory matching the expected filename. Test that `fetch_single` returns None (skip) without making any HTTP requests.
- Test `parse_ia_url` with valid and invalid URLs.
- Test `make_filename` produces deterministic, filesystem-safe names.

Integration tests that hit live IA API belong in Task 3, not here.

**Verification:**
Run: `uv run pytest tests/ -k fetch`
Expected: All unit tests pass (no network required)

**Commit:** `feat: add fetch pipeline (Wayback Machine -> HTML -> markdown)`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Wire fetch into CLI

**Files:**
- Modify: `src/llm_discovery/cli.py:13-18` (replace fetch stub)

**Implementation:**

Replace the `fetch` stub with a real implementation that:
1. Imports `fetch_corpus` from `llm_discovery.fetch`
2. Accepts optional `urls` argument (list of IA URLs, defaults to None for demo URLs)
3. Accepts `--output-dir` option (default: `input/demo_corpus`)
4. Uses Rich console for progress output:
   - Print "Fetching N documents from Internet Archive..."
   - Print status for each URL (fetching / skipped / error)
   - Print summary at end ("Fetched X, skipped Y, failed Z")
5. Exit with code 1 if any URLs failed

**Testing:**
- Integration test: verify CLI exit codes and output messages
- Test that `--help` for fetch shows correct argument docs

**Verification:**
Run: `uv run llm-discovery fetch --help`
Expected: Shows urls argument and --output-dir option

**Commit:** `feat: wire fetch command into CLI with Rich progress`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: End-to-end fetch verification

**Files:**
- Test: `tests/test_fetch.py` (integration)

**Implementation:**

Write an integration test that:
1. Calls `fetch_corpus` with a single known-good demo URL
2. Verifies the output file exists
3. Verifies the first line matches `{timestamp}/{url}` format
4. Verifies the content is valid markdown (non-empty, printable characters)
5. Calls `fetch_corpus` again with the same URL
6. Verifies the file was skipped (idempotency)

This test hits the live Internet Archive API. Mark it appropriately so it can be skipped in CI without network access.

**Testing:**
- reproducible-demo.AC2.1: Verify header format in output file
- reproducible-demo.AC2.6: Verify idempotent skip on re-run

**Verification:**
Run: `uv run pytest tests/test_fetch.py -v`
Expected: All tests pass (requires network access)

**Commit:** `test: add integration tests for WARC fetch pipeline`
<!-- END_TASK_3 -->
<!-- END_SUBCOMPONENT_A -->
