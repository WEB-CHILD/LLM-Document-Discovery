# LLM Document Discovery

Reproducible pipeline for classifying historical web documents (1996-2005) using large language models. Extracts linguistic and structural features from children's web content archived by the Internet Archive, producing a structured SQLite database of classifications with supporting blockquote evidence.

## Prerequisites

- Python 3.12 or 3.13 (vLLM does not yet support 3.14)
- [uv](https://docs.astral.sh/uv/) package manager
- HuggingFace account (free, for model access)
- GPU access (local or HPC) -- Gemma 4 works for local testing on modest GPUs
- For HPC: SSH access to NCI Gadi or DeiC UCloud

## Quickstart (local GPU)

```bash
git clone <repo-url>
cd LLM-Document-Discovery
uv sync

# Install vLLM nightly (required for Gemma 4, not managed by uv sync)
uv pip install -U vllm --pre \
  --extra-index-url https://wheels.vllm.ai/nightly/cu129 \
  --extra-index-url https://download.pytorch.org/whl/cu129 \
  --index-strategy unsafe-best-match
uv pip install transformers==5.5.0

# Run the full pipeline (RTX 4090 example)
uv run llm-discovery run --platform local --gpu-type RTX4090 --yes

# Browse results
uv run datasette corpus.db
```

GPU types are configured in `config/machines.yaml`. Available types: `RTX4090`, `V100`, `H200`, `H100`. Each selects the appropriate model and vLLM parameters automatically.

### Verify results

```bash
sqlite3 corpus.db "SELECT COUNT(*) FROM result_category"                    # expect: 105
sqlite3 corpus.db "SELECT COUNT(DISTINCT category_id) FROM result_category" # expect: 21
sqlite3 corpus.db "SELECT DISTINCT match FROM result_category"              # expect: yes/maybe/no
sqlite3 corpus.db "SELECT model, pairs_processed FROM run_stats"            # verify model name
```

### HPC deployment (Gadi)

#### First-time setup (once per HPC environment)

```bash
# 1. Build container image locally (requires sudo for overlay filesystems)
#    Validates automatically after build (checks size and CLI callable)
sudo $(which uv) run llm-discovery build --output pipeline.sif

# 2. Download model weights to local HF cache (checks disk space first)
uv run llm-discovery download-model --gpu-queue gpuvolta

# 3. Initialise Gadi: stage container, rsync model weights, run smoke test
uv run llm-discovery init --platform gadi --project <project-code> --gpu-queue gpuvolta

# 4. Check the smoke test completed
uv run llm-discovery status --platform gadi --job-id <job-id> --project <project-code>
```

The `download-model` command downloads model weights to the local HuggingFace cache
(respects `$HF_HOME`). The `init` command then stages the container to
`/scratch/<project-code>/containers/`, rsyncs the cached weights to
`/scratch/<project-code>/hf_cache/` (checking remote disk space before transfer),
and submits a ping job that verifies vLLM starts and responds inside the container.

#### Per-corpus workflow (each time you process a new corpus)

```bash
# 1. Fetch corpus documents
uv run llm-discovery fetch

# 2. Deploy: assembles data dir (prep-db, preflight, assets), uploads, submits job
uv run llm-discovery deploy --platform gadi --project <project-code> --gpu-queue gpuhopper

# 3. Monitor and retrieve results
uv run llm-discovery status --platform gadi --job-id <job-id> --project <project-code>
uv run llm-discovery retrieve --platform gadi --project <project-code>
```

See [docs/testing-plan-local-4090.md](docs/testing-plan-local-4090.md) for the full tier-by-tier testing plan.

## CLI Reference

| Command          | Description                                              |
|------------------|----------------------------------------------------------|
| `build`          | Build Apptainer container image for HPC deployment        |
| `build --validate` | Verify existing container image (size, CLI callable)    |
| `download-model` | Download model weights to local HF cache for HPC upload   |
| `init`           | First-time HPC setup: stage container, rsync weights, smoke test |
| `fetch`          | Download pages from Internet Archive, convert to markdown |
| `prep-db`        | Create and populate corpus database from documents/prompts |
| `preflight`      | Validate documents in corpus database                     |
| `process`        | Run LLM classification on document-category pairs         |
| `import-results` | Import JSON result files into corpus database             |
| `validate`       | Check remote HPC environment readiness                    |
| `deploy`         | Sync code/data to HPC and submit job                     |
| `status`         | Check status of running HPC job                          |
| `retrieve`       | Pull results (corpus.db) back from HPC                   |
| `run`            | Execute the complete pipeline end-to-end                  |

Run any command with `--help` for detailed options.

## Architecture

The pipeline executes in stages:

1. **fetch** -- Downloads pages from the Internet Archive Wayback Machine via the `id_` endpoint, converts HTML to markdown with `{timestamp}/{url}` headers.

2. **prep-db** -- Creates SQLite database from `schema.sql`, syncs 21 category prompts from `prompts/*.yaml`, syncs documents with SHA-256 change detection and automatic splitting for large documents.

3. **preflight** -- Affirmative validation: documents must prove they contain usable text (checks for binary content, minimum length, printable ratio).

4. **process** -- Streaming architecture with reader thread (fetchmany from DB), bounded work queue (100 items), and ThreadPoolExecutor workers making concurrent requests to a vLLM server. Atomic JSON file writes for crash-safe resumability.

5. **import-results** -- Reads JSON/JSONL result files and inserts into the database with `INSERT OR IGNORE` idempotency.

On HPC nodes, `scripts/process_corpus.sh` orchestrates the on-node pipeline: installs GPU deps, starts vLLM in tmux, waits for health, runs pipeline steps, kills server on exit.

## Platform Setup

- [NCI Gadi setup](docs/gadi-setup.md) -- SSH keys, project allocation, module loading
- [DeiC UCloud setup](docs/ucloud-setup.md) -- Account, container configuration

## Container Build (Apptainer)

To build the pipeline container image:

```bash
sudo $(which uv) run llm-discovery build --output pipeline.sif
```

**Ubuntu 24.04 prerequisite:** Apptainer requires unprivileged user namespaces. If builds fail, set:

```bash
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
# Persist across reboots:
echo "kernel.apparmor_restrict_unprivileged_userns=0" | sudo tee /etc/sysctl.d/99-apptainer.conf
```

Run the container with GPU access:

```bash
apptainer exec --nv \
    --bind ./data:/data \
    --bind ~/.cache/huggingface:/model_cache --env HF_HOME=/model_cache \
    pipeline.sif /opt/llm-discovery/container/entrypoint.sh
```

See `container/hpc_env.rtx4090.sh` for local GPU configuration and `container/entrypoint.sh` header for bind mount requirements.

## Development

```bash
uv sync --extra dev          # Install with test dependencies
uv run pytest tests/ -v      # Run tests (excludes network/GPU by default)
uv run pytest tests/ -v -m network    # Run network integration tests
```

## Citation

If you use this software, please cite:

> Ballsun-Stanton, B. (2026). *LLM Document Discovery* [Software]. https://github.com/WEB-CHILD/LLM-Document-Discovery

See [CITATION.cff](CITATION.cff) for machine-readable citation metadata.

This pipeline was built for the paper [Exploring the Archived Web through AI-Assisted Document Discovery](https://github.com/WEB-CHILD/exploring-the-archived-web-through-ai-assisted-document-discovery).

## Licence

Creative Commons Attribution 4.0 International. See [LICENSE.md](LICENSE.md).
