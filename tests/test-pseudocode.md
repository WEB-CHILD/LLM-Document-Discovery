# Test Pseudocode

Human-readable description of what each test does, organised by domain.
Maintained by project-claude-librarian at branch completion.

Overlapping tests and coverage gaps are documented intentionally --
they reveal where the test suite is redundant or incomplete.

## Fetch (Internet Archive)

### Parse Internet Archive URL
**File:** tests/test_fetch.py::TestParseIaUrl::test_valid_url
1. Pass a full IA URL with timestamp and original URL
2. Assert timestamp and original URL are extracted correctly

**Verifies:** URL parsing extracts the 14-digit timestamp and original URL from IA format

### Parse IA URL rejects non-IA URLs
**File:** tests/test_fetch.py::TestParseIaUrl::test_invalid_url_not_ia
1. Pass a non-IA URL
2. Assert ValueError raised with "Internet Archive" in message

**Verifies:** Only IA-format URLs are accepted

### Make filename is deterministic and filesystem-safe
**File:** tests/test_fetch.py::TestMakeFilename::test_deterministic, test_produces_md_extension, test_filesystem_safe
1. Generate filename from same URL twice, assert identical
2. Assert .md extension
3. Assert no /, \, or : characters in output

**Verifies:** URL-to-filename mapping is stable and won't break filesystem paths

### HTML to markdown conversion
**File:** tests/test_fetch.py::TestHtmlToMarkdown::test_basic_conversion, test_preserves_links
1. Convert simple HTML with headings and paragraphs
2. Assert text content preserved
3. Assert links preserved

**Verifies:** HTML-to-markdown conversion retains content and structure

### Verify snapshot via CDX API (mocked)
**File:** tests/test_fetch.py::TestVerifySnapshot::test_returns_true_when_snapshot_exists, test_returns_false_when_no_snapshot
1. Mock CDX API response with/without snapshot rows
2. Assert True when snapshot found, False when empty

**Verifies:** CDX verification correctly interprets API responses

### Download HTML via id_ endpoint (mocked)
**File:** tests/test_fetch.py::TestDownloadHtml::test_returns_html, test_raises_on_http_error
1. Mock successful HTTP response, assert HTML returned and id_ URL constructed correctly
2. Mock HTTP error, assert RuntimeError raised

**Verifies:** HTML download uses the Wayback id_ endpoint and propagates errors

### Fetch single page creates markdown with header
**File:** tests/test_fetch.py::TestFetchSingle::test_creates_markdown_file_with_header
1. Mock download_html and verify_snapshot
2. Call fetch_single with an IA URL
3. Assert output file exists with timestamp/URL header on first line

**Verifies:** Full fetch pipeline produces correctly-formatted markdown files

### Fetch single skips existing files
**File:** tests/test_fetch.py::TestFetchSingle::test_skips_existing_file
1. Fetch once (creates file), fetch again
2. Assert second call returns None and download_html not called

**Verifies:** Idempotent fetch -- existing files are not re-downloaded

### Fetch single leaves no partial files on error
**File:** tests/test_fetch.py::TestFetchSingle::test_no_partial_files_on_error
1. Mock download to raise RuntimeError
2. Assert RuntimeError propagated and no files in output dir

**Verifies:** Atomic file creation -- no partial files on failure

### Fetch corpus uses defaults and returns only new files
**File:** tests/test_fetch.py::TestFetchCorpus::test_uses_default_urls_when_none, test_returns_only_new_files, test_raises_on_failures
1. Call fetch_corpus with None URLs, assert DEFAULT_DEMO_URLS used
2. Mix new/skipped results, assert only new files returned
3. Assert failures propagate

**Verifies:** Corpus-level fetch orchestration

### Fetch integration (network required)
**File:** tests/test_fetch.py::TestFetchIntegration::test_fetch_single_produces_valid_markdown, test_idempotent_skip_on_rerun
1. Fetch a known-good IA URL against live API
2. Assert file created with correct header format and non-empty content
3. Re-fetch, assert skipped

