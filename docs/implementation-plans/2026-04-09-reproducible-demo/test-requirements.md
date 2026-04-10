# Test Requirements: Reproducible Demo Pipeline

Maps each acceptance criterion to specific automated tests or human verification steps.

**Corrected counts:** 21 categories / 105 result_category rows (categories 01 and 12 intentionally excluded from the research design). The design plan's "22 categories / 110 rows" is incorrect.

**Corrected fetch architecture:** The fetch pipeline uses Wayback Machine `id_` endpoint (`https://web.archive.org/web/{timestamp}id_/{url}`) to retrieve original HTML without Wayback toolbar injection. CDX API is used only for snapshot existence verification, not for WARC range requests.

---

## reproducible-demo.AC1: Clean public repo

### reproducible-demo.AC1.1 -- Clone + uv sync + llm-discovery --help works

| Field | Value |
|-------|-------|
| Test type | Integration |
| Test file | `tests/test_scaffolding.py` |
| Phase | 1 (Task 6) |

**Automated tests:**

1. `test_uv_sync_succeeds` -- Run `uv sync` in a subprocess from the repo root. Assert exit code 0. Assert stderr does not contain "error" (case-insensitive).

2. `test_cli_help_shows_subcommands` -- Run `uv run llm-discovery --help` in a subprocess. Assert exit code 0. Assert output contains all expected subcommand names: `fetch`, `validate`, `deploy`, `status`, `retrieve`, `run`. (Phase 1 stubs; later phases add `prep-db`, `preflight`, `process`, `import-results`.)

3. `test_package_importable` -- `import llm_discovery` succeeds without error.

### reproducible-demo.AC1.2 -- No .db, .jsonl, sync-conflict, or embargoed data in repo

| Field | Value |
|-------|-------|
| Test type | Unit |
| Test file | `tests/test_scaffolding.py` |
| Phase | 1 (Task 6) |

**Automated tests:**

1. `test_no_data_files_in_repo` -- Walk the repo tree (excluding `.venv/`, `.git/`). Assert no files match `*.db`, `*.jsonl`, `*.sync-conflict-*`. Assert no `input/` directory exists in the tracked tree (check via `git ls-files`).

2. `test_gitignore_covers_data_patterns` -- Read `.gitignore`. Assert it contains entries for `*.db`, `*.jsonl`, `input/`.

### reproducible-demo.AC1.3 -- uv sync succeeds without GPU

| Field | Value |
|-------|-------|
| Test type | Integration |
| Test file | `tests/test_scaffolding.py` |
| Phase | 1 (Task 1) |

**Automated tests:**

1. `test_vllm_not_in_base_dependencies` -- Parse `pyproject.toml`. Assert `vllm` appears only in `[project.optional-dependencies]` under the `gpu` extra, not in the base `dependencies` list.

2. `test_uv_sync_without_gpu_extra` -- Run `uv sync` (without `--extra gpu`). Assert exit code 0. Run `uv pip list` and assert `vllm` is NOT in the installed packages.

---

## reproducible-demo.AC2: Smoke test fetch and process

### reproducible-demo.AC2.1 -- fetch produces 5 markdown files with correct header format

| Field | Value |
|-------|-------|
| Test type | Unit + Integration |
| Test file | `tests/test_fetch.py` |
| Phase | 2 (Tasks 1, 3) |

**Automated tests (unit, mocked network):**

1. `test_parse_ia_url_valid` -- Call `parse_ia_url` with each of the 5 default demo URLs. Assert each returns a `(timestamp, original_url)` tuple. Assert timestamp is numeric. Assert original_url starts with `http`.

2. `test_parse_ia_url_invalid` -- Call `parse_ia_url` with non-IA URLs (e.g., `https://example.com`, `https://web.archive.org/web/` with no timestamp). Assert `ValueError` raised.

