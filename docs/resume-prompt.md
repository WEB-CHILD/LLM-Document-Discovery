# Resume Prompt for LLM-Document-Discovery

Paste this into a new conversation to resume work.

---

## Project State

Working directory: `/home/brian/people/Helle-Aarhus/LLM-Document-Discovery/`

8-phase implementation plan executed. All phases coded and committed. 63 tests passing. Pre-commit hooks (ruff, shellcheck, ty, complexipy) configured. Ruff passes clean.

## What Was Built

Pipeline for classifying historical web documents (1996-2005 children's web content) using LLMs served via vLLM. Typer CLI (`llm-discovery`) with subcommands: fetch, prep-db, preflight, process, import-results, validate, deploy, status, retrieve, run.

Key modules in `src/llm_discovery/`: fetch.py, prep_db.py, preflight_check.py, unified_processor.py, import_results.py, platform.py, local_runner.py, content_utils.py, cli.py.

## Critical Peer Review Findings (partially fixed)

A critical peer review (`denubis-plan-and-execute:critical-peer-review`) was run. Full output is too large to include — re-run if needed. Summary of what's been fixed and what hasn't:

### Fixed (committed)
- `gpt-oss-20b` → `gpt-oss-120b` in 5 Python source files (fabricated truncated model name)
- `mistralai/gpt-oss-120b` → `openai/gpt-oss-120b` in config/scripts/docs (fabricated vendor prefix)

### Partially fixed (changed but NOT yet committed)
- UCloud GPU count: `ucloud-setup.md` and `platform.py` manual instructions changed from "4 GPUs" to "2 GPUs" (user has 2x H100, TP=2)
- `warcio` removal from pyproject.toml — **STOP, SEE BELOW**
- `openai` SDK removed from dependencies (never imported)
- `datasette` moved to optional `[browse]` extra

### NOT yet fixed
- `dependency-rationale.md` has multiple false evidence claims (warcio, pydantic location, requests description)
- `langchain-text-splitters` missing from dependency-rationale.md
- No `max_model_len` for H200/H100 in machines.yaml (needs comment or value)
- `mistralai/gpt-oss-120b` persists in 3 implementation plan phase files (phase_04.md, phase_06.md)
- Design plan still says "22 categories" (should be 21)
- `google/gemma-4-12b` appears in README and cli.py — this model ID is fabricated. Should be `google/gemma-4-E4B-it` or `google/gemma-4-E2B-it`

## BLOCKING DECISION: fetch.py and warcio

**The current `fetch.py` implementation is wrong.** It uses the Wayback Machine `id_` endpoint to download raw HTML directly. The user's intent was WARC-based: download WARC records, extract HTML with warcio, then convert to markdown.

During the original implementation planning session, I (Claude) suggested the `id_` endpoint as "simpler." This got recorded as a design decision. The user has now corrected this — the pipeline should go: **URL → WARC download → warcio extraction → markdownify → markdown file.** The WARC is the source of truth.

**However:** investigation of the Internet Archive's tools shows that downloading individual WARC records for specific Wayback snapshots requires CDX API → WARC range requests (not the `ia` CLI, which is for archive.org item collections, not Wayback Machine). The `id_` endpoint returns identical HTML content without the WARC layer.

**The user needs to decide:** Is the WARC record needed as an archival artifact (provenance, HTTP headers, citing the exact record), or is the HTML content sufficient? If WARC records are needed, fetch.py needs rewriting to use CDX → WARC range requests → warcio. If HTML is sufficient, the current `id_` endpoint approach works but warcio should be removed from dependencies.

**Do not proceed with fetch.py changes or warcio removal until this is resolved with the user.**

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

1. Resolve the WARC vs id_ endpoint decision with the user
2. Fix or rewrite fetch.py based on that decision
3. Complete remaining peer review fixes (dependency-rationale, design plan corrections, fabricated model IDs)
4. Commit all fixes with full ripple verification (grep every corrected string, zero remaining)
5. Run the testing plan Tier 1 (RTX 4090 + Gemma 4 E4B)