**Verifies:** End-to-end fetch against live Internet Archive

## Database Preparation

### Create database with all tables
**File:** tests/test_prep_db.py::TestCreateDb::test_creates_all_tables
1. Create DB from schema.sql
2. Assert tables exist: result, category, result_category, result_category_blockquote, excluded_file, run_stats

**Verifies:** Schema creates all required tables

### Create database returns false if exists
**File:** tests/test_prep_db.py::TestCreateDb::test_returns_false_if_exists
1. Create DB, then call create_db again
2. Assert returns False (no-op)

**Verifies:** Idempotent database creation

### Sync categories populates table
**File:** tests/test_prep_db.py::TestSyncCategories::test_populates_category_table, test_no_duplicates_on_resync, test_raises_on_empty_dir
1. Sync 2 sample YAML prompt files
2. Assert 2 rows in category table
3. Re-sync, assert still 2 rows (no duplicates)
4. Sync empty dir, assert ValueError

**Verifies:** Category sync is idempotent and rejects empty prompt directories

### Sync documents populates result table
**File:** tests/test_prep_db.py::TestSyncDocuments::test_populates_result_table, test_no_duplicates_on_resync
1. Sync 3 sample corpus documents
2. Assert 3 rows in result table, 0 skipped
3. Re-sync, assert still 3 rows

**Verifies:** Document sync with SHA-256 change detection is idempotent

### Database status returns correct stats
**File:** tests/test_prep_db.py::TestGetDatabaseStatus::test_returns_correct_stats
1. Sync 2 categories and 3 documents
2. Assert stats: 3 documents, 2 categories, 6 total pairs, 6 pending, 0 processed

**Verifies:** Status calculation for the document x category cross-product

## Preflight Validation

### Check document accepts valid markdown
**File:** tests/test_preflight.py::TestCheckDocument::test_valid_markdown_passes
1. Create document with timestamp header and sufficient text
2. Assert is_valid=True, empty reason

**Verifies:** Valid documents pass preflight

### Check document rejects various invalid content
**File:** tests/test_preflight.py::TestCheckDocument::test_empty_content_rejected, test_binary_gif_rejected, test_binary_pdf_rejected, test_short_body_rejected, test_null_bytes_rejected, test_low_printable_ratio_rejected
1. Test empty content -> rejected ("empty")
2. Test GIF89a header -> rejected ("GIF")
3. Test %PDF header -> rejected ("PDF")
4. Test short body -> rejected ("short")
5. Test null bytes -> rejected ("null")
6. Test low printable ratio -> rejected ("printable")

**Verifies:** Each rejection class is detected with descriptive reason

### Run preflight on database
**File:** tests/test_preflight.py::TestRunPreflight::test_all_valid_documents, test_detects_invalid_documents, test_delete_removes_problematic
1. Sync 3 valid documents, run preflight -> 3 valid, 0 problematic
2. Insert binary document + valid document -> 1 valid, 1 problematic
3. Run with delete=True -> problematic removed, 0 rows remaining

**Verifies:** Batch preflight with optional deletion of invalid documents

## LLM Processing

### Build request body
**File:** tests/test_unified_processor.py::TestBuildRequestBody::test_produces_correct_shape, test_custom_id_format
1. Build request with result_id=1, category_id=2
2. Assert custom_id="r1_c2", model set, temperature=0.0, 2 messages (system + user)
3. Assert document content and category prompt in user message

**Verifies:** Request body conforms to OpenAI chat completion format

### Parse custom ID
**File:** tests/test_unified_processor.py::TestParseCustomId::test_valid_id
1. Parse "r1_c2" -> (1, 2), "r42_c7" -> (42, 7)

**Verifies:** Bidirectional custom_id encoding/decoding