3. `test_make_filename_deterministic` -- Call `make_filename` twice with the same URL. Assert identical output. Assert output ends with `.md`. Assert output contains no `/` characters.

4. `test_fetch_single_produces_header` -- Mock `requests.get` to return sample HTML (`<html><body><p>Hello</p></body></html>`). Call `fetch_single`. Read the output file. Assert first line matches pattern `{timestamp}/{original_url}` where timestamp and original_url match the parsed input.

5. `test_fetch_single_produces_markdown` -- Same mock as above. Assert output file content (after header line) contains converted markdown, not raw HTML tags.

6. `test_fetch_corpus_produces_five_files` -- Mock `requests.get` to return sample HTML for each URL. Call `fetch_corpus(None, tmp_dir)`. Assert exactly 5 `.md` files exist in `tmp_dir`.

**Automated tests (integration, live network):**

7. `test_fetch_single_live` -- Mark with `@pytest.mark.network`. Call `fetch_single` with one known-good demo URL. Assert output file exists. Assert first line matches `{timestamp}/{url}` pattern. Assert content length > 100 characters.

8. `test_fetch_all_demo_urls_live` -- Mark with `@pytest.mark.network`. Call `fetch_corpus(None, tmp_dir)`. Assert 5 files produced. Assert each has valid header line.

### reproducible-demo.AC2.2 -- Each fetched file passes preflight_check

| Field | Value |
|-------|-------|
| Test type | Unit |
| Test file | `tests/test_preflight.py` |
| Phase | 3 (Task 2, Task 5) |

**Automated tests:**

1. `test_valid_markdown_passes_preflight` -- Create a sample markdown string with `{timestamp}/{url}` header followed by prose text. Call `check_document(content)`. Assert returns `(True, ...)`.

2. `test_binary_content_rejected` -- Create content starting with PNG magic bytes (`\x89PNG`). Call `check_document(content)`. Assert returns `(False, reason)` where reason mentions binary.

3. `test_empty_content_rejected` -- Call `check_document("")`. Assert returns `(False, reason)`.

4. `test_low_printable_ratio_rejected` -- Create content with >50% non-printable characters. Assert `check_document` returns `(False, reason)`.

5. `test_demo_corpus_files_pass_preflight` -- Mark with `@pytest.mark.network` (requires fetched corpus). For each file in `input/demo_corpus/`, read content and call `check_document`. Assert all return `(True, ...)`. This is the direct AC2.2 verification -- it confirms the actual fetched demo files pass validation.

### reproducible-demo.AC2.3 -- Full pipeline completes on 5 demo documents

| Field | Value |
|-------|-------|
| Test type | E2E |
| Test file | `tests/test_pipeline_e2e.py` |
| Phase | 3 (Tasks 1-5), Phase 7 (Task 1) |

**Automated tests (unit, no GPU):**

1. `test_prep_db_creates_tables` -- Call `create_db` with a temp DB and `schema.sql`. Query `sqlite_master`. Assert all 6 tables exist: `result`, `category`, `result_category`, `result_category_blockquote`, `excluded_file`, `run_stats`.

2. `test_prep_db_syncs_categories` -- Create temp DB, call `sync_categories` with the real `prompts/` directory. Query `SELECT COUNT(*) FROM category`. Assert exactly 21 rows.

3. `test_prep_db_syncs_documents` -- Create temp DB and a temp corpus dir with 5 sample markdown files (with header lines). Call `sync_documents`. Query `SELECT COUNT(*) FROM result`. Assert >= 5 rows (may be more if documents are split).

4. `test_prep_db_sha256_idempotent` -- Sync documents twice. Assert row count unchanged on second sync.

5. `test_import_results_valid_json` -- Create a temp DB with schema, insert a result and category row. Write a valid `r1_c1.json` file with `{"match": "yes", "reasoning_trace": "test", "blockquotes": ["quote1"]}`. Call `run_import`. Assert `result_category` has 1 row. Assert `result_category_blockquote` has 1 row.

