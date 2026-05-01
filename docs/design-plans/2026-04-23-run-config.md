# Run Config Design

**GitHub Issue:** None

## Summary

This design externalises and generalises the pipeline's hardcoded configuration so that a downstream adapter (Lise) can drive the entire `llm-discovery` workflow without modifying any file inside the vendored submodule. Currently, every model-to-GPU mapping lives in a Python dict (`_GPU_QUEUE_CONFIGS`) baked into `platform.py`, every data path is hardcoded inside the CLI orchestrators, and PBS job resources are hardcoded directly in the template file. Together these force any adapter to either fork the codebase or accept whatever parameters were committed at release time.

The design addresses this through two parallel mechanisms. First, all adapter-facing inputs — corpus database path, system prompt file, prompt directory, output directory, server URL — become explicit Typer CLI flags threaded through every orchestration layer, so the adapter can point the tool at their own files per invocation without any configuration file. Second, `_GPU_QUEUE_CONFIGS` is deleted and its content migrated into a new `queues:` and `job_types:` block in `config/platforms.yaml`, validated at load time by a set of Pydantic v2 models (`QueueProfile`, `JobType`, `PlatformsConfig`). Job resource values (`ncpus`, `mem`, `jobfs`) are derived by computed fields from `ngpus` multiplied by per-queue ratios, enforced at YAML-load time rather than at submission time. The existing `deploy` command is extended — not replaced — to accept `--config` and `--job-type`, render an expanded PBS template from the resolved `JobType`, validate that model weights exist on the remote before calling `qsub`, and write a `submitted.json` audit record. A new `smoke-test` verb submits a short PBS job that loads the target model and runs one canned inference round-trip, giving operators an empirical end-to-end check before committing production walltime. Two supporting improvements ship alongside: per-pair `.error.json` failure artefacts with full reasoning traces and retry-skip logic, and origin metadata (`filepath`, `category_name`) propagated into every output JSON file.

## Definition of Done

### Primary deliverables

1. **Adapter-facing paths as CLI flags, threaded through every orchestrator.** Every hardcoded `Path(...)` string for adapter data (`system_prompt.txt`, `corpus.db`, `input/demo_corpus`, `out`, `prompts`, `schema.sql`, `logs/`) and every hardcoded server/queue default with no flag (`"http://localhost:8000"` on `run`, port 8000 in `start_vllm_server`/`wait_for_health`, `RTX4090-e4b` fallback in `_run_container_pipeline`) becomes an explicit Typer option on every command that uses it, including `process`, `prep-db`, `preflight`, `import-results`, `run`, `deploy`, `init`, `retrieve`. Overrides thread through `_run_local_pipeline`, `_run_container_pipeline`, `_assemble_data_dir`, `prepare_corpus`, `run_container_pipeline`, `run_local_pipeline`.

2. **Externalise and extend the existing job-type mechanism.** Move the `_GPU_QUEUE_CONFIGS` dict out of Python into `config/platforms.yaml` as a `job_types:` block (keyed by existing names like `gpuhopper-qwen3`, `RTX4090-e4b`). Add a `queues:` block holding per-queue resource ratios (`ncpus_per_gpu`, `mem_gb_per_gpu`, `jobfs_gb_per_gpu`, `max_jobfs_gb`, `max_walltime_hours`, `max_ngpus_per_job`, `su_per_resource_hour`). Each job-type entry references a queue by name and carries the existing vLLM fields plus the currently-missing PBS fields (`ngpus`, `walltime`, `project_default`) and weight-staging fields (`hf_repo`, `local_weights`, `dtype`, `trust_remote_code`, `extra_vllm_args`, `max_model_len`). `hpc/gadi.pbs.template`'s hardcoded values (`ngpus=4`, `ncpus=48`, `mem=380GB`, `walltime=04:00:00`, `jobfs=200GB`, storage line missing `+gdata/`, job name, log paths) become placeholders driven from the job-type entry. `get_gpu_queue_config`, `generate_hpc_env`, `submit_gadi_job`, `submit_ping_job` rewritten to read the YAML. `--config PATH` on `download-model`, `deploy`, `init`, `run`, `status`, `retrieve` lets the adapter point at their own `platforms.yaml`.

3. **Adapter can submit a PBS job for any job-type defined in the YAML.** Behaviour, not command shape: given a populated `platforms.yaml` whose weights have been staged, the adapter invokes the CLI with a job-type name, and a PBS job goes out for that job-type with resources derived from `ngpus` + the queue's ratios (`ncpus = ncpus_per_gpu × ngpus`, `mem = mem_gb_per_gpu × ngpus GB`, `jobfs = min(jobfs_gb_per_gpu × ngpus, max_jobfs_gb) GB`). If `local_weights` is missing on the remote, submission refuses with a clear error citing the missing path. Caller cannot silently override the derived resources. Enforcement of `walltime ≤ max_walltime_hours` and `ngpus ∈ {1..max_ngpus_per_job}`. A `runs/<run-id>/submitted.json` with `{job_id, job_type, git_sha, timestamp, yaml_snapshot}` is written after `qsub` succeeds. (Whether this is a new `submit` command or an extension of `deploy` is decided in brainstorming.)

4. **Smoke-test command.** New `llm-discovery smoke-test --config platforms.yaml --job-type <name> --project <project>` submits a short PBS job that loads the model and exits. User-triggered after YAML edits for a job-type; not chained inside deliverable-3 submission.

5. **Per-pair failure logs.** When `_handle_completed_future` exhausts retries, write `out/r{id}_c{id}.error.json` with `{custom_id, result_id, category_id, filepath, category_name, attempts, reason, last_response_preview, last_error, timestamp}`. `get_completed_pairs` treats `.error.json` as terminal so re-runs skip without retrying silently. `process` emits a prominent warning at end-of-run listing skipped-prior-failure pairs and their error file paths. Optional `--retry-failed` flag ignores `.error.json` on re-run.

6. **Origin metadata in all JSON output.** Every `out/r{id}_c{id}.json` (success) and `out/r{id}_c{id}.error.json` (failure) gains `filepath` and `category_name` fields matching the source `result.filepath` and `category.category_name` rows. The reader at `unified_processor.py:442` already `SELECT`s both; they propagate through `build_request_body` → work queue tuple → `do_request` → `parse_response` → `save_result_to_file`.

### Success criteria

- **SC1:** Adapter runs `llm-discovery process` with their own `--db`, `--system-prompt`, `--prompts-dir`, `--input-dir`, `--output-dir` without editing any file inside the submodule; output lands at their paths.
- **SC2:** Adapter adds a new `job_types` entry to their own `platforms.yaml` (e.g. a new Qwen variant) and runs the deliverable-3 submission for it. A PBS job is submitted with `ngpus`/`ncpus`/`mem`/`jobfs` exactly matching the queue-derived values for that entry, with no Python file changes inside the submodule.
- **SC3:** Submission against a job-type whose `local_weights` path does not exist on the remote exits non-zero before any `qsub` call, quoting the missing path.
- **SC4:** Submission against a job-type whose `walltime` exceeds `queues.<name>.max_walltime_hours` or whose `ngpus` exceeds `max_ngpus_per_job` refuses to qsub with a clear constraint-violation error.
- **SC5:** A pair whose `do_request` errors on all three retries produces `out/r{id}_c{id}.error.json` with the captured last error, `attempts=3`, timestamp, `filepath`, and `category_name`; re-running `process` skips it and logs "skipped due to prior failure: N pairs" in the run summary.
- **SC6:** Every `r{id}_c{id}.json` and `r{id}_c{id}.error.json` carries `filepath` and `category_name` matching DB values, verifiable via `jq`.
- **SC7:** `llm-discovery smoke-test --config platforms.yaml --job-type qwen3.6-35b-a3b --project as07` submits a PBS job that loads the model and exits within 10 minutes, emitting a PASS/FAIL marker like the existing ping job.