### Extract JSON from text
**File:** tests/test_unified_processor.py::TestExtractJsonFromText::test_extracts_json, test_returns_none_for_no_json, test_handles_nested_braces
1. Extract JSON from text with reasoning prefix -> correct dict
2. No JSON present -> None
3. Nested braces handled correctly

**Verifies:** JSON extraction from LLM free-text responses

### Parse response
**File:** tests/test_unified_processor.py::TestParseResponse::test_valid_response, test_error_response, test_no_json_in_content, test_missing_match_field
1. Valid response -> parsed dict with result_id, category_id, match, blockquotes
2. Error response (None response, error string) -> None parsed, error message
3. No JSON in content -> None parsed, "No JSON" error
4. Missing "match" field -> None parsed, "match" error

**Verifies:** Response parsing handles valid, error, malformed, and incomplete responses

### Save result to file (atomic)
**File:** tests/test_unified_processor.py::TestSaveResultToFile::test_atomic_write, test_idempotent_skip
1. Save parsed result -> file created as r1_c2.json with correct content
2. Save same result again -> returns False (skip)

**Verifies:** Atomic, idempotent JSON result file writing

## Result Import

### Import single record
**File:** tests/test_import_results.py::TestImportRecord::test_valid_record_imported
1. Sync categories and documents, create record with match="yes" and 2 blockquotes
2. Import record, assert stats["imported"]=1, bq_count=2
3. Verify result_category row and 2 blockquote rows in DB

**Verifies:** Valid records are imported with blockquotes

### Idempotent import
**File:** tests/test_import_results.py::TestImportRecord::test_idempotent_import
1. Import record, import same record again
2. Assert second import: skipped=1, imported=0

**Verifies:** INSERT OR IGNORE prevents duplicate imports

### Missing fields rejected
**File:** tests/test_import_results.py::TestImportRecord::test_missing_fields_rejected
1. Import record with only result_id (missing category_id, match)
2. Assert errors=1

**Verifies:** Incomplete records are rejected with error count

### Run import on JSON files
**File:** tests/test_import_results.py::TestRunImport::test_imports_json_files, test_handles_malformed_json
1. Create JSON result file, run_import -> imported=1, blockquotes=1
2. Create malformed JSON file -> errors=1, imported=0

**Verifies:** Batch import reads JSON files and handles parse errors

## Platform Configuration

### Load platforms from YAML
**File:** tests/test_platform.py::TestLoadPlatforms::test_loads_real_config, test_gadi_has_required_fields, test_raises_on_missing_file, test_raises_on_invalid_yaml
1. Load real config/platforms.yaml, assert "gadi" and "ucloud" present
2. Assert Gadi has correct display_name, ssh_host, gpu_type, 4 checks
3. Missing file -> FileNotFoundError
4. Invalid YAML -> ValidationError

**Verifies:** Platform config loading with Pydantic validation

### Resolve remote path
**File:** tests/test_platform.py::TestResolveRemotePath::test_replaces_project_placeholder
1. Create platform with remote_base="/scratch/{project}/llm-discovery"
2. Resolve with project="ab12"
3. Assert "/scratch/ab12/llm-discovery"

**Verifies:** Project placeholder substitution in remote paths

### Validate platform (SSH checks)
**File:** tests/test_platform.py::TestValidatePlatform::test_non_ssh_platform_skips, test_ssh_checks_pass, test_ssh_checks_fail, test_project_placeholder_resolved
1. Non-SSH platform -> checks skipped with "skipped" message
2. Mock SSH success -> check passes with stdout snippet
3. Mock SSH failure -> check fails with stderr
4. Project placeholder in check command resolved before SSH execution

**Verifies:** Platform validation runs checks via SSH or skips for non-SSH platforms

## Container Build (CLI)

### Build success
**File:** tests/test_build.py::TestBuildCommand::test_build_success
1. Create container/pipeline.def and a >1GB pipeline.sif stub
2. Mock apptainer available, mock subprocess success
3. Invoke `build` command
4. Assert exit 0, verify apptainer build called with correct args, then apptainer exec for validation