6. `test_import_results_idempotent` -- Import the same JSON file twice. Assert row count unchanged (INSERT OR IGNORE).

7. `test_import_results_malformed_json` -- Write an invalid JSON file. Call `run_import`. Assert it handles gracefully (no crash, logged error).

**Human verification (GPU required):**

| Item | Detail |
|------|--------|
| Criterion | Full pipeline with live vLLM server |
| Why not automated | Requires GPU hardware, model download (gpt-oss-120b is ~30GB), and 4+ GPU allocation. Cannot run in CI or on developer machines without HPC access. |
| Verification approach | On a GPU node (Gadi or local): run `llm-discovery run --platform local --yes`. Verify exit code 0. Open `corpus.db` with `datasette corpus.db` or `sqlite3`. Run `SELECT COUNT(*) FROM result_category` and confirm 105 rows (5 docs x 21 categories). Run `SELECT DISTINCT match FROM result_category` and confirm values are from {yes, maybe, no}. Check `SELECT COUNT(*) FROM result_category_blockquote` returns > 0 (at least some categories should extract quotes). |

### reproducible-demo.AC2.4 -- corpus.db contains 5 docs x 21 categories = 105 result_category rows

| Field | Value |
|-------|-------|
| Test type | Unit (partial) + Human verification (full) |
| Test file | `tests/test_prep_db.py`, `tests/test_pipeline_e2e.py` |
| Phase | 3 (Task 5) |

**Automated tests (no GPU -- verifies the math, not the LLM output):**

1. `test_category_count_is_21` -- Call `sync_categories` with real `prompts/` directory. Assert 21 category rows. This is the prerequisite half of the 105-row assertion.

2. `test_result_category_cross_product` -- Create temp DB, sync 21 categories and 5 documents (assuming no splits). Query for unprocessed pairs (result_id, category_id combinations not yet in result_category). Assert exactly 105 pairs. This verifies the cross-product is correctly generated before LLM processing.

**Human verification (GPU required):**

| Item | Detail |
|------|--------|
| Criterion | Exactly 105 result_category rows after full pipeline run |
| Why not automated | Requires GPU and live LLM inference to populate result_category table. The cross-product generation is tested automatically; the LLM filling those rows requires hardware. |
| Verification approach | After `llm-discovery run --platform local --yes` completes: `sqlite3 corpus.db "SELECT COUNT(*) FROM result_category"` -- expect 105. Also verify: `sqlite3 corpus.db "SELECT COUNT(DISTINCT result_id) FROM result_category"` -- expect 5. `sqlite3 corpus.db "SELECT COUNT(DISTINCT category_id) FROM result_category"` -- expect 21. If documents were split (>80KB), the count may exceed 105 because split parts each get their own result rows. In that case, verify via the `document_category_aggregate` view that 5 original documents are covered. |

### reproducible-demo.AC2.5 -- fetch with unreachable URL reports clear error, no partial files

| Field | Value |
|-------|-------|
| Test type | Unit |
| Test file | `tests/test_fetch.py` |
| Phase | 2 (Task 1) |

**Automated tests:**

1. `test_fetch_single_connection_error` -- Mock `requests.get` to raise `ConnectionError`. Call `fetch_single`. Assert it raises or returns error. List files in output dir. Assert no `.md` files exist (atomic write prevents partials).

2. `test_fetch_single_http_404` -- Mock `requests.get` to return a 404 response. Assert `RuntimeError` raised with message containing the URL. Assert no partial files.

3. `test_fetch_single_http_500` -- Mock `requests.get` to return a 500 response. Assert `RuntimeError` raised. Assert no partial files.

4. `test_fetch_corpus_continues_on_single_failure` -- Mock `requests.get` to fail for the first URL and succeed for the rest. Call `fetch_corpus`. Assert 4 files created. Assert `RuntimeError` raised summarising the 1 failure.

