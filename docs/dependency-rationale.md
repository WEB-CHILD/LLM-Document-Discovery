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
**Claim:** We use Typer for the `llm-discovery` CLI with subcommands (fetch, validate, deploy, status, retrieve, run). Provides type-annotated argument parsing and auto-generated help.
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
**Claim:** We use warcio's ArchiveIterator to extract HTML from downloaded WARC records, following the same pattern used in Victor's JDH article. Standard library for WARC processing in Python.
**Evidence:** `src/llm_discovery/fetch.py` uses `warcio.archiveiterator.ArchiveIterator`.
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
**Claim:** We use requests for HTTP calls to the Internet Archive CDX API and for downloading WARC records via range requests.
**Evidence:** `src/llm_discovery/fetch.py` makes HTTP GET requests to web.archive.org.
**Serves:** Runtime users (local machine, fetch subcommand)

## pydantic
**Added:** 2026-04-09
**Design plan:** docs/design-plans/2026-04-09-reproducible-demo.md
**Claim:** We use Pydantic for configuration validation and LLM output schema definition. Carried forward from FirstRun.
**Evidence:** `src/llm_discovery/unified_processor.py` uses Pydantic models for response validation.
**Serves:** Runtime users

## pyyaml
**Added:** 2026-04-09
**Design plan:** docs/design-plans/2026-04-09-reproducible-demo.md
**Claim:** We use PyYAML to load category prompt definitions from `prompts/*.yaml` and platform config from `config/platforms.yaml`.
**Evidence:** `src/llm_discovery/prep_db.py` and `src/llm_discovery/platform.py` load YAML files.
**Serves:** Runtime users