**Verifies:** Build command calls apptainer build then validates the image

### Apptainer not found
**File:** tests/test_build.py::TestBuildCommand::test_apptainer_not_found
1. Mock shutil.which returns None
2. Invoke `build`
3. Assert exit 1, output contains apptainer.org URL

**Verifies:** Missing apptainer gives actionable installation guidance

### Build failure shows sudo hint
**File:** tests/test_build.py::TestBuildCommand::test_build_failure_shows_sudo_hint
1. Mock apptainer build raising CalledProcessError
2. Assert exit 1, output contains "sudo"

**Verifies:** Build failures suggest sudo re-run

### Validate-only mode
**File:** tests/test_build.py::TestBuildValidate::test_validate_success, test_validate_missing_sif, test_validate_sif_too_small, test_validate_cli_not_callable
1. Valid >1GB .sif with successful apptainer exec -> exit 0, "validated" in output
2. Missing .sif -> exit 1, "does not exist"
3. Tiny .sif -> exit 1, "gb" in output
4. CLI exec fails -> exit 1, "not callable"

**Verifies:** Validation checks: file existence, size >1GB, CLI callable inside container

## Container Staging (Platform)

### Stage SIF to remote with SHA256 verification
**File:** tests/test_platform.py::TestStageContainerImage::test_stages_sif_to_correct_remote_path
1. Create local .sif, compute SHA256
2. Mock Connection and rsync subprocess
3. Call stage_container_image
4. Assert remote path returned, rsync called with correct args

**Verifies:** SIF is rsynced to /scratch/{project}/containers/ with correct path

### Stage raises on missing SIF
**File:** tests/test_platform.py::TestStageContainerImage::test_raises_on_missing_sif
1. Call with nonexistent .sif path
2. Assert FileNotFoundError with "Container image not found"

**Verifies:** Clear error when SIF doesn't exist locally

### Stage raises on checksum mismatch
**File:** tests/test_platform.py::TestStageContainerImage::test_raises_on_checksum_mismatch
1. Create .sif, mock remote sha256sum returning wrong hash
2. Assert RuntimeError with "SHA256 mismatch"

**Verifies:** Post-transfer integrity check catches corruption

### Stage creates remote directory
**File:** tests/test_platform.py::TestStageContainerImage::test_creates_remote_directory
1. Stage a .sif file
2. Assert first SSH call is "mkdir -p /scratch/ab12/containers"

**Verifies:** Remote container directory created before rsync

## HPC Environment Config

### Generate hpc_env.sh for known queues
**File:** tests/test_platform.py::TestGenerateHpcEnv::test_gpuvolta_config, test_gpuhopper_config
1. Generate env for gpuvolta -> exports gemma-4-31B-it, TP=4, MEM=0.90, SEQS=64
2. Generate env for gpuhopper -> exports gpt-oss-120b, TP=4, MEM=0.92, SEQS=384
3. Assert starts with shebang line

**Verifies:** Correct vLLM parameters for each GPU queue

### Unknown queue raises
**File:** tests/test_platform.py::TestGenerateHpcEnv::test_unknown_queue_raises
1. Generate env for "nonexistent"
2. Assert ValueError with "Unknown GPU queue"

**Verifies:** Invalid queue names are rejected

### Get GPU queue config
**File:** tests/test_platform.py::TestGetGpuQueueConfig::test_gpuhopper_returns_config, test_gpuvolta_returns_config, test_unknown_queue_raises
1. Assert gpuhopper config has correct model and TP
2. Assert gpuvolta config has correct model
3. Unknown queue -> ValueError

**Verifies:** GPU queue config lookup returns correct parameters

## PBS Job Submission