5. `test_fetch_single_no_temp_files_on_failure` -- Mock `requests.get` to raise mid-download. List all files in output dir (including hidden/temp). Assert directory is clean.

### reproducible-demo.AC2.6 -- Re-running fetch skips already-fetched files (idempotent)

| Field | Value |
|-------|-------|
| Test type | Unit + Integration |
| Test file | `tests/test_fetch.py` |
| Phase | 2 (Tasks 1, 3) |

**Automated tests (unit, mocked):**

1. `test_fetch_single_skips_existing` -- Write a file to the output dir matching the expected filename for a demo URL. Call `fetch_single`. Assert it returns `None`. Assert `requests.get` was NOT called (mock verifies zero calls). Assert the pre-existing file content is unchanged.

2. `test_fetch_corpus_reports_skipped_count` -- Pre-create 2 of 5 expected output files. Mock network for the other 3. Call `fetch_corpus`. Assert 3 files in the `written` return list. Assert 2 files skipped (not in written, not in failed).

**Automated tests (integration, live):**

3. `test_fetch_idempotent_live` -- Mark with `@pytest.mark.network`. Call `fetch_corpus` with 1 demo URL. Record the output file's mtime. Call `fetch_corpus` again with the same URL. Assert the file's mtime is unchanged (was not rewritten).

---

## reproducible-demo.AC3: HPC deployment

### reproducible-demo.AC3.1 -- deploy --platform gadi rsyncs code and submits PBS job

| Field | Value |
|-------|-------|
| Test type | Unit |
| Test file | `tests/test_platform.py`, `tests/test_deploy.py` |
| Phase | 6 (Tasks 2, 4, 6) |

**Automated tests (mocked SSH/rsync):**

1. `test_rsync_command_construction` -- Call `rsync_to_remote` with a mock platform config. Capture the subprocess command. Assert it includes `-avz`, correct source and destination paths, and all required `--exclude` flags (`.venv/`, `__pycache__/`, `*.db`, `*.pyc`, `.git/`, `input/`, `out/`, `*.log`). Assert it does NOT include `--delete`.

2. `test_pbs_template_substitution` -- Read `hpc/gadi.pbs.template`. Call the template substitution logic with `GPU_QUEUE=gpuvolta` and `NCI_PROJECT=ab12`. Assert output contains `#PBS -q gpuvolta`, `#PBS -P ab12`, `#PBS -l storage=scratch/ab12`. Assert no `{{PLACEHOLDER}}` markers remain.

3. `test_pbs_template_gpuhopper` -- Same substitution with `GPU_QUEUE=gpuhopper`. Assert `#PBS -q gpuhopper` in output. Assert vLLM parameters in the case block match H200/H100 values.

4. `test_submit_gadi_job_parses_jobid` -- Mock fabric `Connection.run` to return stdout like `12345.gadi-pbs`. Call `submit_gadi_job`. Assert returned job ID is `12345.gadi-pbs`.

5. `test_deploy_cli_help` -- Run `uv run llm-discovery deploy --help`. Assert output contains `--platform`, `--project`, `--gpu-queue`.

**Human verification (requires Gadi access):**

| Item | Detail |
|------|--------|
| Criterion | Actual rsync to Gadi and PBS job submission |
| Why not automated | Requires valid NCI account, SSH keys configured for gadi.nci.org.au, active project allocation with GPU quota, and network access to the NCI firewall. Cannot be replicated in CI. |
| Verification approach | Run `llm-discovery deploy --platform gadi --project <code> --gpu-queue gpuvolta`. Verify rsync output shows files transferred. Verify qsub output shows a job ID. Run `qstat <job_id>` on Gadi to confirm job is queued/running. Check `llm-discovery.out` and `llm-discovery.err` log files on /scratch after job completes. |

### reproducible-demo.AC3.2 -- deploy --platform ucloud submits via API or prints manual instructions

