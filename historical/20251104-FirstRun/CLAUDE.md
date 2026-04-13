# Claude Interaction Protocols

## Table of Contents

- [For Claude: Documentation Protocol](#for-claude-documentation-protocol)
- [Communication Style](#communication-style)
- [Working Method](#working-method)
- [Project-Specific Context](#project-specific-context)
- [Decision Log](#decision-log)
  - [Core Architecture](#core-architecture-decisions)
  - [Data Management](#data-management-decisions)
  - [Testing & Development](#testing--development-decisions)
  - [HPC Integration](#hpc-integration-decisions)
- [Cross-References](#cross-references)

---

## For Claude: Documentation Protocol

⚠️  **IMPORTANT**: Before implementing features, READ the relevant documentation first:

### When to Read Documentation

1. **On session startup** → Read [docs/README.md](docs/README.md) to understand available documentation
2. **Before implementing vLLM features** → Read [docs/external/vllm_guide.md](docs/external/vllm_guide.md) and [docs/external/vllm_gptoss_deployment.md](docs/external/vllm_gptoss_deployment.md)
3. **Before working with harmony format** → Read [docs/external/harmony_format.md](docs/external/harmony_format.md) and [docs/external/harmony_python_api.md](docs/external/harmony_python_api.md)
4. **When making architectural decisions** → Check [docs/architecture/](docs/architecture/) for existing patterns
5. **When starting elaborations** → Read [docs/elaborations/lessons_learned.md](docs/elaborations/lessons_learned.md) for proven patterns
6. **When asked about decisions** → Cross-reference this file's Decision Log with linked documentation

### Decision Log Location

All architectural decisions are logged in this file under the [Decision Log](#decision-log) section below. When implementing features, consult relevant decisions first:
- **vLLM**: See Decision #14
- **Harmony format**: See Decisions #10, #14
- **Batch processing**: See Decisions #5, #12
- **Database schema**: See Decision #6
- **Testing methodology**: See Decision #13

### Protocol

**Don't wait to be asked.** If you're working on vLLM, harmony, database, elaborations, or HPC topics, READ THE RELEVANT DOCS FIRST before implementing.

---

## Communication Style

### Core Principles
1. **Critical, not complimentary**: You already know your ideas are good. I ask pointed questions to clarify, not to validate.
2. **Specific over general**: One concrete question at a time until the task is fully understood.
3. **Direct challenge when unclear**: If your requirements are ambiguous, I push back immediately rather than proceeding with assumptions.
4. **Australian English**: honour, analyse, etc.

### Question Protocol
- Ask **one question at a time**
- Questions must be **critical and pointed**, identifying gaps or contradictions
- Wait for your response before proceeding
- No performative courtesy or hedging

---

## Working Method

### Task Decomposition
Before starting any multi-step task:
1. Functionally decompose into discrete subtasks
2. Present decomposition for validation
3. Proceed through subtasks sequentially
4. Track progress explicitly

### Decision Logging
All decisions that affect implementation are logged in this file under **Decision Log** section below.

Each entry includes:
- Decision number
- Date
- Context/question
- Decision made
- Rationale (if not obvious)

### When I'm Unclear
If your instructions are ambiguous:
1. Stop immediately
2. Identify the specific ambiguity
3. Ask a clarifying question
4. Do not proceed until resolved

### Evidence Over Inference
When in doubt about requirements:
- Extract concrete examples from your statements
- Ask for ground truth cases
- Prefer explicit specification over interpretation

---

## Project-Specific Context

### Research Domain
Historical analysis of children's web content (1996-2005), multilingual (English, Danish, Korean).

### Methodological Stance
- **No ground truth**: Exploratory research to discover patterns
- **Broad net over precision**: Over-inclusion preferred to missing data
- **Evidence extraction, not interpretation**: LLM extracts textual evidence; humans interpret
- **Temporal agnosticism**: No year-specific judgments across the decade

### Technical Stack
- **Inference**: vLLM with gpt-oss models (see [docs/architecture/vllm_vs_ollama.md](docs/architecture/vllm_vs_ollama.md))
- **Input**: Markdown files in `input/` directory
- **Output**: SQLite database with normalized schema (see Decision #6)
- **Prompts**: POC-prompts/ YAML (git submodule)
- **Processing**: Batch 15 categories per file with vLLM

---

## Decision Log

### Core Architecture Decisions

#### Decision #1 - 2025-10-27
**Context**: Boundary between "yes" and "maybe" classifications

**Decision**: "Maybe" = "Pattern exists but context is unclear (e.g., imperative present but addressee uncertain)". Serves as catch-all for "uncertain, needs human oversight."

**Rationale**: Prioritizes recall over precision. Better to flag uncertain cases for human review than risk false negatives.

---

#### Decision #2 - 2025-10-27
**Context**: Scope of proof of concept - model/input variation

**Decision**: POC uses only gpt-oss:20b with markdown input. No model comparison, no HTML preprocessing.

**Rationale**: Proof of concept goal is to demonstrate capability to work with the data, not to build full comparative infrastructure.

---

#### Decision #3 - 2025-10-27 → **SUPERSEDED by Decision #14**
**Context**: Library choice for LLM interaction - Guidance vs Ollama native

**Decision**: ~~Use Ollama native structured outputs with Pydantic JSON schema~~

**Status**: REPLACED by vLLM with openai_harmony (see Decision #14)

---

#### Decision #4 - 2025-10-27
**Context**: Verification step with Beautiful Soup

**Decision**: Skip Beautiful Soup verification for POC. Markdown input requires simple fuzzy string matching, not HTML parsing.

**Rationale**: Beautiful Soup is for HTML. Input is markdown. For POC, trust LLM extraction or use simple string matching (e.g., difflib, fuzzywuzzy) if verification needed.

---

#### Decision #5 - 2025-10-27 → **UPDATED for vLLM**
**Context**: Prompt structure for inference calls

**Decision**: Batch all 15 categories for one file in a single vLLM call
- Render 15 conversations using openai_harmony
- vLLM.generate() processes batch simultaneously
- Transaction scope: Per file (all 15 categories atomic)

**Original (Ollama)**: ~~15 separate ollama calls per file (one per category)~~

**Rationale**:
- vLLM batch processing far more efficient than sequential calls
- Better GPU utilization
- Simpler code (no ThreadPoolExecutor needed)
- Still maintains ACID guarantee per file

---

---

### Data Management Decisions

#### Decision #6 - 2025-10-27
**Context**: Output format for POC demonstration and SOLR compatibility

**Decision**: Normalized SQLite database with proper relational schema

**Schema**:
```sql
-- Source documents
CREATE TABLE result (
  result_id TEXT PRIMARY KEY,
  content TEXT,
  filepath TEXT
);

-- Category definitions (15 rows, static)
CREATE TABLE category (
  category_id INTEGER PRIMARY KEY,
  category_name TEXT,
  category_description TEXT
);

-- Category results per document
CREATE TABLE result_category (
  result_id TEXT,
  category_id INTEGER,
  match TEXT CHECK(match IN ('yes', 'maybe', 'no')),
  reasoning_trace TEXT,  -- Added in Decision #10
  PRIMARY KEY (result_id, category_id),
  FOREIGN KEY (result_id) REFERENCES result(result_id),
  FOREIGN KEY (category_id) REFERENCES category(category_id)
);

-- Blockquotes as separate rows
CREATE TABLE result_category_blockquote (
  result_id TEXT,
  category_id INTEGER,
  blockquote TEXT,
  FOREIGN KEY (result_id) REFERENCES result(result_id),
  FOREIGN KEY (category_id) REFERENCES category(category_id)
);
```

**Rationale**:
- Proper normalization for a proper database
- Easy to query: "show all 'yes' matches for category X"
- Easy to export to SOLR (flatten with JOIN)
- Clean separation of concerns
- Datasette works perfectly with normalized schema

---

#### Decision #7 - 2025-10-27
**Context**: Pydantic-SQLite integration approach

**Decision**: Direct sqlite3 with Pydantic for output validation only. No ORM.

**Architecture**:
- Pydantic `CategoryResult` → constrains JSON output structure
- Standard `sqlite3` module → INSERT operations
- Datasette → all querying/visualization (no Python query layer needed)

**Rationale**:
- Write-only pipeline: markdown → vLLM → sqlite
- No need for ORM complexity
- Datasette provides instant web UI with faceted search
- Simpler is better for POC

---

### Testing & Development Decisions

#### Decision #8 - 2025-11-14
**Context**: HPC workflow integration approach

**Decision**: Elaboration-driven refactor with falsifiable hypotheses before full implementation.

**Approach**:
1. **Five elaboration tests** (small, throwaway scripts) to prove/disprove critical assumptions
2. **Document results** before proceeding with full refactor
3. **Extract proven patterns** from successful elaborations
4. **Full refactor** implements only validated approaches (no guesswork)

**Elaborations**: See [ELABORATION_PLAN.md](ELABORATION_PLAN.md) and [docs/elaborations/index.md](docs/elaborations/index.md)
- E1: Harmony format integration (vLLM + openai_harmony) - ✅ PASS
- E2: Multi-model compatibility (20b, safeguard:20b) - ✅ PASS
- E3: SQLite thread safety - ⏭️ SKIPPED (vLLM batching eliminates threading need)
- E4: Batch processing performance (vLLM optimal batch size)
- E5: HPC vLLM startup (model caching, GPU loading, startup time)

**Rationale**: Test risky assumptions in isolation before full implementation. Each elaboration targets a specific failure mode.

---

#### Decision #13 - 2025-11-14
**Context**: Testing and development methodology

**Decision**: Test-first, falsification-focused development for all work.

**Protocol**:
1. **Write failing test first** - Before implementing any feature, write pytest tests that will fail
2. **Confirm test can falsify** - Run tests, verify they fail with clear errors
3. **Implement solution** - Only after tests are confirmed to work
4. **Verify test passes** - Re-run tests to confirm correctness
5. **Extract pattern** - Document working patterns for reuse

**Rationale**:
- Proves we can detect problems before committing to solutions
- Prevents building on untested assumptions
- Maintains high code quality through the project
- Aligns with scientific method: falsifiable hypotheses

**Non-negotiable**: This is how we work in this project from now on. No exceptions for "simple" features. If it can't be tested, it can't be trusted.

---

### HPC Integration Decisions

#### Decision #9 - 2025-11-14
**Context**: Model flexibility requirements

**Decision**: Support three models via configuration:
- `openai/gpt-oss-20b` (testing, faster iteration)
- `openai/gpt-oss-120b` (production quality)
- `openai/gpt-oss-safeguard-20b` (policy reasoning alternative)

**Rationale**: All three models use harmony format. Switching requires only model name change, no code path divergence. Allows testing with fast model, running with best model.

---

#### Decision #10 - 2025-11-14
**Context**: Prompt format and reasoning capture

**Decision**: Migrate to harmony response format for all models.

**Implementation**:
- System message: defines reasoning effort (low/medium/high)
- Developer message: contains category-specific instructions
- Response parsing: extract reasoning from `analysis` channel, structured output from `final` channel
- Database: add `reasoning_trace TEXT` column to capture full chain-of-thought

**Rationale**:
- Harmony required for gpt-oss-safeguard
- Provides reasoning transparency for debugging
- Enables variable reasoning effort (cost/quality tradeoff)
- Native format for gpt-oss family

See [docs/external/harmony_format.md](docs/external/harmony_format.md) for specification.

---

#### Decision #11 - 2025-11-14
**Context**: Configuration management

**Decision**: All configuration via `config.py` with environment variable overrides. No hardcoded paths.

**Configuration variables**:
- `PROMPTS_DIR` → POC-prompts/ (synced via Syncthing)
- `INPUT_DIR` → input/markdown_corpus/
- `DB_PATH` → ./corpus.db (local) or /work/20251104-FirstRun/corpus.db (HPC)
- `GPT_MODEL` → openai/gpt-oss-20b | openai/gpt-oss-120b | openai/gpt-oss-safeguard-20b
- `REASONING_EFFORT` → low | medium | high
- `VLLM_BASE_URL` → http://localhost:8000 (configurable for HPC)
- `VLLM_TENSOR_PARALLEL_SIZE` → 2 (recommended for H100)
- `VLLM_MAX_NUM_SEQS` → 15 (batch all categories per file)

**Rationale**: Single codebase works in both environments. HPC environment variables override defaults.

---

#### Decision #12 - 2025-11-14 → **UPDATED for vLLM**
**Context**: Processing strategy for 15 categories per file

**Decision**:
- **Files**: Sequential (one at a time)
- **Categories within file**: vLLM native batching (single `llm.generate(prompts=[15 TokensPrompts])` call)
- **Transaction scope**: Per file (all 15 categories atomic)
- **No threading**: Sequential file processing + vLLM GPU batching within each file

**Original (Ollama)**: ~~ThreadPoolExecutor for parallel category processing~~

**Rationale**:
- vLLM native GPU batching far more efficient than Python threading
- Single GPU call processes all 15 categories simultaneously
- ACID guarantee: all 15 categories committed together or none
- Resumability: file-level granularity (check for 15 completed categories)
- Simpler implementation: no executor management, no multi-connection SQLite
- Estimated 4x speedup over Ollama sequential approach

See [docs/architecture/vllm_vs_ollama.md](docs/architecture/vllm_vs_ollama.md) for performance analysis and Elaboration 04 for batch performance validation.

---

#### Decision #14 - 2025-11-14
**Context**: Inference backend selection

**Decision**: Use vLLM as primary inference backend, replacing Ollama.

**Implementation**:
- Direct Python library usage: `from vllm import LLM, SamplingParams`
- Proper harmony token rendering: `openai_harmony` library
- Batch processing: All 15 categories per file in single `llm.generate()` call
- Configuration: H100-optimized settings (TP=2, FlashAttention3)

**Rationale**:
- **Performance**: 4x speedup via batching (estimated 62 hours vs 249 hours for full corpus)
- **GPU Utilization**: PagedAttention, multi-GPU support, H100 optimizations
- **Harmony Format**: Proper token-level control vs Ollama's text approximation
- **Server-Grade**: Designed for HPC workloads

**Ollama Status**: Retained for local development/testing only (not in elaborations).

See:
- [docs/architecture/vllm_vs_ollama.md](docs/architecture/vllm_vs_ollama.md) - Decision rationale
- [docs/external/vllm_guide.md](docs/external/vllm_guide.md) - General usage
- [docs/external/vllm_gptoss_deployment.md](docs/external/vllm_gptoss_deployment.md) - H100 deployment
- [docs/external/harmony_python_api.md](docs/external/harmony_python_api.md) - Token rendering API

---

#### Decision #15 - 2025-11-14
**Context**: Documentation infrastructure

**Decision**: Build comprehensive docs/ directory to document all external references, architecture decisions, and lessons learned.

**Structure**:
```
docs/
├── README.md                           # Index with cross-referencing protocol
├── external/                           # Third-party documentation
│   ├── harmony_format.md               # OpenAI harmony specification
│   ├── harmony_python_api.md           # openai_harmony Python API
│   ├── vllm_guide.md                   # General vLLM usage
│   └── vllm_gptoss_deployment.md       # H100-specific deployment
├── architecture/                       # Design decisions
│   └── vllm_vs_ollama.md               # Backend selection rationale
└── elaborations/                       # Elaboration tracking
    ├── index.md                        # Status and decision matrix
    └── lessons_learned.md              # Extracted patterns
```

**Rationale**:
- External references documented for future Claude sessions
- Architecture decisions cross-referenced with CLAUDE.md
- Elaboration results tracked systematically
- Prevents re-explaining context in future conversations

**Protocol**: Every external reference pasted → documented in docs/ immediately.

---

## Cross-References

### External Documentation
- [docs/README.md](docs/README.md) - Documentation index
- [docs/external/harmony_format.md](docs/external/harmony_format.md) - Harmony specification
- [docs/external/harmony_python_api.md](docs/external/harmony_python_api.md) - Python API reference
- [docs/external/vllm_guide.md](docs/external/vllm_guide.md) - vLLM usage guide
- [docs/external/vllm_gptoss_deployment.md](docs/external/vllm_gptoss_deployment.md) - H100 deployment

### Architecture Documents
- [docs/architecture/vllm_vs_ollama.md](docs/architecture/vllm_vs_ollama.md) - Backend comparison

### Elaboration Tracking
- [ELABORATION_PLAN.md](ELABORATION_PLAN.md) - Complete elaboration strategy
- [docs/elaborations/index.md](docs/elaborations/index.md) - Status tracking
- [docs/elaborations/lessons_learned.md](docs/elaborations/lessons_learned.md) - Extracted patterns
- [Elaborations/Elaboration01/RESULTS.md](Elaborations/Elaboration01/RESULTS.md) - E01 results

### Implementation Files
- schema.sql - Database schema (Decision #6)
- schemas.py - Pydantic models (Decision #7)
- processor.py - Current POC implementation
- main.py - Entry point