### PBS template uses singularity exec
**File:** tests/test_platform.py::TestPBSTemplate::test_pbs_template_contains_singularity_exec
1. Read gadi.pbs.template
2. Assert contains "singularity exec --nv" and "module load singularity"
3. Assert does NOT contain "bash scripts/process_corpus.sh" or "module load python3"

**Verifies:** Template uses container execution, not legacy shell scripts

### Container path substituted in PBS template
**File:** tests/test_platform.py::TestPBSTemplate::test_container_path_substituted
1. Create platform config, mock SSH connection
2. Submit job with container_path
3. Read uploaded PBS script content
4. Assert no {{CONTAINER_PATH}} placeholder, actual path present

**Verifies:** All template placeholders are resolved before submission

### Submit ping job
**File:** tests/test_platform.py::TestSubmitPingJob::test_submits_ping_job
1. Mock SSH connection returning job ID
2. Submit ping job with platform, project, queue, container path
3. Assert job ID returned, template placeholders resolved in uploaded content

**Verifies:** Ping job template substitution and submission

## HPC Init (CLI)

### Init success (full call chain)
**File:** tests/test_init.py::TestInitCommand::test_init_success
1. Mock all platform functions with call-order tracking
2. Invoke init with --platform gadi --project ab12 --gpu-queue gpuvolta
3. Assert exit 0, all functions called with correct args
4. Assert call order: stage -> env -> model -> ping
5. Assert job ID in output

**Verifies:** Init orchestrates staging, env upload, model upload, and ping in correct order

### Init SIF not found
**File:** tests/test_init.py::TestInitCommand::test_init_sif_not_found
1. Invoke init with nonexistent .sif
2. Assert exit 1, "container image not found" and "build it first" in output

**Verifies:** Init gives actionable guidance when container image missing

### Init validation fails
**File:** tests/test_init.py::TestInitCommand::test_init_validation_fails
1. Mock _ensure_validated returning False
2. Assert exit 1, "validation failed" in output

**Verifies:** Init exits early on platform validation failure

## Data Upload

### Upload data dir via rsync
**File:** tests/test_platform.py::TestUploadDataDir::test_rsync_with_valid_data_dir
1. Create data dir with corpus.db, system_prompt.txt, prompts/
2. Call upload_data_dir
3. Assert rsync called with correct source and remote paths

**Verifies:** Data directory is rsynced to remote /data/ path

### Upload excludes hpc_env.sh
**File:** tests/test_platform.py::TestUploadDataDir::test_excludes_hpc_env
1. Upload data dir, check rsync args
2. Assert "--exclude=hpc_env.sh" in args

**Verifies:** hpc_env.sh is not overwritten during data upload (managed separately)

### Upload validates required files
**File:** tests/test_platform.py::TestUploadDataDir::test_missing_corpus_db, test_missing_system_prompt, test_missing_prompts_dir, test_multiple_missing_lists_all
1. Missing corpus.db -> FileNotFoundError matching "corpus.db"
2. Missing system_prompt.txt -> FileNotFoundError
3. Missing prompts/ -> FileNotFoundError
4. Multiple missing -> all listed in error message

**Verifies:** Upload validates all required data files before transfer

## Model Cache Upload

### Upload model cache from HF cache
**File:** tests/test_platform.py::TestUploadModelCache::test_rsync_with_hf_hub_cache, test_rsync_with_hf_home, test_rsync_with_default_cache
1. With $HF_HUB_CACHE set -> rsync from that path
2. With $HF_HOME set -> rsync from $HF_HOME/hub/
3. Neither set -> rsync from ~/.cache/huggingface/hub/
4. All assert correct model directory and remote target in rsync args

**Verifies:** Model cache resolution follows HuggingFace env var hierarchy

### Model not found raises
**File:** tests/test_platform.py::TestUploadModelCache::test_model_not_found_raises, test_no_cache_dir_raises
1. Cache dir exists but model dir missing -> FileNotFoundError with "Download first"
2. No HF cache at all -> FileNotFoundError with "No HuggingFace cache"