| Field | Value |
|-------|-------|
| Test type | Unit |
| Test file | `tests/test_platform.py` |
| Phase | 6 (Tasks 1, 5) |

**Automated tests:**

1. `test_ucloud_manual_fallback_prints_instructions` -- If UCloud API spike determines manual submission: call `submit_ucloud_job`. Capture stdout. Assert output contains "Manual steps", "cloud.sdu.dk", "H100", and "process_corpus.sh".

2. `test_ucloud_api_submission` -- If UCloud API spike determines automated submission: mock the API endpoint. Call `submit_ucloud_job`. Assert it sends the correct API payload. Assert it returns a job ID.

**Human verification (requires UCloud access):**

| Item | Detail |
|------|--------|
| Criterion | Actual UCloud job submission or successful manual workflow |
| Why not automated | Requires DeiC/UCloud account, active project allocation, and GPU resource availability. UCloud uses a web portal that may not be fully API-scriptable. |
| Verification approach | If automated: run `llm-discovery deploy --platform ucloud`. Verify job submission output. If manual: run `llm-discovery deploy --platform ucloud`. Follow printed instructions. Verify the batch script runs successfully in the UCloud Terminal App. |

### reproducible-demo.AC3.3 -- validate reports pass/fail for each prerequisite

| Field | Value |
|-------|-------|
| Test type | Unit |
| Test file | `tests/test_platform.py` |
| Phase | 5 (Tasks 3, 4, 5) |

**Automated tests (mocked SSH):**

1. `test_platforms_yaml_loads` -- Call `load_platforms("config/platforms.yaml")`. Assert it returns a valid `PlatformsConfig`. Assert `gadi` and `ucloud` keys exist.

2. `test_platform_config_validation` -- Create a YAML dict missing `display_name`. Assert pydantic `ValidationError` raised.

3. `test_project_placeholder_resolution` -- Call `resolve_remote_path` with platform config containing `{project}` and project="ab12". Assert result is `/scratch/ab12/llm-discovery`.

4. `test_validate_all_checks_pass` -- Mock fabric `Connection.run` to return `ok=True` for all checks. Call `validate_platform`. Assert all tuples in result have `passed=True`.

5. `test_validate_hf_token_missing` -- Mock fabric `Connection.run` to return `ok=False` for the HF_TOKEN check. Call `validate_platform`. Assert the HF_TOKEN check tuple has `passed=False`. Assert other checks still ran (no early abort).

6. `test_validate_ssh_failure` -- Mock fabric `Connection` to raise `AuthenticationException`. Assert validation reports SSH connectivity as failed.

7. `test_ucloud_skips_ssh_checks` -- Load UCloud platform config (ssh_host=None). Call `validate_platform`. Assert no SSH connection attempted. Assert result list reflects skipped checks.

8. `test_validate_cli_exit_codes` -- Mock the validate logic to return all-pass. Run `llm-discovery validate --platform gadi`. Assert exit code 0. Mock to return one failure. Assert exit code 1.

**Human verification (requires HPC access):**

| Item | Detail |
|------|--------|
| Criterion | Validate against live Gadi environment |
| Why not automated | Requires SSH access to gadi.nci.org.au with valid credentials and project. |
| Verification approach | Run `llm-discovery validate --platform gadi --project <code>`. Verify Rich table output shows pass/fail for: SSH connectivity, /scratch accessible, HF_TOKEN set, uv available. Fix any failures and re-run to confirm the validate command correctly reflects environment state. |

### reproducible-demo.AC3.4 -- deploy without prior validate warns and runs validation first

| Field | Value |
|-------|-------|
| Test type | Unit |
| Test file | `tests/test_deploy.py` |
| Phase | 5 (Task 4), Phase 6 (Task 6) |

**Automated tests:**

1. `test_deploy_calls_validate_first` -- Mock both `validate_platform` and `rsync_to_remote`. Call the deploy CLI logic. Assert `validate_platform` was called before `rsync_to_remote`. (Verify call order via mock call history.)