### Key exclusions

- No DB schema migration; origin metadata stays in JSON only (the existing `category_matches` view already joins `result.filepath` and `category.category_name`).
- No automatic weight staging from deliverable-3 submission; staging remains a separate step via `download-model` + `upload_model_cache` (themselves rewritten to be YAML-aware as part of deliverable 2).
- No silent auto-retry of failed pairs; retries require explicit `--retry-failed` or deletion of `.error.json`.
- No env-var fallback for any path override; CLI flags only.
- No multi-node PBS jobs; single-node `ngpus ∈ {1,2,3,4}` only.
- No changes to `/data/` or `/model_cache/` container bind-mount contracts.
- Smoke-test not auto-invoked from deliverable-3 submission.
- Non-Gadi platforms (UCloud) keep their existing submission paths; YAML-driven submission is Gadi-only for this design.
- The `_GPU_QUEUE_CONFIGS` Python dict is deleted (externalised). Anywhere that imported it must switch to the YAML reader — that is in scope, not out of scope.

## Acceptance Criteria

### run-config.AC1: Adapter-facing paths overridable via CLI flags
- **run-config.AC1.1 Success:** `process --db /tmp/x.db --system-prompt /tmp/sp.txt --prompts-dir /tmp/p --input-dir /tmp/i --output-dir /tmp/o` invokes `run_processor` with the supplied paths (mocked-spy assertion on call kwargs).
- **run-config.AC1.2 Success:** Omitting any of `--db`, `--system-prompt`, `--prompts-dir`, `--input-dir`, `--output-dir` falls back to the documented defaults (`corpus.db`, `system_prompt.txt`, `prompts/`, `input/demo_corpus`, `out/`); existing behaviour preserved.
- **run-config.AC1.3 Failure:** `process --db /nonexistent.db` (or missing system-prompt / prompts-dir) exits non-zero quoting the missing path.
- **run-config.AC1.4 Success:** `run` with all new flags threads each through `_run_local_pipeline` / `_run_container_pipeline` / `_run_remote_pipeline` — no hardcoded `Path("corpus.db")`, `"http://localhost:8000"`, `Path("logs")`, etc. inside those orchestrators.
- **run-config.AC1.5 Failure:** `_run_container_pipeline` invoked with a `PlatformConfig` lacking job-type assignment exits with explicit error rather than silently falling back to `"RTX4090-e4b"`.

### run-config.AC2: YAML schema validates job-type configurations
- **run-config.AC2.1 Success:** Canonical `config/platforms.yaml` with `queues:` and `job_types:` blocks loads into `PlatformsConfig` without errors. Each existing `_GPU_QUEUE_CONFIGS` key has a corresponding `job_types:` entry.
- **run-config.AC2.2 Success:** `JobType.ncpus`, `.mem_gb`, `.jobfs_gb` computed properties return `ngpus × queue_profile.ncpus_per_gpu`, `ngpus × queue_profile.mem_gb_per_gpu`, `min(ngpus × queue_profile.jobfs_gb_per_gpu, queue_profile.max_jobfs_gb)`. Verified at `ngpus=1`, `ngpus=4`, jobfs-cap clamp.
- **run-config.AC2.3 Failure:** A `job_types:` entry referencing a queue name absent from the `queues:` block raises `ValidationError` quoting the unknown queue.
- **run-config.AC2.4 Failure:** A `job_types:` entry with `ngpus > queue_profile.max_ngpus_per_job` raises `ValidationError` quoting the offending value and the cap.
- **run-config.AC2.5 Failure:** A `job_types:` entry with `walltime > queue_profile.max_walltime_hours` (parsed from `HH:MM:SS`) raises `ValidationError`.
- **run-config.AC2.6 Failure:** A `job_types:` entry with malformed `walltime` (not `HH:MM:SS`) raises `ValidationError`.

### run-config.AC3: `deploy` submits PBS job from YAML-driven job-type
- **run-config.AC3.1 Success:** `deploy --config <yaml> --job-type gpuhopper-qwen3 --project as07` renders a PBS script whose body contains exactly `#PBS -l ngpus=4`, `#PBS -l ncpus=48`, `#PBS -l mem=1024GB` (4 × 256), `#PBS -l jobfs=1600GB` (4 × 400, no cap needed), `#PBS -l walltime=24:00:00`, `#PBS -l storage=scratch/as07+gdata/as07`, `#PBS -P as07`, `#PBS -q gpuhopper`, `#PBS -N llm-discovery-gpuhopper-qwen3`, output paths under `/scratch/as07/llm-discovery/`.
- **run-config.AC3.2 Success:** After successful `qsub`, `runs/<run-id>/submitted.json` is written on the remote with keys `{job_id, job_type, project, git_sha, timestamp, yaml_snapshot}`. `<run-id>` matches the format `YYYYMMDDTHHMMSS.sssZ-<7char-sha>`.
- **run-config.AC3.3 Failure:** Missing `local_weights` on remote → `deploy` exits non-zero quoting the missing path; no `qsub` invocation occurs (verified by mocked SSH client).
- **run-config.AC3.4 Failure:** `deploy --job-type <invalid>` exits non-zero with the available job-type names listed.
- **run-config.AC3.5 Success:** `--gpu-queue` accepted as deprecated alias for `--job-type`, emits stderr deprecation warning, behaviour identical to `--job-type`.

### run-config.AC4: PBS bound enforcement at YAML load
- **run-config.AC4.1 Failure:** A YAML where `job_types.<x>.ngpus > queues.<q>.max_ngpus_per_job` causes `deploy` to exit non-zero at YAML-load time, before any SSH or qsub call.
- **run-config.AC4.2 Failure:** A YAML where `job_types.<x>.walltime > queues.<q>.max_walltime_hours` causes the same load-time refusal.
- **run-config.AC4.3 Failure:** A YAML with a disabled queue referenced from a job-type causes load-time refusal quoting the disabled reason.

### run-config.AC5: Per-pair failure logs
- **run-config.AC5.1 Success:** A pair whose `do_request` returns `urllib.error.HTTPError 500` on all 3 attempts produces exactly one `out/r{id}_c{id}.error.json` with `{custom_id, result_id, category_id, filepath, category_name, attempts: 3, reason, reasoning_trace, last_response_content, last_error, timestamp}`. `last_error` populated; `last_response_content` may be `null` for transport errors.
- **run-config.AC5.2 Success:** A pair whose response cannot be parsed as JSON on all 3 attempts produces an `.error.json` with `reason: "No JSON found. Preview: ..."`, `reasoning_trace` populated from `extract_reasoning(last_content)`, and `last_response_content` containing the full raw body.
- **run-config.AC5.3 Success:** Re-running `process` with the same `output_dir` skips pairs that have a `.error.json`. The final run summary contains `Skipped due to prior failure: <N>` with the listed file paths.
- **run-config.AC5.4 Success:** Deleting `out/r{id}_c{id}.error.json` and re-running `process` re-queues that pair (manual retry escape hatch).

