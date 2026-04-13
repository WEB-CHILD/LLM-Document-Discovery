# Elaborations Directory

This directory contains 5 elaboration tests that validate critical assumptions before the full refactor.

## Purpose

Each elaboration is a **falsifiable hypothesis** tested in isolation. We write failing tests first, confirm they can detect problems, then implement solutions.

## Elaboration Structure

Each elaboration folder contains:
- `README.md` - Hypothesis, success criteria, why it matters
- `test_*.py` or `test_*.sh` - Pytest tests or shell scripts (written FIRST)
- `*_implementation.py` - Stub implementations (intentionally broken)
- Results documentation (added after tests run)

## Elaborations

### Elaboration 01: Harmony Format Integration
**Hypothesis**: openai_harmony library works with Ollama and produces parseable structured output

**Files**:
- `test_harmony_integration.py` - 7 pytest tests
- `harmony_integration.py` - Stub implementation

**Status**: 🔴 Not run

---

### Elaboration 02: Multi-Model Compatibility
**Hypothesis**: Same code works for gpt-oss:20b, gpt-oss:120b, and gpt-oss-safeguard:20b

**Files**:
- `test_multi_model_compatibility.py` - 7 pytest tests
- Model adapter (if needed)

**Status**: 🔴 Not run
**Dependencies**: Elaboration 01 must pass

---

### Elaboration 03: SQLite Thread Safety & ACID
**Hypothesis**: SQLite handles concurrent writes from multiple threads with ACID guarantees

**Files**:
- `test_sqlite_thread_safety.py` - 10 pytest tests
- `thread_safe_db.py` - Stub implementation

**Status**: 🔴 Not run

---

### Elaboration 04: Parallel Processing Performance
**Hypothesis**: Parallel category processing is faster than sequential (I/O-bound workload)

**Files**:
- `test_parallel_performance.py` - 8 performance benchmarks
- `parallel_processor.py` - Stub implementation

**Status**: 🔴 Not run
**Dependencies**: Elaboration 01 must pass

---

### Elaboration 05: HPC Ollama Startup
**Hypothesis**: Ollama starts, downloads models, serves requests in < 10 minutes on HPC

**Files**:
- `test_hpc_ollama_startup.sh` - Shell script test
- Timing results documentation

**Status**: 🔴 Not run
**Dependencies**: HPC access required

---

## Running Tests

### Prerequisites
1. Ollama running with gpt-oss:20b model
2. UV environment set up
3. All dependencies installed

### Run Order

**Phase 1: Core Functionality**
```bash
# Test 1: Harmony format integration
uv run pytest Elaborations/Elaboration01/test_harmony_integration.py -v

# Test 2: Multi-model compatibility (requires 120b and safeguard models)
ollama pull gpt-oss:120b
ollama pull gpt-oss-safeguard:20b
uv run pytest Elaborations/Elaboration02/test_multi_model_compatibility.py -v

# Test 3: Database thread safety
uv run pytest Elaborations/Elaboration03/test_sqlite_thread_safety.py -v
```

**Phase 2: Performance**
```bash
# Test 4: Parallel processing performance (LONG RUNNING)
uv run pytest Elaborations/Elaboration04/test_parallel_performance.py -v -s
```

**Phase 3: HPC Integration**
```bash
# Test 5: HPC Ollama startup (run on HPC or simulate locally)
./Elaborations/Elaboration05/test_hpc_ollama_startup.sh
```

### Expected Behavior

**Initially**: All tests should FAIL because implementations are stubs

**After implementation**: Tests should PASS, extracting proven patterns

## Decision Matrix

| Elaborations Passed | Risk Level | Decision |
|-------------------|-----------|----------|
| 5/5 | Very Low | Proceed with full refactor |
| 4/5 | Low | Fix one failure, then proceed |
| 3/5 | Medium | Significant revisions needed |
| 2/5 | High | Reassess architecture |
| 0-1/5 | Critical | Abandon approach, redesign |

## Next Steps

1. **Run all elaborations** - Document pass/fail for each
2. **Extract patterns** - Copy working code from elaborations
3. **Update refactor plan** - Use optimal parameters discovered
4. **Execute refactor** - Implement using validated approaches

## Testing Philosophy

We follow a **test-first, falsification-focused** approach:

1. **Write test that will fail** - Prove we can detect the problem
2. **Confirm test can falsify** - Run it, watch it fail as expected
3. **Implement solution** - Write actual working code
4. **Verify test passes** - Confirm our implementation works
5. **Extract pattern** - Document for use in refactor

This ensures we don't commit to broken architectures.