2. `test_deploy_aborts_on_validation_failure` -- Mock `validate_platform` to return a failed check. Call deploy. Assert `rsync_to_remote` was NOT called. Assert exit code 1.

3. `test_deploy_proceeds_after_validation_pass` -- Mock `validate_platform` to return all-pass. Call deploy. Assert `rsync_to_remote` WAS called.

---

## reproducible-demo.AC4: Documentation

### reproducible-demo.AC4.1 -- README quickstart gets from clone to completed run in under 10 commands

| Field | Value |
|-------|-------|
| Test type | Unit (partial) + Human verification |
| Test file | `tests/test_docs.py` |
| Phase | 8 (Task 1) |

**Automated tests:**

1. `test_readme_exists` -- Assert `README.md` exists at repo root.

2. `test_readme_contains_quickstart` -- Read `README.md`. Assert it contains a section header matching "quickstart" (case-insensitive).

3. `test_quickstart_command_count` -- Parse the quickstart section of `README.md`. Count lines that start with ` ``` ` fenced code blocks or that look like shell commands (lines starting with `$`, `#`, or common CLI prefixes inside code blocks). Assert total command count <= 10.

**Human verification:**

| Item | Detail |
|------|--------|
| Criterion | A new collaborator can follow README from clone to completed demo run |
| Why not automated | Verifying that documentation is clear, complete, and actually leads to a working pipeline requires a human reading and following the instructions on a fresh machine. Automated tests can count commands but cannot judge clarity. |
| Verification approach | On a clean machine (or fresh VM/container) with only Python 3.12+ and uv installed: follow the README quickstart exactly as written. Note any missing steps, unclear instructions, or errors. Verify that `datasette corpus.db` shows populated data at the end. The test passes if no undocumented steps were required. |

---

## Test Infrastructure

### Pytest markers

| Marker | Purpose | Default |
|--------|---------|---------|
| `@pytest.mark.gpu` | Requires GPU and running vLLM server | Skip |
| `@pytest.mark.network` | Requires live Internet Archive access | Skip |
| `@pytest.mark.slow` | Takes >30 seconds (e.g., full fetch of 5 URLs) | Run |

Configure in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = [
    "gpu: requires GPU and running vLLM server",
    "network: requires network access to Internet Archive",
    "slow: takes more than 30 seconds",
]
```

### Test file inventory

| File | Phase | Covers |
|------|-------|--------|
| `tests/test_scaffolding.py` | 1 | AC1.1, AC1.2, AC1.3 |
| `tests/test_fetch.py` | 2 | AC2.1, AC2.5, AC2.6 |
| `tests/test_preflight.py` | 3 | AC2.2 |
| `tests/test_prep_db.py` | 3 | AC2.4 (category/document counts) |
| `tests/test_import_results.py` | 3 | AC2.3 (import logic) |
| `tests/test_pipeline_e2e.py` | 3, 7 | AC2.3, AC2.4 (cross-product) |
| `tests/test_platform.py` | 5 | AC3.3 |
| `tests/test_deploy.py` | 6 | AC3.1, AC3.2, AC3.4 |
| `tests/test_docs.py` | 8 | AC4.1 |

### Human verification summary

| Criterion | Requires | Blocker |
|-----------|----------|---------|
| AC2.3 full pipeline | GPU (4x V100/A100/H100/H200), gpt-oss-120b model | Hardware access |
| AC2.4 105 rows | Same as AC2.3 | Hardware access |
| AC3.1 Gadi deploy | NCI account, SSH keys, project allocation | Institutional access |
| AC3.2 UCloud deploy | DeiC/UCloud account, project allocation | Institutional access |
| AC3.3 live validate | NCI account, SSH keys | Institutional access |
| AC4.1 documentation | Fresh machine, human reader | Requires human judgment |