### run-config.AC6: Origin metadata in pair-level JSON
- **run-config.AC6.1 Success:** Every `out/r{id}_c{id}.json` (success) contains `filepath` and `category_name` fields whose values match `result.filepath` and `category.category_name` for that `(result_id, category_id)`. Verified via `jq -r .filepath out/r1_c1.json` against the DB.
- **run-config.AC6.2 Success:** Every `out/r{id}_c{id}.error.json` (failure) contains the same `filepath` and `category_name` fields, populated from the same DB columns.
- **run-config.AC6.3 Edge:** For split-document parts (`result.part_number IS NOT NULL`), `filepath` reflects the part's filepath (e.g. `original_2`), not the parent's. Aligns with existing reader query semantics.

### run-config.AC7: Smoke-test command runs end-to-end inference
- **run-config.AC7.1 Success:** `llm-discovery smoke-test --config <yaml> --job-type gpuhopper-qwen3 --project as07 --platform gadi` submits a PBS job. The rendered script has `walltime=00:10:00` (or `job_type.smoketest_walltime` when set), points the container at `/opt/llm-discovery/container/smoketest_entrypoint.sh` (not `entrypoint.sh`), and uses the same resource lines as the production deploy.
- **run-config.AC7.2 Success:** The smoke-test job emits `PASS: smoke-test inference returned content` to stdout when the canned chat-completion request succeeds and `message.content` is non-empty.
- **run-config.AC7.3 Failure:** The smoke-test job emits `FAIL: <reason>` to stdout when vLLM crashes during load, the chat endpoint returns non-200, or the response body has empty `message.content`. The CLI reports the FAIL line and exits non-zero.
- **run-config.AC7.4 Failure:** When the PBS job completes without emitting either `PASS:` or `FAIL:` (job died unexpectedly), the CLI treats this as crash: "PING FAILED — No PASS or FAIL marker found in output — job may have crashed."

## Glossary

