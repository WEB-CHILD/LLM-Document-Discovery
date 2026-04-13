# Elaboration-Driven Refactor Plan

## Overview

This document outlines the elaboration tests we'll run before refactoring the POC code for HPC deployment. Each elaboration tests a specific assumption that could break the full implementation.

## Elaborations (Prove Assumptions Before Full Implementation)

### Elaboration 1: Harmony Format Integration Test ✅ PASS

**Hypothesis to falsify**: "openai_harmony library works with vLLM and produces parseable structured output"

**Test**:
- Single-file pytest suite using openai_harmony + vLLM
- Load category prompts from POC-prompts
- Construct harmony conversation via token rendering
- Send to vLLM LLM instance (openai/gpt-oss-20b)
- Parse response channels (analysis + final)
- Validate JSON structure against CategoryResult schema

**Success criteria**: ✅ All met
- vLLM accepts harmony token sequences
- Response contains both analysis and final channels
- Final channel contains valid JSON matching schema
- Reasoning trace extracted from analysis channel

**Status**: ✅ PASS (2025-11-14)
**Results**: [Elaborations/Elaboration01/RESULTS.md](Elaborations/Elaboration01/RESULTS.md)
**Pattern**: Use `construct_harmony_conversation()` + `parse_harmony_response()` from harmony_integration.py

---

### Elaboration 2: Multi-Model Compatibility Test ✅ PASS

**Hypothesis to falsify**: "Same harmony token rendering works identically across openai/gpt-oss-20b and openai/gpt-oss-safeguard-20b"

**Test**:
- Same input + same category prompt
- Run through gpt-oss-20b and gpt-oss-safeguard-20b via vLLM
- Compare output structure and parseability
- Verify safeguard model doesn't require special handling
- Note: 120b testing deferred to HPC (will run E01 suite with MODEL=120b)

**Success criteria**: ✅ All met
- Both models return valid harmony format
- Both produce parseable JSON in final channel
- Reasoning traces are comparable in structure
- No model-specific code paths needed

**Status**: ✅ PASS (2025-11-14)
**Results**: [Elaborations/Elaboration02/RESULTS.md](Elaborations/Elaboration02/RESULTS.md)
**Pattern**: Single unified code path works for all gpt-oss models - switch via model name string only

---

### Elaboration 3: SQLite Thread Safety & ACID Test ⏭️ SKIPPED

**Original Hypothesis**: "SQLite can handle concurrent writes from multiple threads with proper locking and maintain ACID guarantees"

**Status**: ⏭️ SKIPPED (2025-11-14)
**Reason**: After E02 demonstrated vLLM native batching, architectural decision made to use single `llm.generate(prompts=[15 TokensPrompts])` call per file. No threading needed for category processing.

**New Architecture**:
- Sequential file processing (one file at a time)
- vLLM native GPU batching (all 15 categories per file in single call)
- Single SQLite connection (no multi-threading concerns)
- Per-file atomic commits (all 15 categories or none)

**See**: [Elaborations/Elaboration03/README.md](Elaborations/Elaboration03/README.md) for full explanation

---

### Elaboration 4: Batch Processing Performance Test ⚠️ PARTIAL PASS

**Hypothesis to falsify**: "Processing 15 categories in a single vLLM batch is faster than sequential processing, with vLLM's native GPU batching providing optimal throughput"

**Test**:
- Use 5 real markdown files
- Measure: sequential processing (batch_size=1, one category at a time)
- Measure: batch processing with varying sizes (5, 10, 15, 20 prompts)
- Compare throughput, latency, and GPU utilisation
- Identify optimal batch size for production

**Success criteria**: ⚠️ 4/5 met
- Batch processing shows significant speedup (>3x) over sequential → ⚠️ 2.35x (PARTIAL, 2-3x range)
- vLLM handles 15-prompt batches without errors → ✅ All tests passed
- GPU utilisation high during batch processing → ⚠️ Unable to measure (tracking failed)
- Memory requirements acceptable → ✅ No OOM, model loaded successfully
- Clear optimal batch size identified → ✅ batch_size=15 optimal

**Status**: ⚠️ PARTIAL PASS (2025-11-14)
**Results**: [Elaborations/Elaboration04/RESULTS.md](Elaborations/Elaboration04/RESULTS.md)
**Pattern**: Use vLLM native batching with `batch_size=15`, provides 2.35x speedup over sequential
**Key Finding**: Modest but significant speedup validates approach, optimal batch size matches use case perfectly

---

### Elaboration 5: HPC vLLM Startup & Model Loading

**Hypothesis to falsify**: "vLLM can load gpt-oss models on HPC H100 and serve requests within acceptable startup time"

