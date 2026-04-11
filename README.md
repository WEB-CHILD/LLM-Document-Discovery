# LLM Document Discovery

Reproducible pipeline for classifying historical web documents (1996-2005) using large language models. Extracts linguistic and structural features from children's web content archived by the Internet Archive, producing a structured SQLite database of classifications with supporting blockquote evidence.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- HuggingFace account (free, for model access)
- GPU access (local or HPC) -- Gemma 4 works for local testing on modest GPUs
- For HPC: SSH access to NCI Gadi or DeiC UCloud

## Quickstart

```bash
git clone <repo-url>
cd LLM-Document-Discovery
uv sync
uv run llm-discovery run --platform local --yes    # Fetches demo pages + full pipeline
datasette corpus.db                                 # Browse results
```

For HPC deployment (Gadi):

```bash
uv run llm-discovery run --platform gadi --project <code> --yes
```

For local testing with a smaller model:

```bash
VLLM_MODEL=google/gemma-4-12b uv run llm-discovery run --platform local --yes
```

## CLI Reference

| Command          | Description                                              |
|------------------|----------------------------------------------------------|
| `fetch`          | Download pages from Internet Archive, convert to markdown |
| `prep-db`        | Create and populate corpus database from documents/prompts |
| `preflight`      | Validate documents in corpus database                     |
| `process`        | Run LLM classification on document-category pairs         |
| `import-results` | Import JSON result files into corpus database             |
| `validate`       | Check remote HPC environment readiness                    |
| `deploy`         | Sync code to HPC and submit job                          |
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

## Development

```bash
uv sync --extra dev          # Install with test dependencies
uv run pytest tests/ -v      # Run tests (excludes network/GPU by default)
uv run pytest tests/ -v -m network    # Run network integration tests
```

## Citation

See [CITATION.cff](CITATION.cff) for citation information.

## Licence

Creative Commons Attribution 4.0 International. See [LICENSE.md](LICENSE.md).
