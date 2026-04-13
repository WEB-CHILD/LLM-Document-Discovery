# Elaboration 03: SQLite Thread Safety & ACID Guarantees

## Status: ⏭️ SKIPPED

**Reason**: After Elaboration 02 demonstrated vLLM native batching capability, architectural decision made to use single `llm.generate(prompts=[15 TokensPrompts])` call per file instead of threading. This eliminates the need for concurrent SQLite writes from multiple threads.

**Architecture Decision**: Sequential file processing with vLLM batching all 15 categories per file in a single GPU call. No ThreadPoolExecutor, no multi-connection SQLite needed.

**See**: Elaboration 04 for vLLM batch performance testing.

---

## Original Hypothesis (Now Superseded)

**"SQLite can handle concurrent writes from multiple threads with proper locking and maintain ACID guarantees for batch transactions."**

## What We're Testing

1. Can multiple threads write to the same SQLite database simultaneously without corruption?
2. Do transactions properly rollback when errors occur mid-transaction?
3. Can we commit 15 category results atomically (all or nothing)?
4. Does SQLite's file locking prevent race conditions?
5. What connection handling pattern ensures thread safety (connection per thread, connection pool, serialized writes)?
6. Is performance acceptable with concurrent access?

## Why This Matters

The refactor assumes we can:
- Process 15 categories in parallel (ThreadPoolExecutor)
- Write all 15 results atomically per file
- Recover from errors without partial writes
- Avoid database corruption or deadlocks

If SQLite can't handle concurrent access, we need to:
- Serialize all database writes (slower)
- Use a different database (more complex)
- Change our parallelization strategy

## Success Criteria

### ✅ PASS
- Multiple threads can write simultaneously without errors
- Failed transactions fully rollback (no partial data)
- All 15 categories committed atomically
- No database corruption under stress
- Performance degradation < 50% vs sequential writes

### ⚠️  PARTIAL
- Concurrent writes work but require explicit locking/queueing
- Performance degradation 50-80%
- Fallback: Serialize writes at application level

### ❌ FAIL
- Database corruption occurs
- OR: Deadlocks are frequent
- OR: Transaction rollbacks don't work correctly
- OR: Performance degradation > 80%

## Test Approach

### Phase 1: Write Failing Tests (pytest)
Create `test_sqlite_thread_safety.py` with tests that:
1. Spawn multiple threads attempting concurrent writes
2. Deliberately cause mid-transaction failures
3. Verify rollback behavior
4. Stress test with many concurrent operations
5. **These tests will FAIL if our DB connection handling is naive**

### Phase 2: Confirm Test Can Falsify
Run pytest and verify it fails with clear errors about:
- Database locks
- Corruption
- Incomplete rollbacks

### Phase 3: Implement Thread-Safe DB Layer
Create proper connection handling in `thread_safe_db.py`:
- Connection per thread pattern
- OR: Connection pool with proper locking
- OR: Write queue with single writer thread

### Phase 4: Verify Tests Pass
Re-run pytest to confirm thread safety

## Files

- `README.md` - This file
- `test_sqlite_thread_safety.py` - Pytest tests (write first, expect failures)
- `thread_safe_db.py` - Thread-safe database layer (implement after tests fail)
- `test_db.sqlite` - Temporary test database (created/destroyed by tests)

## Expected Outcome

Either:
1. **PASS**: SQLite handles concurrent writes fine, extract pattern for refactor
2. **PARTIAL**: Need explicit serialization, implement write queue
3. **FAIL**: SQLite unsuitable for concurrent access - reconsider parallelization strategy

## Key Testing Scenarios

### Scenario 1: Concurrent Inserts
- 10 threads simultaneously inserting results
- No overlapping result_ids (different files)
- Should work without locking

### Scenario 2: Concurrent Updates
- 10 threads updating same tables
- Possible conflicts
- Tests how SQLite handles write locks

### Scenario 3: Transaction Rollback
- Start transaction
- Insert 14 of 15 categories
- Force error on 15th
- Verify database has NONE of the 15

### Scenario 4: Stress Test
- 100 threads
- Each inserts 15 categories atomically
- Verify all data correct at end

### Scenario 5: Read During Write
- Writer thread doing batch insert
- Reader threads querying database
- Verify reads don't block or corrupt

## SQLite Connection Modes to Test

1. **Shared connection** (will fail - not thread-safe)
2. **Connection per thread** (should work)
3. **Connection pool** (should work with proper locking)
4. **WAL mode** (Write-Ahead Logging for better concurrency)

## Dependencies

- None (standalone test)
- Creates temporary test database
- Cleans up after tests