- **vLLM**: An open-source LLM inference server that exposes an OpenAI-compatible HTTP API. The pipeline launches vLLM inside the container and directs classification requests at it via `/v1/chat/completions`.
- **Apptainer / Singularity**: Container runtimes used for HPC workloads. Apptainer is the successor to Singularity; the local GPU path uses Apptainer and the Gadi HPC path uses Singularity (Gadi's installed runtime). Both accept the same `.sif` image format built from `container/pipeline.def`.
- **PBS (Portable Batch System)**: The job scheduler on NCI Gadi. Jobs are described in shell scripts with `#PBS` directives specifying resources, then submitted via `qsub`. The scheduler queues them and dispatches them to available nodes.
- **NCI Gadi**: The Australian National Computational Infrastructure's flagship HPC cluster. Access is via SSH; jobs must be submitted through PBS to run on GPU nodes.
- **gpuhopper queue**: A Gadi PBS queue providing access to A100 GPU nodes. Resource ratios (CPUs, memory, jobfs per GPU) are fixed by the queue's allocation rules and are the basis for the `QueueProfile` block.
- **SU (Service Units)**: The currency of compute allocation on NCI Gadi. Jobs are charged SU proportional to resources consumed; the `su_per_resource_hour` field in `QueueProfile` lets operators estimate cost before submitting.
- **walltime**: The maximum wall-clock duration a PBS job is permitted to run, declared as `HH:MM:SS`. Jobs that exceed their walltime are killed by the scheduler without producing output.
- **jobfs**: A per-job local scratch filesystem on Gadi nodes, faster than `/scratch` for temporary files. Used by vLLM for compile and inductor caches during inference. Allocated in GB per job; the design caps it at `min(ngpus × jobfs_gb_per_gpu, max_jobfs_gb)`.
- **ngpus**: The number of GPUs requested for a PBS job. Drives all other resource calculations via the queue's per-GPU ratios.
- **Pydantic v2**: A Python data-validation library. The design uses it to parse `platforms.yaml` into typed model objects, enforce cross-field constraints at load time, and derive computed fields. Version 2 introduced `@computed_field` and the `model_validator(mode="after")` API used in `JobType`.
- **`@computed_field`**: A Pydantic v2 decorator that marks a property as part of the model's serialised output. Used in `JobType` to expose `ncpus`, `mem_gb`, and `jobfs_gb` as read-only properties derived from `ngpus` and the linked `QueueProfile`.
- **`@model_validator`**: A Pydantic v2 decorator for cross-field validation that runs after field assignment. Used to enforce `ngpus ≤ max_ngpus_per_job` and `walltime ≤ max_walltime_hours` at parse time rather than at call time.
- **`_GPU_QUEUE_CONFIGS`**: The Python dict in `platform.py` that was the prior single source of truth for model/GPU parameter mappings. This design deletes it and replaces it with the `job_types:` block in `config/platforms.yaml`.
- **`JobType`**: The new Pydantic model representing one entry in the `job_types:` YAML block. It holds the vLLM model parameters, PBS resource parameters, weight-staging paths, and a reference to its `QueueProfile`.
- **`QueueProfile`**: The new Pydantic model representing one entry in the `queues:` YAML block. It holds the per-GPU resource ratios and caps for a specific PBS queue.
- **`PlatformsConfig`**: The new Pydantic root model that owns `platforms:`, `queues:`, and `job_types:` as a single parsed object. It is the single source of truth replacing `_GPU_QUEUE_CONFIGS`.
- **`submitted.json`**: A JSON audit record written to `runs/<run-id>/` on the remote scratch after a successful `qsub`. It contains `{job_id, job_type, project, git_sha, timestamp, yaml_snapshot}` and serves as an immutable record of what was submitted and with what configuration.
- **run-id format**: The identifier for a submitted run, formatted as `YYYYMMDDTHHMMSS.sssZ-<7char-sha>` (ISO 8601 timestamp with milliseconds plus the short git commit SHA). Makes `submitted.json` paths time-ordered and traceable to a code version.
- **fabric SSH**: The `fabric` Python library used throughout `platform.py` to run commands and transfer files on remote hosts via SSH. The new `local_weights` validation uses `fabric.Connection.run("test -d ...")` to check the remote path before qsub.
- **Lise (downstream adapter)**: The downstream project that vendors this repository as a git submodule. Lise runs `llm-discovery` against its own corpus database and 15-category safeguard rubric on Gadi. The design's primary motivation is to allow Lise to drive the pipeline entirely through CLI flags and its own `platforms.yaml` without modifying any submodule file.
- **submodule**: A git mechanism for embedding one repository inside another at a pinned commit. Lise uses this to vendor `llm-discovery`; the adapter isolation design ensures Lise never needs to edit the embedded repo's files.
- **Hugging Face repo (`hf_repo`)**: The Hugging Face model identifier (e.g. `google/gemma-4-31B-it`) used by `download-model` to fetch weights into the local HF cache before uploading to HPC scratch.
- **`local_weights`**: The path on the remote HPC scratch where model weights are expected to reside at job submission time. If missing, `deploy` refuses to call `qsub` and exits non-zero quoting the path.
- **`extract_reasoning`**: A function in `unified_processor.py` that extracts the chain-of-thought reasoning trace from a vLLM response, whether it appears in `message.reasoning_content`, `message.reasoning`, or inline in `message.content`. The extracted text is stored in `.error.json` to help diagnose parse failures.
- **reasoning trace**: The intermediate chain-of-thought text produced by reasoning-capable models (Qwen3, Gemma 4) before their final answer. Some vLLM backends surface it in a separate response field; others inline it with special tokens.
- **`reasoning_parser`**: A vLLM server flag that activates a model-specific parser to separate reasoning tokens from final output. Known values in this codebase: `qwen3`, `gemma4`, `openai_gptoss`.
- **MoE (Mixture of Experts)**: A model architecture where only a subset of parameters are active per token. Qwen3.6-35B-A3B is a MoE model: it has 35 billion total parameters but activates roughly 3 billion per forward pass, allowing lower GPU memory requirements than a dense 35B model.
- **`result_category` table**: The SQLite table that records each (document, category) classification result, including the model's response text and extracted match field. The `category_matches` view joins it with `result` and `category` tables to expose `filepath` and `category_name`.
- **`category_matches` view**: A pre-existing SQLite view in `schema.sql` that joins `result_category` with `result` (for `filepath`) and `category` (for `category_name`). The design relies on this view to avoid denormalising the schema when adding origin metadata to JSON output.
- **smoke-test (verb)**: A new CLI command (`llm-discovery smoke-test`) that submits a short PBS job running the full vLLM load-and-infer path with canned fixture prompts. Intended for operator use after YAML edits to validate a new job-type before committing production walltime.
- **`language_model_only`**: A vLLM server flag that disables the vision encoder in multimodal models (e.g. Gemma 4). Reduces KV cache pressure and speeds load when the pipeline only sends text prompts.
- **`dtype`**: The floating-point precision used to load model weights. Common values: `bfloat16`, `float16`, `auto`. Affects GPU memory consumption and numerical behaviour.
- **`tensor_parallel`**: The vLLM parameter controlling how many GPUs share each model layer's tensor computations. Must equal `ngpus` for single-node multi-GPU jobs that do not use data-parallel.
- **`data_parallel`**: The vLLM parameter controlling how many independent model replicas run in parallel across GPUs. `tensor_parallel × data_parallel` should equal `ngpus`. Most existing job types use `data_parallel = 1`; `gpuhopper-oss20b` is an exception with `tensor_parallel = 1, data_parallel = 4`.

## Architecture

The design has six cross-cutting components, all additive on top of the existing container pipeline and orchestration layer. Nothing in the `/data/` or `/model_cache/` bind-mount contracts changes; nothing in the SQLite schema changes; the `vllm/vllm-openai:v0.19.0` container image and its `entrypoint.sh` orchestration stay the same. The change surface is the Python package (`src/llm_discovery/`), `config/platforms.yaml`, `hpc/gadi.pbs.template`, and a new `container/smoketest_entrypoint.sh` plus two canned smoke-test prompt fixtures.

**System boundaries.** Adapter (Lise) → CLI (`llm-discovery <verb>`) → orchestration helpers (`local_runner.py`, `platform.py`) → container entrypoint or SSH+PBS path → vLLM server → DB writers. The CLI flag layer sits at the top boundary; the YAML reader sits just below it (replacing `_GPU_QUEUE_CONFIGS` lookups); the processor changes sit in the deepest layer (`unified_processor.py`).

**Data flow for a Gadi production run.** Adapter invokes `llm-discovery deploy --config their-platforms.yaml --job-type their-job --project their-proj`. The CLI loads `PlatformsConfig` via Pydantic, resolves the `JobType` (which carries the resolved `QueueProfile`), SSH-validates that `local_weights` exists, runs `_assemble_data_dir` over adapter-supplied paths, rsyncs code, stages container, uploads data dir, renders the PBS template with computed resources, qsubs, captures the job ID, writes `runs/<run-id>/submitted.json` on the remote scratch. The PBS job runs `singularity exec` with `entrypoint.sh` which sources `hpc_env.sh` (now generated from the resolved `JobType`), launches vLLM, waits for health, and runs `process` + `import-results` inside the container. `process` writes `r{id}_c{id}.json` (success) or `r{id}_c{id}.error.json` (failure) per pair; both files carry `filepath` and `category_name`; failure files additionally carry `reasoning_trace` (extracted from the last attempt's response) and full `last_response_content`.

**Data flow for smoke-test.** `llm-discovery smoke-test --config ... --job-type ... --project ...` mirrors the deploy flow up to the qsub call but renders a different PBS template (`hpc/gadi.smoketest.template`) with walltime clamped server-side to `00:10:00` (or per-job-type `smoketest_walltime`), and points the container at `container/smoketest_entrypoint.sh` instead of the production entrypoint. The smoke-test entrypoint loads vLLM, hits `/health`, then POSTs a single canned chat-completion request using two fixture files (`container/smoketest_system_prompt.txt`, `container/smoketest_user_prompt.txt`) shipped inside the container image. PASS/FAIL marker emitted to stdout; verdict surfaced via the existing `_wait_for_ping`-style polling logic.

**Key contracts.**

```python
class QueueProfile(BaseModel):
    pbs_queue: str | None
    ncpus_per_gpu: int
    mem_gb_per_gpu: int
    jobfs_gb_per_gpu: int
    max_jobfs_gb: int
    max_walltime_hours: int
    max_ngpus_per_job: int
    su_per_resource_hour: float

class JobType(BaseModel):
    name: str
    queue_profile: QueueProfile
    hf_repo: str
    local_weights: Path | None
    ngpus: int
    walltime: str | None
    smoketest_walltime: str = "00:10:00"
    vllm_model: str
    tensor_parallel: int
    data_parallel: int = 1
    dtype: str
    max_model_len: int
    trust_remote_code: bool = False
    gpu_memory_utilization: float
    max_num_seqs: int
    reasoning_parser: str | None = None
    language_model_only: bool = False
    extra_vllm_args: list[str] = []

    @computed_field
    @property
    def ncpus(self) -> int: ...
    @computed_field
    @property
    def mem_gb(self) -> int: ...
    @computed_field
    @property
    def jobfs_gb(self) -> int: ...

class PlatformsConfig(BaseModel):
    platforms: dict[str, PlatformConfig]
    queues: dict[str, QueueProfile]
    job_types: dict[str, JobType]

def render_pbs_script(
    template_path: Path,
    job_type: JobType,
    project: str,
    container_path: str,
    walltime_override: str | None = None,
) -> str: ...

def save_failure_to_file(failure: dict, output_dir: Path) -> bool: ...

# Work-queue item shape — anchors the five-signature lockstep change in Phase 5.
# (custom_id, body, filepath, category_name)
WorkItem = tuple[str, dict, str, str]
```

`PlatformsConfig` is the single source of truth; `_GPU_QUEUE_CONFIGS` is deleted. `render_pbs_script` is the single PBS template renderer used by `deploy`, `smoke-test`, and the existing `init → submit_ping_job` path. `save_result_to_file` (existing) and `save_failure_to_file` (new) are the only writers of pair-level JSON.

## Decision Record

### DR1: CLI flags for adapter data, YAML for infrastructure config
**Status:** Accepted
**Confidence:** High
**Reevaluation triggers:** If a third axis emerges (e.g., adapter wants a model registry distinct from queue/job-type config) and the binary split no longer scales.

**Decision:** We chose to split configuration responsibilities by concern. CLI Typer flags cover *adapter-facing data* (paths, server URLs, ports, individual run inputs) — values that vary per invocation, per adapter, per corpus. A YAML file (`config/platforms.yaml`) covers *infrastructure config* — queue resource ratios, per-job-type model parameters, and PBS submission specs that are slow-changing and per-deployment.

**Consequences:**
- **Enables:** Adapter can drive `process` end-to-end without editing any submodule file. Infrastructure config can be version-controlled separately and overridden via `--config` without touching the CLI shape. Adding a new job-type means editing one YAML entry, not Python.
- **Prevents:** "Everything is a CLI flag" maximalism that would have made `deploy` take 20+ flags. Also prevents a TOML/config-file-per-thing sprawl.

**Alternatives considered:**
- **CLI flags for everything (including model/queue specs):** Rejected because per-job-type values like `tensor_parallel`, `max_num_seqs`, `extra_vllm_args` are not per-invocation; baking them into CLI flags would force every invocation to repeat them or load them from somewhere anyway.
- **TOML/YAML for everything (paths included):** Rejected because adapter-supplied paths *are* per-invocation; forcing them through a config file adds a layer the adapter must construct each run.

### DR2: Single extended `config/platforms.yaml` over a new TOML file
**Status:** Accepted
**Confidence:** Medium
**Reevaluation triggers:** If `platforms.yaml` grows past comfortable readability (>500 lines) or if YAML's type ambiguity becomes a maintenance pain point.

**Decision:** We chose to extend the existing `config/platforms.yaml` (PyYAML-parsed, already containing the `platforms:` block) with two new top-level blocks (`queues:` and `job_types:`) rather than introduce a separate `config/gadi.toml` or migrate everything to TOML.

**Consequences:**
- **Enables:** One config file in `config/`, one parser, one Pydantic root model. No format-context-switching for adapter or future maintainers. Existing `load_platforms` extends naturally to a new `PlatformsConfig` root.
- **Prevents:** Adapter having to understand two formats simultaneously; duplication of file-loading code paths.

**Alternatives considered:**
- **New `config/gadi.toml`:** Rejected because two formats in `config/` is cognitive overhead, and the user's "TOML" framing in the reference brief was descriptive (showing what values needed configuring) rather than prescriptive of file format.
- **Migrate everything to TOML:** Rejected as a larger migration scope than this design needs; existing tests and tooling already work with PyYAML.

### DR3: Per-queue resource-ratio block, not per-job-type fields
**Status:** Accepted
**Confidence:** High
**Reevaluation triggers:** If a queue ever has a non-uniform ratio (e.g., gpuhopper has 12 cpus/GPU but a hypothetical "gpuhopper-fat" sub-pool has 24).

**Decision:** We chose to keep resource ratios (`ncpus_per_gpu`, `mem_gb_per_gpu`, `jobfs_gb_per_gpu`, etc.) in a per-queue `queues:` block, with each `job_types:` entry referencing a queue by name. Job-type entries do not repeat the ratios.

**Consequences:**
- **Enables:** A change to Gadi gpuhopper's official ratio (rare but possible) means editing one block; the change applies to every job-type on that queue automatically.
- **Prevents:** Ratio drift across job-types on the same queue. Cross-validation (`walltime ≤ max_walltime_hours`) has a single canonical source.

**Alternatives considered:**
- **Per-job-type fields:** Rejected because ratios are facts about the queue, not the job. Duplicating them per-job-type creates the kind of value-pinning this design is trying to eliminate.

### DR4: Extended `deploy` command, no new `submit` command
**Status:** Accepted
**Confidence:** Medium
**Reevaluation triggers:** If adapters frequently re-submit to a stable environment (no corpus or container changes between runs) and `deploy`'s prep-db + rsync + upload becomes wasteful enough to warrant a leaner atom.

**Decision:** We chose to extend the existing `deploy` command with `--config`, `--job-type`, weight validation, expanded PBS template rendering, and `submitted.json` writing — rather than introducing a new `submit` atom alongside it.

**Consequences:**
- **Enables:** One submission verb. Smaller CLI surface for the adapter to learn. Existing `deploy` users see only additive flags. The `--gpu-queue` flag becomes an alias for `--job-type` for one release cycle.
- **Prevents:** A second submission code path that drifts from `deploy`. Adapter confusion over which verb to use.

**Alternatives considered:**
- **New `submit` atom alongside `deploy`:** Rejected to keep CLI surface tight; `deploy`'s rsync is idempotent (skips unchanged files) and prep-db is fast for typical corpus sizes.
- **Decompose `deploy` into `stage-data`/`stage-container`/`submit`:** Rejected as too invasive a restructure for this scope.

### DR5: Origin metadata in JSON only, no DB schema migration
**Status:** Accepted
**Confidence:** High
**Reevaluation triggers:** If a downstream consumer requires `result_category.filepath` or `.category_name` columns that the existing `category_matches` view does not satisfy.

**Decision:** We chose to add `filepath` and `category_name` to per-pair JSON output (success and failure) and *not* to migrate the SQLite schema. Database consumers query the existing `category_matches` view (`schema.sql:139`) which already joins `result.filepath` and `category.category_name`.

**Consequences:**
- **Enables:** Self-describing JSON files for filesystem-grep debugging without schema-evolution risk.
- **Prevents:** Denormalisation of `result_category` and the migration burden it would carry.

**Alternatives considered:**
- **DB columns:** Rejected because the data is already queryable via the view; duplicating into normalised tables is denormalisation without justification.

### DR6: Per-pair `.error.json`, skip-on-rerun, no `--retry-failed` flag
**Status:** Accepted
**Confidence:** Medium
**Reevaluation triggers:** If users frequently want to retry whole batches of failures programmatically and discover that filesystem-rm scripting is friction.

**Decision:** We chose per-pair `r{id}_c{id}.error.json` artefacts containing the parser reason, full `reasoning_trace` extracted from the last response, full `last_response_content`, and transport-level `last_error`. `get_completed_pairs` treats `.error.json` as terminal so re-runs skip them; an end-of-run summary lists skipped-prior-failure paths loudly. No `--retry-failed` flag — manual deletion of the `.error.json` file is the retry path.

**Consequences:**
- **Enables:** Loud, debuggable failures. A failed pair that's deterministic stays failed across reruns. Operators see exactly why each pair failed and can decide whether to retry.
- **Prevents:** Silent retry loops on systematic failures. Aggregated `errors.jsonl` index drift versus per-file truth.

**Alternatives considered:**
- **Aggregated `errors.jsonl` index:** Rejected because per-file `*.error.json` is already grep-able and `ls` lists them.
- **Auto-retry across runs:** Rejected because a deterministically-failing pair would consume retries forever without operator awareness.
- **Have `--retry-failed` flag:** Rejected as YAGNI for v1; manual deletion is the v1 escape hatch and the flag can be added later if friction emerges.

### DR7: Smoke-test runs canned inference, not just model load
**Status:** Accepted
**Confidence:** High
**Reevaluation triggers:** If the canned inference fixtures become a maintenance burden across many job-types, or if model-load alone becomes a sufficient signal in practice.

**Decision:** We chose to make the smoke-test command run vLLM model load *and* a single canned chat-completion request against two fixture files (`container/smoketest_system_prompt.txt`, `container/smoketest_user_prompt.txt`) shipped inside the container image — rather than just a model-load-and-exit gate. Fixtures are not adapter-overridable; the smoke-test verifies the inference path, not adapter prompt content.

**Consequences:**
- **Enables:** End-to-end pipeline validation (vLLM serve + chat endpoint + JSON output path) before the operator commits 24h of SU to a real run. Catches issues a model-only load would miss (chat template mismatches, tokenizer issues during generation, OOM during inference rather than load).
- **Prevents:** False-positive "model loads, but actual inference crashes" outcomes that look fine to a load-only smoke-test.

**Alternatives considered:**
- **Model-load-only smoke-test:** Rejected because it doesn't catch inference-time failures. Loading a 35B-A3B model successfully and then OOM'ing on the first chat request is a known failure mode the smoke-test must catch.
- **Require vLLM version gate (refuse to submit if vLLM < required):** Rejected because pinning to specific vLLM versions creates a different brittleness; a smoke-test that empirically verifies the actual behaviour is more honest.
- **Adapter-supplied smoke-test prompts:** Rejected — smoke-test is a self-test of the runner; its fixtures are part of the runner's contract.

## Existing Patterns

This design follows established patterns from the codebase. Investigation surfaced the following:

- **Typer + Rich CLI structure** (`src/llm_discovery/cli.py`). Every command is `@app.command()`-decorated with `typer.Option(...)` defaults; errors print via `rprint("[red]...[/red]")` and `raise typer.Exit(1)`. New flags follow this pattern verbatim.
- **`typer.testing.CliRunner` test harness** (`tests/test_cli_process.py`, established in commit `c93f5bb` already merged). Mocks `run_processor` / `run_local_pipeline`, asserts custom paths thread through. New CLI flag tests follow this pattern.
- **Pydantic v2 models with PyYAML loading** (`src/llm_discovery/platform.py:38` — existing `PlatformConfig` with `display_name`, `ssh_host`, `remote_base`, etc.). `load_platforms(config_path) → Platforms` returns the parsed root. `QueueProfile`, `JobType`, and the new `PlatformsConfig` root model extend this exact pattern.
- **PBS template rendering via placeholder substitution** (`hpc/gadi.pbs.template` with `{{GPU_QUEUE}}`, `{{NCI_PROJECT}}`, `{{CONTAINER_PATH}}`; `submit_gadi_job` does the substitution and passes the rendered script to `qsub` via SSH). Expanded placeholder set follows the same `{{VAR}}` convention; `render_pbs_script` extracts the existing substitution logic into a single helper.
- **EXIT trap for vLLM cleanup in container entrypoints** (`container/entrypoint.sh:75-81`). The new `smoketest_entrypoint.sh` follows the same `trap cleanup EXIT` pattern, no `set -e`, kill+wait on `$VLLM_PID`.
- **SSH via fabric** (`fetch_remote_file`, `rsync_to_remote` in `platform.py`). The new `local_weights` validation uses the same `fabric.Connection` invocation pattern: `conn.run("test -d $path", warn=True)`.
- **Atomic JSON file writes** (`save_result_to_file` writes to `.tmp` then renames). `save_failure_to_file` follows the same atomic pattern.
- **Run-stats DB tracking** (`run_stats` table in `schema.sql`, populated by `start_run`/`finish_run` in `unified_processor.py`). Failure-log changes do not affect this; the existing `pairs_failed` counter remains accurate.
- **Test fixtures in `tests/conftest.py`** (`tmp_db`, `sample_corpus_dir`, `sample_prompts_dir`). New tests use these fixtures plus new YAML-config fixtures.

**Divergence:** `_GPU_QUEUE_CONFIGS` (a Python dict in `platform.py:232`) is replaced by an externalised YAML block. This is the central design goal — the dict's hardcoding is the user-named complaint — so the divergence is intentional and load-bearing.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: CLI flag threading for adapter-facing paths
**Goal:** Every adapter-facing path and per-invocation default becomes an explicit Typer option threaded through every orchestration layer. Commit `c93f5bb` already covers `--system-prompt` and `--prompts-dir` on `process`; this phase extends the same pattern to the rest of the surface.

**Components:**
- `src/llm_discovery/cli.py` — add `--db`, `--input-dir`, `--output-dir`, `--prompts-dir`, `--system-prompt`, `--server-url`, `--schema`, `--log-dir` to the `run` command. Drop the `Path("input/demo_corpus")`, `Path("corpus.db")`, `Path("out")`, `Path("prompts")`, `Path("system_prompt.txt")`, `Path("schema.sql")`, `Path("logs")`, `"http://localhost:8000"`, and `"RTX4090-e4b"` hardcodes inside `_run_local_pipeline`, `_run_container_pipeline`, `_run_remote_pipeline`, `_assemble_data_dir`. The `RTX4090-e4b` silent fallback at `cli.py:704` becomes an explicit error.
- `src/llm_discovery/local_runner.py` — `prepare_corpus(...)`, `run_container_pipeline(...)`, `run_local_pipeline(...)`, `start_vllm_server(...)`, `wait_for_health(...)` accept the threaded path/URL/port parameters; no hardcoded `Path("schema.sql")`, `Path("logs")`, `Path("system_prompt.txt")`, port `8000`.
- `tests/test_cli_run.py` (new) — covers each new flag on `run` (custom path threads through, default preserves behaviour, missing path errors cleanly).

**Dependencies:** None (already-merged commit `c93f5bb` is the precedent).

**Done when:** All hardcoded Class-1 paths and Class-2 server defaults removed from `cli.py`, `local_runner.py`. `run --help` lists the new flags. Tests covering AC1.1, AC1.2, AC1.3 pass. Existing tests still pass.

**Covers ACs:** run-config.AC1.1, run-config.AC1.2, run-config.AC1.3.
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: Pydantic schema and extended `config/platforms.yaml`
**Goal:** Externalise `_GPU_QUEUE_CONFIGS` into the YAML; introduce `QueueProfile`, `JobType`, `PlatformsConfig` Pydantic models with computed fields and cross-field validation. No CLI behaviour change yet — Phase 3 wires the schema into `deploy`.

**Components:**
- `src/llm_discovery/platform.py` — new `QueueProfile` and `JobType` Pydantic v2 models with `@computed_field` for `ncpus`/`mem_gb`/`jobfs_gb` and `@model_validator(mode="after")` for ngpus/walltime bounds. New `PlatformsConfig` root model linking platforms + queues + job_types, with a root-level validator that resolves each `JobType.queue` string against the queues block and binds `JobType.queue_profile`.
- `config/platforms.yaml` — new top-level `queues:` block (`gpuhopper` and `rtx4090` for now, matching existing `_GPU_QUEUE_CONFIGS` keys) and `job_types:` block (one entry per existing `_GPU_QUEUE_CONFIGS` entry, populated with both existing fields and the new ones from the design — `hf_repo`, `local_weights`, `ngpus`, `walltime`, `dtype`, `trust_remote_code`, `extra_vllm_args`, `smoketest_walltime`).
- `src/llm_discovery/platform.py` — new `load_job_type(name: str, yaml_path: Path) → JobType` function that loads `PlatformsConfig` and returns the resolved JobType. `_GPU_QUEUE_CONFIGS` dict and `get_gpu_queue_config(...)` and `generate_hpc_env(...)` *not yet removed* — Phase 3 is when they go away.
- `tests/test_platforms_yaml.py` (new) — fixture YAML files (valid + invalid in 5 ways: missing queue ref, ngpus over cap, walltime over cap, malformed walltime string, unknown queue type). Bound-validator and computed-field tests.

**Dependencies:** Phase 1 (independent in code but tested separately).

**Done when:** `PlatformsConfig` loads the canonical `config/platforms.yaml` without errors. Each existing `_GPU_QUEUE_CONFIGS` entry has a corresponding `job_types:` entry. Bound violations raise `ValidationError` with the offending field named. Tests covering AC2.1-2.4 pass.

**Covers ACs:** run-config.AC2.1, run-config.AC2.2, run-config.AC2.3, run-config.AC2.4.
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: Extended `deploy` command driven by the YAML
**Goal:** `deploy` reads `JobType` from the YAML, validates remote `local_weights`, renders the expanded PBS template, qsubs, writes `submitted.json`. `_GPU_QUEUE_CONFIGS` deleted; all callers migrated to `load_job_type` / `render_pbs_script`.

**Components:**
- `src/llm_discovery/cli.py` — extend `deploy` with `--config PATH` (default `config/platforms.yaml`) and `--job-type NAME` (replaces `--gpu-queue` which becomes a deprecated alias for one release cycle). Validate `local_weights` via `fabric.Connection.run("test -d ...", warn=True)` before any state-changing action. On failure: clear error citing the missing path, exit 1.
- `src/llm_discovery/platform.py` — `PlatformConfig.gpu_queue` field removed from the Pydantic model. The corresponding key removed from each entry in `config/platforms.yaml`'s `platforms:` block. Job-type selection moves entirely to the new `--job-type` CLI flag + `job_types:` YAML block. This eliminates the orphan-field risk where future code might re-derive a fallback queue from `platform.gpu_queue`.
- `src/llm_discovery/platform.py` — new `render_pbs_script(template_path, job_type, project, container_path, walltime_override=None) → str` helper. `submit_gadi_job` and `submit_ping_job` rewritten to use `render_pbs_script`. `_GPU_QUEUE_CONFIGS`, `get_gpu_queue_config`, `generate_hpc_env`, `resolve_pbs_queue` removed. `upload_hpc_env` rewritten to render `hpc_env.sh` from a `JobType` instance.
- `hpc/gadi.pbs.template` — placeholder set expanded: existing `{{GPU_QUEUE}}`, `{{NCI_PROJECT}}`, `{{CONTAINER_PATH}}` plus new `{{NGPUS}}`, `{{NCPUS}}`, `{{MEM_GB}}`, `{{JOBFS_GB}}`, `{{WALLTIME}}`, `{{STORAGE}}` (now includes `+gdata/{project}`), `{{JOB_NAME}}`, `{{LOG_OUT}}`, `{{LOG_ERR}}`. Hardcoded `ngpus=4`, `ncpus=48`, `mem=380GB`, `walltime=04:00:00`, `jobfs=200GB` removed.
- `src/llm_discovery/cli.py` — after `submit_gadi_job` returns the job ID, write `runs/<run-id>/submitted.json` to the remote via SSH; `<run-id>` = `{isotime}-{short_sha}`. Snapshot is the `JobType.model_dump_json()` plus `QueueProfile.model_dump_json()`.
- `tests/test_deploy_yaml.py` (new) — mock fabric Connection, mock qsub. Tests for: weight validation refusal path, bound-violation refusal path, valid submission writes correct PBS resources and `submitted.json`.
- `tests/test_platform.py` — migrate the 7 pre-existing failing tests (currently failing on HEAD per the session context) onto the new YAML-driven path; old `_GPU_QUEUE_CONFIGS` references removed.

**Dependencies:** Phases 1-2.

**Done when:** `_GPU_QUEUE_CONFIGS` import returns `ImportError` (deleted). `deploy --config <path> --job-type <name> --project <p>` end-to-end against a stub remote produces correct PBS template content + `submitted.json` + correct error paths. Tests covering AC3.1-3.5 pass.

**Covers ACs:** run-config.AC3.1, run-config.AC3.2, run-config.AC3.3, run-config.AC3.4, run-config.AC3.5.
<!-- END_PHASE_3 -->

<!-- START_PHASE_4 -->
### Phase 4: `smoke-test` command and smoketest entrypoint
**Goal:** New CLI verb that submits a 10-minute PBS job loading the model and running one canned inference round-trip; PASS/FAIL reported.

**Components:**
- `src/llm_discovery/cli.py` — new `@app.command()` `smoke_test(...)` with `--config`, `--job-type`, `--platform`, `--project`. Reuses `render_pbs_script` with `walltime_override = job_type.smoketest_walltime` and `template_path = "hpc/gadi.smoketest.template"`.
- `hpc/gadi.smoketest.template` (new) — short PBS script. Same placeholder set as production template; binds `/data` and `/model_cache`; calls `/opt/llm-discovery/container/smoketest_entrypoint.sh` instead of `entrypoint.sh`.
- `container/smoketest_entrypoint.sh` (new) — sources `hpc_env.sh`, builds vLLM cmd via `lib_vllm_cmd.sh::build_vllm_cmd` (existing), launches vLLM in background, EXIT trap for cleanup, polls `/health`, then POSTs one chat-completion request to `/v1/chat/completions` using `curl`, checks response body has non-empty `message.content`. Emits `PASS:` or `FAIL:` to stdout.
- `container/smoketest_system_prompt.txt` (new) — canned 2-line system prompt: "you are a tiny test classifier; always answer in JSON".
- `container/smoketest_user_prompt.txt` (new) — canned user prompt: 'is the sky blue? Answer with `{"match": "yes"}` or `{"match": "no"}`'.
- `container/pipeline.def` — copy the new fixture files and `smoketest_entrypoint.sh` into the image.
- `src/llm_discovery/platform.py` — new `submit_smoketest_job(...)` mirroring `submit_ping_job` but with the smoketest template + 10-minute walltime clamp.
- `src/llm_discovery/cli.py` — `_wait_for_smoketest` reuses `_wait_for_ping`'s verdict logic.
- `tests/test_smoketest.py` (new) — mock SSH + qsub; assert smoketest template contains the right walltime clamp and points at `smoketest_entrypoint.sh`.

**Dependencies:** Phase 3 (uses `render_pbs_script`).

**Done when:** `llm-discovery smoke-test --help` shows the command. End-to-end stub test produces a rendered PBS that points at `smoketest_entrypoint.sh` with walltime ≤ 10 min. Container rebuild includes new fixture files. Test covering AC7.1 passes (manual on Gadi for the actual PBS run).

**Covers ACs:** run-config.AC7.1.
<!-- END_PHASE_4 -->

<!-- START_PHASE_5 -->
### Phase 5: Per-pair failure logs and origin metadata in `unified_processor.py`
**Goal:** Failed pairs produce `r{id}_c{id}.error.json` with full reasoning trace and last-response content; success and failure JSON both carry origin metadata; re-runs skip prior failures with a loud summary.

**Components:**
- `src/llm_discovery/unified_processor.py` — `build_request_body(...)` gains `filepath: str, category_name: str` parameters. Work-queue tuple expands to `(custom_id, body, filepath, category_name)`. `_handle_completed_future` and `_run_worker_loop` unpack the extended tuple. `parse_response` returns parsed dicts that include `filepath` and `category_name`. `_handle_completed_future` stops discarding the failure reason; on retry exhaustion calls new `save_failure_to_file(...)` with `{custom_id, result_id, category_id, filepath, category_name, attempts, reason, reasoning_trace, last_response_content, last_error, timestamp}`.
- `src/llm_discovery/unified_processor.py` — new `save_failure_to_file(failure: dict, output_dir: Path) → bool` mirroring the atomic-write pattern of `save_result_to_file`. New extraction logic: `reasoning_trace` from last response via existing `extract_reasoning(content)` or `message.reasoning_content`/`message.reasoning`; `last_response_content` is the full body, not truncated.
- `src/llm_discovery/unified_processor.py` — `get_completed_pairs` extended to glob `r*_c*.error.json` and treat those pairs as terminal. `_display_run_summary` extended with a "Skipped due to prior failure: N" row when N > 0, listing error-file paths.
- `tests/test_unified_processor.py` — new tests: `do_request` stub raises always → assert one `.error.json` per pair with expected fields; re-run against same output dir → 0 new pairs, summary lists skipped count and paths; assert `filepath` + `category_name` fields in both success and error JSON.

**Dependencies:** None (independent of Phases 1-4 in code; ships with them).

**Done when:** Failed-pair test produces correct `.error.json`. Re-run test shows skip behaviour and summary line. Origin metadata test asserts both fields in success and error JSON. Tests covering AC5.1-5.3 and AC6.1 pass.

**Covers ACs:** run-config.AC5.1, run-config.AC5.2, run-config.AC5.3, run-config.AC6.1.
<!-- END_PHASE_5 -->

<!-- START_PHASE_6 -->
### Phase 6: Documentation maintenance and cleanup
**Goal:** README, CLAUDE.md, and design docs reflect the new CLI surface and YAML schema. No stale references to `_GPU_QUEUE_CONFIGS` remain.

**Components:**
- `README.md` — CLI reference table updated for `process` (already done in commit 1), `run`, `deploy`, `smoke-test`, `init` flag changes. New "Configuring a job type" section pointing at `config/platforms.yaml` schema.
- `CLAUDE.md` — contracts table at line 49 updated for `run`, `deploy`, `init`, `process` (done), `smoke-test` (new row); GPU-queue paragraph at line 69 rewritten to describe the new `queues:` and `job_types:` blocks instead of `_GPU_QUEUE_CONFIGS` dict; `Freshness:` bumped to commit date.
- `container/CLAUDE.md` — entrypoint contract paragraph updated if any field changed (probably not, but verify); add reference to `smoketest_entrypoint.sh` and the canned fixture files.
- `docs/dependency-rationale.md` — no new dependencies introduced (Pydantic v2, PyYAML, fabric, requests all pre-existing) — *no entry needed*.
- Static check: grep for `_GPU_QUEUE_CONFIGS` across repo; assert no production-code references remain (test files may reference the migrated form).

**Dependencies:** Phases 1-5 (documentation reflects the final state).

**Done when:** README CLI table is current. CLAUDE.md contracts table includes every command and every flag. `git grep _GPU_QUEUE_CONFIGS` returns no production references. Freshness dates bumped.

**Covers ACs:** None directly (cross-cutting documentation maintenance).
<!-- END_PHASE_6 -->

## Additional Considerations

**Already-shipped work.** Commit `c93f5bb` already added `--system-prompt` and `--prompts-dir` to the `process` command, with tests in `tests/test_cli_process.py` and README/CLAUDE.md updates. Phase 1 of this plan completes the same pattern across the rest of the CLI surface; Phase 1 should *not* re-do `process`.

**Adapter integration (Lise).** The downstream Lise project vendors this repo as a git submodule and runs `llm-discovery process` against their own corpus DB and 15-category safeguard rubric on Gadi gpuhopper. Their workflow under this design:
1. `cd llm-discovery-submodule && uv pip install -e .` once.
2. Maintain their own `lise/config/platforms.yaml` outside the submodule, listing their job-types pointing at their `local_weights` paths on `/scratch/<their-project>/models/`.
3. Stage weights via `llm-discovery download-model --config their-platforms.yaml --job-type their-job` + `upload-model-cache` (rewritten to be YAML-aware in Phase 3 implicitly).
4. Run their own prep-db over their corpus, then `llm-discovery deploy --config their-platforms.yaml --job-type their-job --project <theirs>` per submission.
5. Edit their YAML to add a new model? Run `llm-discovery smoke-test --config ... --job-type new-one` first to validate.

No edits to any submodule file required for any of the above.

**vLLM v0.19.0 compatibility for new model architectures.** Internet-research surfaced that vLLM v0.19.0 (the container's pin) does ship Qwen3.5/3.6 fixes per its release notes, but the Qwen3.6-35B-A3B release post-dates the container image by hours. The smoke-test command (Phase 4) is the empirical mitigation: rather than gating on a specific vLLM version, the operator runs smoke-test after each YAML edit and only commits production walltime once smoke-test passes. If the container's vLLM doesn't load the model, smoke-test FAIL is visible in stdout; rebuild the container against a newer vLLM tag if needed.

**Backward compatibility window.** `--gpu-queue` on `deploy` / `init` / `run` becomes a deprecated alias for `--job-type`, accepted for one release cycle with a deprecation warning to stderr. After that release it's removed. This avoids breaking any external scripting that may already use `--gpu-queue`.

**NCI storage directive correctness.** The existing `hpc/gadi.pbs.template` has `#PBS -l storage=scratch/{{NCI_PROJECT}}` which is missing the `+gdata/{{NCI_PROJECT}}` portion required to access `/g/data/<project>` from inside PBS jobs. Phase 3's template rewrite fixes this; the `{{STORAGE}}` placeholder renders as `scratch/<project>+gdata/<project>` (no leading `/`, plus-separated, gdata explicit per NCI documentation).

**Implementation scoping.** This design has 6 implementation phases, within the 8-phase limit of impl-plan-write. No splitting required.

**Smoke-test endpoint choice is intentional.** The existing `hpc/gadi.ping.template` (used by `init`) posts to vLLM's legacy `/v1/completions` endpoint to verify the server is alive. The new `smoke-test` command posts to `/v1/chat/completions` because that is the endpoint production `process` uses (`build_request_body` constructs chat-completion requests). The two endpoints exercise different code paths in vLLM (chat templating, reasoning-parser routing). This design intentionally does *not* unify them: ping remains a liveness probe; smoke-test is the production-path probe. An implementer should not "harmonise" the two by copying the ping endpoint into `smoketest_entrypoint.sh` — that would defeat the smoke-test's purpose of catching chat-template / reasoning-parser failures before production walltime.
