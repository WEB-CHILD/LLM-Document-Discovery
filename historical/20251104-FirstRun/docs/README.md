# Documentation Index

This directory contains structured documentation for the 20251104-FirstRun project.

## ⚠️  FOR CLAUDE: WHEN TO READ THIS DOCUMENTATION

**IMPORTANT**: As Claude Code, you should proactively read documentation from this directory in the following situations:

1. **On session startup** - Read `docs/README.md` (this file) to understand what documentation exists
2. **Before implementing vLLM features** - Read `docs/external/vllm_gptoss_deployment.md` and `docs/external/vllm_guide.md`
3. **Before working with harmony format** - Read `docs/external/harmony_format.md` and `docs/external/harmony_python_api.md`
4. **When making architectural decisions** - Check `docs/architecture/` for existing patterns
5. **When starting elaborations** - Read `docs/elaborations/lessons_learned.md` for proven patterns
6. **When asked about decisions** - Cross-reference with CLAUDE.md decision log and linked docs

**Protocol**: Don't wait to be asked. If you're working on vLLM, harmony, database, or HPC topics, READ THE RELEVANT DOCS FIRST.

## Purpose

As the project evolves, we accumulate:
- External references (harmony format, vLLM guides, API docs)
- Design decisions and rationale
- Extracted patterns from elaborations
- Architecture documentation

This `docs/` directory provides a structured knowledge base separate from the decision log in [CLAUDE.md](../CLAUDE.md).

## Directory Structure

### docs/external/
External references and guides that we've collected for cross-reference.

- [harmony_format.md](external/harmony_format.md) - OpenAI Harmony Response Format specification
- [harmony_python_api.md](external/harmony_python_api.md) - openai_harmony Python API reference
- [vllm_guide.md](external/vllm_guide.md) - How to run gpt-oss with vLLM
- [ollama_guide.md](external/ollama_guide.md) - How to run gpt-oss with Ollama (for reference)

### docs/architecture/
Our architectural decisions and implementation patterns.

- [harmony_integration.md](architecture/harmony_integration.md) - How we integrate harmony format
- [vllm_vs_ollama.md](architecture/vllm_vs_ollama.md) - Why we chose vLLM for HPC
- [database_schema.md](architecture/database_schema.md) - SQLite schema design and ACID strategy

### docs/elaborations/
Summaries and lessons learned from elaboration tests.

- [index.md](elaborations/index.md) - Links to all elaboration RESULTS.md files
- [lessons_learned.md](elaborations/lessons_learned.md) - Extracted patterns for main refactor

## Cross-References

Documentation is cross-referenced with:
- **[CLAUDE.md](../CLAUDE.md)** - Decision log with links to relevant docs
- **[ELABORATION_PLAN.md](../ELABORATION_PLAN.md)** - Elaboration strategy and results
- **Elaboration folders** - Individual RESULTS.md files

## Documentation Protocol

### When Adding External References:
1. Create file in `docs/external/[topic].md`
2. Include source URL and date retrieved
3. Add summary at top
4. Update this index
5. Cross-reference from CLAUDE.md

### When Documenting Architecture:
1. Create/update file in `docs/architecture/[topic].md`
2. Reference relevant external docs
3. Explain rationale and tradeoffs
4. Update this index
5. Link from CLAUDE.md decision

### When Completing Elaborations:
1. RESULTS.md stays in elaboration folder
2. Extract patterns to `docs/elaborations/lessons_learned.md`
3. Update architecture docs with validated approaches
4. Reference from CLAUDE.md

## Maintenance

- Keep this README updated with new docs
- Refactor docs when patterns emerge
- Archive superseded docs (don't delete - mark as historical)
- Maintain cross-references to CLAUDE.md
