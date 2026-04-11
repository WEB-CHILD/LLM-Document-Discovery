# Resume Prompt for LLM-Document-Discovery

Paste this into a new conversation to resume work.

---

## Project State

Working directory: `/home/brian/people/Helle-Aarhus/LLM-Document-Discovery/`

8-phase implementation plan executed. All phases coded and committed. 63 tests passing. Pre-commit hooks (ruff, shellcheck, ty, complexipy) configured. Ruff passes clean.

## What Was Built

Pipeline for classifying historical web documents (1996-2005 children's web content) using LLMs served via vLLM. Typer CLI (`llm-discovery`) with subcommands: fetch, prep-db, preflight, process, import-results, validate, deploy, status, retrieve, run.

Key modules in `src/llm_discovery/`: fetch.py, prep_db.py, preflight_check.py, unified_processor.py, import_results.py, platform.py, local_runner.py, content_utils.py, cli.py.

## Critical Peer Review Findings

A critical peer review (`denubis-plan-and-execute:critical-peer-review`) was run. All findings have been addressed.

### Fixed (committed in earlier session)
- `gpt-oss-20b` → `gpt-oss-120b` in 5 Python source files (fabricated truncated model name)
- `mistralai/gpt-oss-120b` → `openai/gpt-oss-120b` in config/scripts/docs (fabricated vendor prefix)

### Fixed (changed, not yet committed — 2026-04-11)
- UCloud GPU count: `ucloud-setup.md` and `platform.py` changed from "4 GPUs" to "2 GPUs" (user has 2x H100, TP=2)
- `openai` SDK removed from dependencies (never imported)
- `datasette` moved to optional `[browse]` extra
- `dependency-rationale.md` corrected: warcio evidence, pydantic location, requests description all fixed
- `langchain-text-splitters` and `fabric` entries added to dependency-rationale.md
- `max_model_len: null` added with comments for H200/H100 in machines.yaml
- `mistralai/gpt-oss-120b` → `openai/gpt-oss-120b` in phase_04.md and phase_06.md
- Design plan corrected: 22 categories → 21, 110 rows → 105
- `google/gemma-4-12b` → `google/gemma-4-E4B-it` in README, cli.py, and phase_08.md

## fetch.py and WARC decision (RESOLVED)

**Decision (2026-04-11):** Keep fetch.py as-is (Wayback `id_` endpoint → HTML → markdown). Keep warcio in dependencies. A `fetch_warc.py` stub has been created for the future WARC-based fetch path (CDX → WARC range request → warcio extraction → markdown). The WARC workflow will be demonstrated in the paper narrative; this pipeline uses the simpler path for now.

Reference implementation for WARC fetch: https://github.com/helgeho/ArchiveSpark/blob/master/notebooks/Downloading_WARC_from_Wayback.ipynb

## GPU Configuration (confirmed by user)

| Tier | Hardware | Queue | Model | TP |
|------|----------|-------|-------|----|
| Local | RTX 4090 (1x24GB) | n/a | `google/gemma-4-E4B-it` | 1 |
| Gadi | V100 (4x32GB) | gpuvolta | `google/gemma-4-31B-it` | 4 |
| Gadi | H200 (4x141GB) | gpuhopper | `openai/gpt-oss-120b` | 4 |
| UCloud | H100 (2x80GB) | n/a | `openai/gpt-oss-120b` | 2 |

- gpuhopper = H200 (confirmed from user's melica project)
- vLLM nightly required for Gemma 4: `uv pip install -U vllm --pre --extra-index-url https://wheels.vllm.ai/nightly/cu129`
- Gemma 4 reference: `/media/brian/storage/people/Adela/melica/.worktrees/doc-routing-arch-1/docs/reference/vllm-gemma4-recipe.md`
- Structured output not enforced for Gemma 4 on vLLM nightly — responses may wrap JSON in markdown fences

## Key References

- Design plan: `docs/design-plans/2026-04-09-reproducible-demo.md`
- Implementation plan: `docs/implementation-plans/2026-04-09-reproducible-demo/phase_01.md` through `phase_08.md`
- Test requirements: `docs/implementation-plans/2026-04-09-reproducible-demo/test-requirements.md`
- Testing plan: `docs/testing-plan-local-4090.md`
- FirstRun source: `/home/brian/people/Helle-Aarhus/20251104-FirstRun/`
- Melica vLLM spike: `/media/brian/storage/people/Adela/melica/.worktrees/doc-routing-arch-1/docs/dead-ends/2026-04-10-vllm-gemma4-triage-spike.md`

## Immediate Next Steps

1. Commit all pending fixes with full ripple verification (grep every corrected string, zero remaining)
2. Run the testing plan Tier 1 (RTX 4090 + Gemma 4 E4B)
3. Implement fetch_warc.py when ready to demonstrate WARC workflow for the paper
