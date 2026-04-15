# Dependency Rationale

Falsifiable justifications for every direct dependency. Each entry records why the package was added, what evidence supports its use, and who it serves.

Maintained by design plans (when adding deps) and controlled-dependency-upgrade (when auditing). Reviewed by restate-our-assumptions (periodic philosophical audit).

## vllm
**Added:** 2026-04-09
**Design plan:** docs/design-plans/2026-04-09-reproducible-demo.md
**Claim:** We use vLLM to serve gpt-oss-120b on GPU hardware with OpenAI-compatible API. No alternative provides equivalent batching performance (PagedAttention, tensor parallelism) for self-hosted inference.
**Evidence:** `src/llm_discovery/unified_processor.py` makes HTTP requests to vLLM server; `scripts/start_server.sh` starts vLLM.
**Serves:** Runtime users (HPC GPU nodes)

## typer
**Added:** 2026-04-09
**Design plan:** docs/design-plans/2026-04-09-reproducible-demo.md
**Claim:** We use Typer for the `llm-discovery` CLI with subcommands (build, download-model, init, fetch, prep-db, preflight, process, import-results, validate, deploy, status, retrieve, run). Provides type-annotated argument parsing and auto-generated help.
**Evidence:** `src/llm_discovery/cli.py` defines the Typer app.
**Serves:** Runtime users (local machine)

## rich
**Added:** 2026-04-09
**Design plan:** docs/design-plans/2026-04-09-reproducible-demo.md
**Claim:** We use Rich for terminal progress bars, status display, and formatted output in the CLI. Typer uses Rich internally; explicit dependency for direct Rich usage in fetch/deploy progress.
**Evidence:** `src/llm_discovery/cli.py`, `src/llm_discovery/fetch.py`, `src/llm_discovery/platform.py` use Rich progress and status.
**Serves:** Runtime users (local machine)

## warcio
**Added:** 2026-04-09
**Design plan:** docs/design-plans/2026-04-09-reproducible-demo.md
**Claim:** warcio will be used by the WARC-based fetch path (`fetch_warc.py`) to extract HTML from downloaded WARC records via `ArchiveIterator`, following the ArchiveSpark pattern. Currently a stub; the active fetch path (`fetch.py`) uses the Wayback `id_` endpoint directly.
**Evidence:** `src/llm_discovery/fetch_warc.py` (stub, not yet implemented). Reference: https://github.com/helgeho/ArchiveSpark/blob/master/notebooks/Downloading_WARC_from_Wayback.ipynb
**Serves:** Runtime users (local machine, fetch subcommand)

## markdownify
**Added:** 2026-04-09
**Design plan:** docs/design-plans/2026-04-09-reproducible-demo.md
**Claim:** We use markdownify to convert HTML extracted from WARC records to markdown format. Produces output compatible with the existing corpus file format.
**Evidence:** `src/llm_discovery/fetch.py` calls `markdownify.markdownify()`.
**Serves:** Runtime users (local machine, fetch subcommand)

## requests
**Added:** 2026-04-09
**Design plan:** docs/design-plans/2026-04-09-reproducible-demo.md
**Claim:** We use requests for HTTP calls to the Internet Archive CDX API (snapshot verification) and Wayback Machine `id_` endpoint (HTML download).
**Evidence:** `src/llm_discovery/fetch.py` calls `requests.get()` for CDX queries and HTML download.
**Serves:** Runtime users (local machine, fetch subcommand)

## pydantic
**Added:** 2026-04-09
**Design plan:** docs/design-plans/2026-04-09-reproducible-demo.md
**Claim:** We use Pydantic for configuration validation (platform definitions) and LLM output schema definition. Carried forward from FirstRun.
**Evidence:** `src/llm_discovery/platform.py` uses `pydantic.BaseModel`; `src/llm_discovery/unified_processor.py` uses Pydantic models for response validation.
**Serves:** Runtime users

## pyyaml
**Added:** 2026-04-09
**Design plan:** docs/design-plans/2026-04-09-reproducible-demo.md
**Claim:** We use PyYAML to load category prompt definitions from `prompts/*.yaml` and platform config from `config/platforms.yaml`.
**Evidence:** `src/llm_discovery/prep_db.py` and `src/llm_discovery/platform.py` load YAML files.
**Serves:** Runtime users

## langchain-text-splitters
**Added:** 2026-04-09
**Design plan:** docs/design-plans/2026-04-09-reproducible-demo.md
**Claim:** We use `RecursiveCharacterTextSplitter` to chunk markdown documents before LLM processing. Handles splitting at paragraph/sentence boundaries to stay within model context limits.
**Evidence:** `src/llm_discovery/prep_db.py` imports and uses `langchain_text_splitters.RecursiveCharacterTextSplitter`.
**Serves:** Runtime users (prep-db subcommand)

## fabric
**Added:** 2026-04-09
**Design plan:** docs/design-plans/2026-04-09-reproducible-demo.md
**Claim:** We use Fabric for SSH-based remote execution during HPC deployment (rsync, job submission, status checks). Provides a Python API over SSH without requiring users to install remote agents.
**Evidence:** `src/llm_discovery/platform.py` uses `fabric.Connection` for SSH operations.
**Serves:** Runtime users (deploy/status/retrieve subcommands)
