# Project Glossary

Ubiquitous language for the LLM Document Discovery project. Every term here means the same thing in code, docs, and conversation. Per-design-plan glossaries should reference this file rather than redefine its terms.

## Domain Terms

- **Lise (downstream adapter)**: The downstream project that vendors this repository as a git submodule. Lise runs `llm-discovery` against its own corpus database and 15-category safeguard rubric on Gadi. The motivating use case for the run-config design (`docs/design-plans/2026-04-23-run-config.md`) is to allow Lise to drive the pipeline entirely through CLI flags and its own `platforms.yaml` without modifying any submodule file.
- **submodule**: A git mechanism for embedding one repository inside another at a pinned commit. Lise uses this to vendor `llm-discovery`; the adapter-isolation design ensures Lise never needs to edit the embedded repo's files.
- **pair**: One (document, category) combination — a single unit of classification work. Each pair produces exactly one terminal artefact (success JSON or — planned — error JSON).
- **job-type**: A named submission profile keyed in `_GPU_QUEUE_CONFIGS` today (planned: in `config/platforms.yaml`'s `job_types:` block). Holds vLLM model parameters, PBS resource parameters, and weight-staging paths. Examples: `gpuhopper-qwen3`, `RTX4090-e4b`.
- **smoke-test (verb)**: A planned CLI command (`llm-discovery smoke-test`) that submits a short PBS job running the full vLLM load-and-infer path with canned fixture prompts. Intended for operator use after YAML edits to validate a new job-type before committing production walltime (`docs/design-plans/2026-04-23-run-config.md`).
- **reasoning trace**: The intermediate chain-of-thought text produced by reasoning-capable models (Qwen3, Gemma 4) before their final answer. Some vLLM backends surface it in a separate response field; others inline it with special tokens.
- **system prompt**: The verbatim instruction text loaded as the LLM's `system` role message at request time. Specified per adapter via `--system-prompt PATH` since commit `c93f5bb`.

## Technical Terms

- **vLLM**: An open-source LLM inference server that exposes an OpenAI-compatible HTTP API (`/v1/chat/completions`). The pipeline launches vLLM inside the container and directs classification requests at it via that endpoint.
- **Apptainer / Singularity**: Container runtimes used for HPC workloads. Apptainer is the successor to Singularity; the local GPU path uses Apptainer and the Gadi HPC path uses Singularity (Gadi's installed runtime). Both accept the same `.sif` image format built from `container/pipeline.def`.
- **PBS (Portable Batch System)**: The job scheduler on NCI Gadi. Jobs are described in shell scripts with `#PBS` directives specifying resources, then submitted via `qsub`. The scheduler queues them and dispatches them to available nodes.
- **NCI Gadi**: The Australian National Computational Infrastructure's flagship HPC cluster. Access is via SSH; jobs must be submitted through PBS to run on GPU nodes.
- **gpuhopper queue**: A Gadi PBS queue providing access to A100 GPU nodes. Resource ratios (CPUs, memory, jobfs per GPU) are fixed by the queue's allocation rules.
- **SU (Service Units)**: The currency of compute allocation on NCI Gadi. Jobs are charged SU proportional to resources consumed.
- **walltime**: The maximum wall-clock duration a PBS job is permitted to run, declared as `HH:MM:SS`. Jobs that exceed their walltime are killed by the scheduler without producing output.
- **jobfs**: A per-job local scratch filesystem on Gadi nodes, faster than `/scratch` for temporary files. Used by vLLM for compile and inductor caches during inference.
- **ngpus**: The number of GPUs requested for a PBS job. Drives all other resource calculations via the queue's per-GPU ratios.
- **MoE (Mixture of Experts)**: A model architecture where only a subset of parameters are active per token. Qwen3.6-35B-A3B is a MoE model: 35 billion total parameters, ~3 billion activated per forward pass.
- **tensor_parallel (TP)**: The vLLM parameter controlling how many GPUs share each model layer's tensor computations.
- **data_parallel (DP)**: The vLLM parameter controlling how many independent model replicas run in parallel across GPUs. `tensor_parallel × data_parallel` should equal `ngpus`.
- **dtype**: The floating-point precision used to load model weights. Common values: `bfloat16`, `float16`, `auto`.
- **max_model_len**: The maximum input + output token length vLLM will accept per request. Constrains KV cache size.
- **trust_remote_code**: A vLLM / transformers flag that permits loading model code from the Hugging Face repo. Required for some bleeding-edge architectures.
- **Pydantic v2**: Python data-validation library. Used to parse `config/platforms.yaml` into typed model objects.
- **fabric SSH**: The `fabric` Python library used in `src/llm_discovery/platform.py` to run commands and transfer files on remote hosts via SSH.
- **Hugging Face repo (`hf_repo`)**: The Hugging Face model identifier (e.g. `google/gemma-4-31B-it`) used by `download-model` to fetch weights into the local HF cache.
- **`local_weights`**: The path on the remote HPC scratch where model weights are expected to reside at job submission time. (Planned: `JobType.local_weights`, `docs/design-plans/2026-04-23-run-config.md`.)
- **`category_matches` view**: A SQLite view in `schema.sql` (`c93f5bb`) that joins `result_category` with `result` (for `filepath`) and `category` (for `category_name`).

## Abbreviations

| Abbreviation | Full Form | Context |
|--------------|-----------|---------|
| TP | tensor_parallel | vLLM dispatch parameter |
| DP | data_parallel | vLLM dispatch parameter |
| MoE | Mixture of Experts | Model architecture |
| SU | Service Unit | NCI Gadi compute allocation currency |
| HPC | High-Performance Computing | Cluster/supercomputer context |
| PBS | Portable Batch System | Gadi job scheduler |
| ERD | Entity-Relationship Diagram | Database modelling artefact |
| AC | Acceptance Criterion | Verification item in a design plan (`{slug}.AC{N}.{M}`) |
| DoD | Definition of Done | Top-level success contract in a design plan |

## Deprecated Terms

| Old Term | Replaced By | Since | Reason |
|----------|-------------|-------|--------|
| `--gpu-queue` (CLI flag) | `--job-type` (planned) | `docs/design-plans/2026-04-23-run-config.md` | The flag selects a job-type entry, not a PBS queue (queue is one field of the job-type). The new name is more accurate. Old name kept as deprecated alias for one release cycle. |
| `_GPU_QUEUE_CONFIGS` (Python dict) | `config/platforms.yaml::job_types` (planned) | `docs/design-plans/2026-04-23-run-config.md` | Hardcoded Python dict prevented adapter overrides without submodule edits. Externalised to YAML for adapter-supplied configuration. |