**Test**:
- Minimal HPC job script (not full setup.sh integration)
- Load vLLM LLM instance with gpt-oss-20b (or 120b if memory allows)
- Configure for H100: tensor_parallel_size=2, trust_remote_code=True
- Send test harmony request
- Verify response parsing works
- Measure: model download time, loading time, first token latency

**Success criteria**:
- vLLM loads successfully on HPC H100
- Model downloads to correct HuggingFace cache location
- Model loads into GPU memory with proper parallelisation
- First harmony request completes successfully
- Total startup time acceptable for hour-long runs

**Status**: 🔄 TODO
**Files**: `Elaborations/Elaboration05/` (to be created)

---

## TODO: Full Refactor (After Elaborations Pass)

**Proven by elaborations**:
1. ✅ Harmony format works with vLLM (E01 - PASS)
2. ✅ Multi-model support requires no special handling (E02 - PASS)
3. ⏭️ SQLite threading not needed (E03 - SKIPPED, vLLM batching approach)
4. 🔄 vLLM batch processing provides optimal throughput (E04 - TODO)
5. 🔄 HPC vLLM startup reliable (E05 - TODO)

**Refactor tasks** (executed only after elaborations validate approach):

### Core Architecture
- [ ] Create `config.py` with ALL configuration (no hardcoded paths):
  - `PROMPTS_DIR` (points to POC-prompts/)
  - `INPUT_DIR` (input/markdown_corpus/)
  - `DB_PATH` (./corpus.db or /work/20251104-FirstRun/corpus.db)
  - `GPT_MODEL` (openai/gpt-oss-20b | openai/gpt-oss-120b | openai/gpt-oss-safeguard-20b)
  - `REASONING_EFFORT` (Low | Medium | High)
  - `VLLM_GPU_MEMORY_UTILIZATION` (0.85 default)
  - `VLLM_TENSOR_PARALLEL_SIZE` (2 for H100, 1 for local)
  - `VLLM_MAX_NUM_SEQS` (15 - batch all categories per file)

### Schema & Data Layer
- [ ] Add `reasoning_trace TEXT` to schema.sql
- [ ] Update `CategoryResult` Pydantic model (add reasoning_trace field)
- [ ] Modify `db.py`:
  - Single connection (no threading concerns)
  - Insert reasoning_trace from harmony analysis channel
  - ACID transaction per file (all 15 categories atomic)
  - Use `config.DB_PATH` everywhere
  - Resumability: Check for existing 15 completed categories before processing file

### Processing Layer
- [ ] Create `harmony_processor.py` (using E01 validated pattern):
  - Import `construct_harmony_conversation()` and `parse_harmony_response()` from E01
  - Batch construction: Build 15 TokensPrompt instances for one file
  - Single vLLM call: `llm.generate(prompts=[15 TokensPrompts])`
  - Parse all 15 responses
  - Extract reasoning traces + structured results
  - Use `config.GPT_MODEL` and `config.REASONING_EFFORT`

- [ ] Refactor `processor.py`:
  - Replace Ollama with vLLM LLM instance
  - Load prompts from `config.PROMPTS_DIR`
  - Use harmony_processor for batch processing
  - Handle multi-model responses uniformly (validated by E02)

- [ ] Refactor `main.py`:
  - Sequential file processing (no threading)
  - Per-file: batch all 15 categories via vLLM
  - Per-file: atomic commit (all 15 or none)
  - Signal handlers for graceful shutdown
  - Progress logging (terminal detection: Rich vs plain)
  - Use `config.INPUT_DIR` and `config.DB_PATH`

### HPC Integration
- [ ] Create HPC job script (using E05 validated pattern):
  - Clone 20251104-FirstRun repo
  - Export HPC environment variables (DB_PATH, GPT_MODEL, TENSOR_PARALLEL_SIZE, etc.)
  - Install vLLM and dependencies
  - vLLM loads model directly (no server mode needed for Python API)
  - Run main.py
  - Auto-shutdown after completion

- [ ] Create `.env.example` with local vs HPC configs
- [ ] Document Syncthing sync pattern for POC-prompts (already running, just document)
- [ ] HuggingFace cache configuration for /work/ directory

### Resilience
- [ ] Error handling: retry logic with exponential backoff
- [ ] Logging: file-based for HPC, Rich for local (terminal detection)
- [ ] Validation: script to verify database integrity post-run

---

## Execution Order