**Verifies:** Actionable errors when model weights haven't been downloaded

## Deploy (CLI)

### Deploy calls stage_container_image
**File:** tests/test_platform.py::TestDeploy::test_deploy_calls_stage_container_image
1. Set up full deploy environment (config, template, .sif, data dir)
2. Mock SSH connection with SHA256 matching
3. Invoke deploy with all options
4. Assert exit 0, rsync calls include .sif staging, hpc_env uploaded

**Verifies:** Deploy orchestrates rsync, container staging, data upload, and job submission

### Rsync excludes SIF and container dir
**File:** tests/test_platform.py::TestRsyncToRemote::test_excludes_sif_and_container
1. Call rsync_to_remote, check subprocess args
2. Assert "--exclude=*.sif" and "--exclude=container/" in args

**Verifies:** Large container files excluded from code rsync (staged separately)

## Container E2E (requires pipeline.sif)

### SIF exists and is valid size
**File:** tests/test_container_e2e.py::TestContainerE2E::test_sif_exists_and_is_valid
1. Check pipeline.sif exists and is >1GB

**Verifies:** Built container image is a plausible size

### CLI callable inside container
**File:** tests/test_container_e2e.py::TestContainerE2E::test_cli_callable_inside_container
1. Run `apptainer exec pipeline.sif llm-discovery --help`
2. Assert exit 0, "process" and "import-results" in output

**Verifies:** llm-discovery CLI is installed and callable inside the container

### Container rejects missing env vars
**File:** tests/test_container_e2e.py::TestContainerE2E::test_container_fails_on_missing_env_vars
1. Bind-mount empty hpc_env.sh
2. Run entrypoint
3. Assert non-zero exit, "Required environment variable VLLM_MODEL is not set" in output

**Verifies:** Entrypoint validates required environment variables before proceeding

## Container GPU E2E (requires pipeline.sif + GPU)

### Container processes corpus end-to-end
**File:** tests/test_container_e2e.py::TestContainerGPU::test_container_processes_corpus
1. Prep corpus.db on host (prep-db + preflight)
2. Copy runtime assets into data dir
3. Run full container pipeline with --nv and bind mounts (30 min timeout)
4. Assert exit 0, result JSON files exist in out/ and are non-empty

**Verifies:** Full GPU pipeline produces result files inside container

### Container imports results into database
**File:** tests/test_container_e2e.py::TestContainerGPU::test_container_imports_results
1. After full pipeline run, query corpus.db
2. Assert result_category rows >0 with non-null reasoning_trace

**Verifies:** import-results stage populates database with reasoning traces

### No orphaned vLLM processes after exit
**File:** tests/test_container_e2e.py::TestContainerGPU::test_container_exits_cleanly
1. After pipeline run, pgrep for "vllm serve"
2. Assert no matches (pgrep returns non-zero)

**Verifies:** EXIT trap kills vLLM background process on container exit

### EXIT trap fires on failure
**File:** tests/test_container_e2e.py::TestContainerGPU::test_container_exit_trap_on_failure
1. Provide corrupt (empty) corpus.db
2. Run container (should fail at process step)
3. Assert non-zero exit
4. Assert no orphaned vLLM processes

**Verifies:** EXIT trap fires even when pipeline fails, preventing orphaned GPU processes

## Coverage Gaps

- No tests for `download-model` CLI command
- No tests for `status --watch` polling loop
- No tests for `retrieve` command
- No tests for `run` command end-to-end routing (apptainer vs PBS path)
- No tests for `_assemble_data_dir` helper
- No tests for `check_container_freshness` in local_runner.py
- No tests for `run_container_pipeline` in local_runner.py
- No tests for `_count_jobs_ahead` queue position counting
- No tests for `fetch_remote_file`
- No tests for `get_job_output_paths`
- No tests for apptainer submission validation path (local command execution in validate_platform)
