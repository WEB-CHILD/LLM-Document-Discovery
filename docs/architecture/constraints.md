# Quality Constraints

Measurable limits on system behaviour. Each constraint has a metric, a target, and a verification method. Sources are cited inline.

## Performance

| Constraint | Metric | Target | Verification |
|-----------|--------|--------|-------------|
| Per-request inference budget | Tokens per `/v1/chat/completions` request (system + category prompt + content + response) | ≤ 32,768 tokens (`max_model_len`) | Set per job-type in `config/platforms.yaml::job_types[*].max_model_len` (planned, `docs/design-plans/2026-04-23-run-config.md`); enforced by vLLM rejecting overflowing requests. |
| Document chunking threshold | `result.content` character length | ≤ 80,000 chars before split | `MAX_CONTENT_LENGTH = 80000` in `src/llm_discovery/unified_processor.py` and `src/llm_discovery/prep_db.py` (`c93f5bb`); enforced at prep-db time and by reader's filter. |
| Worker concurrency | Concurrent in-flight requests | Match `VLLM_MAX_SEQS` per job-type | `--concurrency` flag on `process` (`src/llm_discovery/cli.py::process`, `c93f5bb`); ThreadPoolExecutor sized accordingly. |
| Smoke-test runtime ceiling | Total walltime for `smoke-test` PBS job | ≤ 10 minutes (`00:10:00`), or `JobType.smoketest_walltime` if set | Server-side clamp in `render_pbs_script` (planned, `docs/design-plans/2026-04-23-run-config.md`). |

## Capacity

| Constraint | Metric | Current | Limit | Verification |
|-----------|--------|---------|-------|-------------|
| Single-job GPU count | `ngpus` per PBS submission | Per job-type | 1-4 (single-node only) | Pydantic `@model_validator` against `QueueProfile.max_ngpus_per_job` (planned). |
| Single-job walltime | `walltime` per PBS submission | Per job-type | ≤ 48 hours on gpuhopper | `QueueProfile.max_walltime_hours = 48` (planned); enforced at YAML load. |
| Per-GPU CPU allocation | `ncpus` per ngpus | Derived | `12 × ngpus` | `JobType.ncpus` `@computed_field` (planned). |
| Per-GPU memory allocation | `mem` per ngpus | Derived | `256 GB × ngpus` | `JobType.mem_gb` `@computed_field` (planned). |
| Per-GPU jobfs allocation | `jobfs` per ngpus | Derived | `min(400 × ngpus, 1741) GB` (full-node cap) | `JobType.jobfs_gb` `@computed_field` (planned). |
| Per-pair retry budget | Total HTTP attempts on the same pair | Up to 3 | `max_retries = 3` in `_handle_completed_future` (`src/llm_discovery/unified_processor.py`, `c93f5bb`). | Hardcoded in worker loop. |
| Categories per corpus | Category count loaded by `prep-db` | 21 (this repo's demo) | n/a (adapter-controlled) | Loaded from `prompts/*.yaml` (`src/llm_discovery/prep_db.py::sync_categories`, `c93f5bb`); Lise will run with 15. |

## Cost

| Constraint | Metric | Target | Verification |
|-----------|--------|--------|-------------|
| SU charging rate (Gadi gpuhopper) | Service Units per resource-hour | 7.5 SU / resource-hour | `QueueProfile.su_per_resource_hour` field (planned, `docs/design-plans/2026-04-23-run-config.md`); informational, not enforced. |

## Availability and Operational

| Constraint | Requirement | Verification |
|-----------|-------------|-------------|
| Compute-node internet access | None — Gadi compute nodes have no outbound internet. Model weights MUST be staged to `/scratch/<project>/models/<job-type>/` before submission. | Pre-submit SSH check `test -d $local_weights` in `deploy` (planned, `docs/design-plans/2026-04-23-run-config.md`); refuses to qsub if missing. |
| JOBFS ephemerality | JOBFS is per-job and wiped on exit. Production output must NOT be written to JOBFS. | `entrypoint.sh` writes outputs to `/data/out/` (bind-mounted scratch), not `$PBS_JOBFS` (`container/entrypoint.sh::70-71`, `c93f5bb`). |
| Container EXIT trap | vLLM background process must be killed on any container exit (success, failure, crash). | `trap cleanup EXIT` without `set -e` (`container/entrypoint.sh::75-81`, `c93f5bb`); convention: NEVER `set -e` because trap must always fire. |
| Bind-mount contracts | `/data/` and `/model_cache/` paths are part of the container API; renaming breaks every deployment. | Documented in `container/CLAUDE.md`; verified by `tests/test_container_e2e.py`. |
| Atomic JSON write | Per-pair JSON files are written atomically (temp-then-rename) to prevent half-written files surviving a crash. | `save_result_to_file` (`src/llm_discovery/unified_processor.py`, `c93f5bb`); planned `save_failure_to_file` follows same pattern. |

## Security

| Constraint | Requirement | Verification |
|-----------|-------------|-------------|
| HF token handling | `$HF_TOKEN` is read from environment by `download-model`; never committed; never logged. | Validation check at `src/llm_discovery/platform.py::_check_remote_hf_token` (`c93f5bb`); `.env` patterns gitignored. |
| Container runs as calling user | Apptainer / Singularity runs as the invoking user, not root. Bind mounts MUST NOT target `/root/.cache/huggingface`. | Documented in `container/CLAUDE.md::Bind mounts`; enforced by `--bind <hf-cache>:/model_cache --env HF_HOME=/model_cache` pattern. |
| `trust_remote_code` opt-in | Per-job-type opt-in; not globally enabled. | `JobType.trust_remote_code: bool = False` default (planned, `docs/design-plans/2026-04-23-run-config.md`). |

## Constraint History

| Date | Constraint | Change | Reason |
|------|-----------|--------|--------|
| 2026-04-23 | Bootstrap | Initial documentation of all constraints. | First architecture-doc creation, triggered by `run-config` design plan. |