### Phase 1: Run Elaborations ✅ 3/5 complete, 1 skipped
1. ✅ E01: Harmony format integration (local) - PASS
2. ✅ E02: Multi-model compatibility (local, 20b + safeguard-20b) - PASS
3. ⏭️ E03: SQLite thread safety (local) - SKIPPED (vLLM batching eliminates need)
4. ⚠️ E04: Batch processing performance (local, real files) - PARTIAL PASS (2.35x speedup)
5. 🔄 E05: HPC vLLM startup (HPC, minimal job) - TODO

### Phase 2: Review Results & Adjust
- ✅ E01 & E02 passed - patterns extracted
- ⚠️ E04 partial pass - 2.35x speedup validates approach, optimal batch_size=15 confirmed
- E05 remaining - HPC vLLM startup validation on H100
- Once E05 passes, ready for full refactor

### Phase 3: Execute Full Refactor
- Apply TODO checklist using validated patterns
- No guesswork - implementation matches elaboration proofs

### Phase 4: Integration Test
- Local: Process 50 files with new architecture
- HPC: 1-hour test run (measure throughput, estimate full corpus time)

---

## What This Proves

Each elaboration targets a specific risk:
1. ✅ **Harmony risk**: Library incompatibility with vLLM → PROVEN compatible (E01)
2. ✅ **Model risk**: Need for model-specific code paths → PROVEN unified (E02)
3. ⏭️ **Concurrency risk**: Database corruption or deadlocks → NOT APPLICABLE (vLLM batching, no threading)
4. ⚠️ **Performance risk**: Sequential processing too slow → VALIDATED 2.35x speedup with vLLM batching (E04)
5. 🔄 **HPC risk**: vLLM startup failures or cache issues → TO PROVE on H100 (E05)

By falsifying these risks first, the full refactor becomes low-risk implementation of proven patterns.

---

## What We'll Do With The Results

### For Each Elaboration:

1. **Run the test** - Execute the throwaway script
2. **Document outcome** - Record pass/fail and key findings
3. **Extract pattern** - If successful, extract the working code pattern
4. **Identify blockers** - If failed, identify what needs to change

### Results Documentation:

Create `ELABORATION_RESULTS.md` with the following structure for each test:

```markdown
## Elaboration N: [Name]

**Status**: ✅ PASS / ❌ FAIL / ⚠️  PARTIAL

**Key Findings**:
- [Finding 1]
- [Finding 2]

**Extracted Pattern** (if PASS):
```python
# Working code pattern to use in refactor
```

**Blocker** (if FAIL):
- [What failed]
- [Why it failed]
- [Alternative approach to try]

**Performance Data** (if applicable):
- [Timing metrics]
- [Resource usage]
- [Optimal parameters discovered]
```

### Decision Points Based On Results:

#### If ALL elaborations pass:
→ Proceed with full refactor using validated patterns
→ Use optimal parameters discovered (e.g., worker count from E4)
→ High confidence in implementation approach

#### If 1-2 elaborations fail:
→ Revise approach for failed elaboration only
→ Re-test failed elaboration with alternative approach
→ Proceed with refactor once all pass

#### If 3+ elaborations fail:
→ Fundamental assumption is wrong
→ Reassess architecture (e.g., maybe abandon harmony format, maybe abandon parallel processing)
→ Document new approach and create new elaboration plan

### Integration Into Refactor:

Each successful elaboration produces a **reference implementation** that will be copied/adapted during the full refactor:

- ✅ **E01 success** → `harmony_processor.py` uses E01's `construct_harmony_conversation()` and `parse_harmony_response()` patterns
- ✅ **E02 success** → Confirms no model-specific code needed in `processor.py` - single unified path for all gpt-oss models
- ⏭️ **E03 skipped** → `db.py` uses simple single-connection pattern, per-file atomic transactions
- 🔄 **E04 success** → `main.py` uses vLLM batch pattern with optimal batch size from E04 results
- 🔄 **E05 success** → HPC job script uses E05's vLLM startup sequence and HuggingFace cache configuration

### Confidence Levels:

| Elaborations Passed | Refactor Risk | Decision |
|-------------------|--------------|----------|
| 5/5 | Very Low | Proceed with refactor immediately |
| 4/5 | Low | Fix one failure, then proceed |
| 3/5 | Medium | Fix failures, consider architecture changes |
| 2/5 | High | Reassess fundamental approach |
| 0-1/5 | Critical | Abandon current architecture, redesign |

### Timeline:

- **Elaborations**: 1-2 days (quick tests, fast feedback)
- **Results review**: 1 hour (analyze, document patterns)
- **Refactor decision**: Immediate (based on confidence level)
- **Full refactor**: 2-3 days (using proven patterns)

This approach ensures we **invest minimal time** in tests before committing to a potentially broken architecture.
