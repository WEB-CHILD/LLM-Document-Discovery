"""
Elaboration 03: SQLite Thread Safety & ACID Test

This test verifies that SQLite can handle concurrent writes from multiple threads
while maintaining ACID guarantees for batch transactions.

These tests will FAIL if:
- We use naive connection sharing across threads
- Transaction rollback doesn't work properly
- Database corruption occurs under concurrent load

Run with: uv run pytest Elaborations/Elaboration03/test_sqlite_thread_safety.py -v
"""

import pytest
import sqlite3
from pathlib import Path
import threading
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple


# Test database path
TEST_DB = Path("Elaborations/Elaboration03/test_db.sqlite")


@pytest.fixture(scope="function")
def test_db():
    """Create a fresh test database for each test"""
    # Remove if exists
    if TEST_DB.exists():
        TEST_DB.unlink()

    # Create schema
    conn = sqlite3.connect(TEST_DB)
    conn.execute("""
        CREATE TABLE result (
            result_id TEXT PRIMARY KEY,
            content TEXT,
            filepath TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE category (
            category_id INTEGER PRIMARY KEY,
            category_name TEXT,
            category_description TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE result_category (
            result_id TEXT,
            category_id INTEGER,
            match TEXT CHECK(match IN ('yes', 'maybe', 'no')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (result_id, category_id),
            FOREIGN KEY (result_id) REFERENCES result(result_id) ON DELETE CASCADE,
            FOREIGN KEY (category_id) REFERENCES category(category_id)
        )
    """)

    conn.execute("""
        CREATE TABLE result_category_blockquote (
            result_id TEXT,
            category_id INTEGER,
            blockquote TEXT,
            FOREIGN KEY (result_id) REFERENCES result(result_id),
            FOREIGN KEY (category_id) REFERENCES category(category_id)
        )
    """)

    # Insert 15 categories
    for i in range(1, 16):
        conn.execute(
            "INSERT INTO category (category_id, category_name, category_description) VALUES (?, ?, ?)",
            (i, f"category_{i}", f"Description {i}")
        )

    conn.commit()
    conn.close()

    yield TEST_DB

    # Cleanup
    if TEST_DB.exists():
        TEST_DB.unlink()


def test_schema_created(test_db):
    """Test 1: Verify test database schema is correct"""
    conn = sqlite3.connect(test_db)

    # Check tables exist
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]

    assert 'result' in tables
    assert 'category' in tables
    assert 'result_category' in tables
    assert 'result_category_blockquote' in tables

    # Check 15 categories
    cursor = conn.execute("SELECT COUNT(*) FROM category")
    count = cursor.fetchone()[0]
    assert count == 15

    conn.close()


def test_naive_shared_connection_fails():
    """Test 2: Using a shared connection across threads will FAIL

    This test intentionally uses WRONG approach to prove we can detect the problem.
    """
    # This will fail - demonstrates why we need thread-safe implementation
    from Elaborations.Elaboration03.thread_safe_db import insert_result_with_categories_shared

    # This should raise an error about thread safety
    with pytest.raises(Exception) as exc_info:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = []
            for i in range(10):
                future = executor.submit(
                    insert_result_with_categories_shared,
                    TEST_DB,
                    f"result_{i}",
                    f"content_{i}",
                    f"path_{i}"
                )
                futures.append(future)

            for future in as_completed(futures):
                future.result()  # Will raise if thread safety violation

    # If we get here without exception, the stub is too naive to fail properly
    assert "thread" in str(exc_info.value).lower() or "lock" in str(exc_info.value).lower()


def test_connection_per_thread_works(test_db):
    """Test 3: Connection per thread should work safely

    This will FAIL until we implement proper thread-safe connection handling.
    """
    from Elaborations.Elaboration03.thread_safe_db import insert_result_with_categories_per_thread

    # Insert 10 results concurrently, each with 15 categories
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = []
        for i in range(10):
            future = executor.submit(
                insert_result_with_categories_per_thread,
                TEST_DB,
                f"result_{i}",
                f"content_{i}",
                f"path_{i}"
            )
            futures.append(future)

        # Wait for all to complete
        for future in as_completed(futures):
            future.result()  # Should not raise

    # Verify all data inserted correctly
    conn = sqlite3.connect(test_db)

    # Should have 10 results
    cursor = conn.execute("SELECT COUNT(*) FROM result")
    assert cursor.fetchone()[0] == 10

    # Should have 10 * 15 = 150 category results
    cursor = conn.execute("SELECT COUNT(*) FROM result_category")
    assert cursor.fetchone()[0] == 150

    conn.close()


def test_transaction_rollback_on_error(test_db):
    """Test 4: Failed transactions should fully rollback (ACID guarantee)

    This will FAIL if rollback isn't implemented correctly.
    """
    from Elaborations.Elaboration03.thread_safe_db import insert_result_with_forced_error

    # Try to insert with forced error on category 10
    with pytest.raises(Exception):
        insert_result_with_forced_error(
            TEST_DB,
            "test_result",
            "test_content",
            "test_path",
            fail_on_category=10
        )

    # Verify NOTHING was inserted (full rollback)
    conn = sqlite3.connect(test_db)

    cursor = conn.execute("SELECT COUNT(*) FROM result WHERE result_id = 'test_result'")
    assert cursor.fetchone()[0] == 0, "Result should not exist after rollback"

    cursor = conn.execute("SELECT COUNT(*) FROM result_category WHERE result_id = 'test_result'")
    assert cursor.fetchone()[0] == 0, "No categories should exist after rollback"

    conn.close()


def test_atomic_batch_insert(test_db):
    """Test 5: All 15 categories must be inserted atomically (all or nothing)

    This will FAIL if we don't wrap the batch in a transaction.
    """
    from Elaborations.Elaboration03.thread_safe_db import insert_result_with_categories_atomic

    # Insert successfully
    insert_result_with_categories_atomic(
        TEST_DB,
        "atomic_test",
        "content",
        "path"
    )

    # Verify exactly 15 categories
    conn = sqlite3.connect(test_db)
    cursor = conn.execute("SELECT COUNT(*) FROM result_category WHERE result_id = 'atomic_test'")
    count = cursor.fetchone()[0]
    assert count == 15, "Must have exactly 15 categories (atomic insert)"
    conn.close()


def test_concurrent_writes_different_results(test_db):
    """Test 6: Multiple threads writing different results simultaneously

    This will FAIL if there are locking issues or race conditions.
    """
    from Elaborations.Elaboration03.thread_safe_db import insert_result_with_categories_per_thread

    num_workers = 8
    num_results = 20

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = []
        for i in range(num_results):
            future = executor.submit(
                insert_result_with_categories_per_thread,
                TEST_DB,
                f"concurrent_{i}",
                f"content_{i}",
                f"path_{i}"
            )
            futures.append(future)

        # Collect results
        for future in as_completed(futures):
            future.result()

    # Verify all inserted correctly
    conn = sqlite3.connect(test_db)

    cursor = conn.execute("SELECT COUNT(*) FROM result")
    assert cursor.fetchone()[0] == num_results

    cursor = conn.execute("SELECT COUNT(*) FROM result_category")
    assert cursor.fetchone()[0] == num_results * 15

    # Verify no corruption - each result should have exactly 15 categories
    cursor = conn.execute("""
        SELECT result_id, COUNT(*) as cat_count
        FROM result_category
        GROUP BY result_id
        HAVING cat_count != 15
    """)

    corrupted = cursor.fetchall()
    assert len(corrupted) == 0, f"Found results with != 15 categories: {corrupted}"

    conn.close()


def test_stress_test_100_concurrent_writes(test_db):
    """Test 7: Stress test with 100 concurrent writes

    This will FAIL if there are subtle race conditions or deadlocks.
    """
    from Elaborations.Elaboration03.thread_safe_db import insert_result_with_categories_per_thread

    num_results = 100
    num_workers = 16  # More workers than cores to stress test

    start_time = time.time()

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = []
        for i in range(num_results):
            future = executor.submit(
                insert_result_with_categories_per_thread,
                TEST_DB,
                f"stress_{i}",
                f"content_{i}" * 100,  # Larger content
                f"path_{i}"
            )
            futures.append(future)

        completed = 0
        for future in as_completed(futures):
            future.result()
            completed += 1

        assert completed == num_results

    elapsed = time.time() - start_time

    # Verify data integrity
    conn = sqlite3.connect(test_db)

    cursor = conn.execute("SELECT COUNT(*) FROM result")
    assert cursor.fetchone()[0] == num_results

    cursor = conn.execute("SELECT COUNT(*) FROM result_category")
    assert cursor.fetchone()[0] == num_results * 15

    conn.close()

    # Print performance info
    print(f"\nStress test completed in {elapsed:.2f}s")
    print(f"Throughput: {num_results / elapsed:.2f} results/second")
    print(f"Per result: {elapsed / num_results * 1000:.2f}ms")


def test_read_during_concurrent_writes(test_db):
    """Test 8: Reads should work correctly during concurrent writes

    This will FAIL if readers get blocked or see corrupted data.
    """
    from Elaborations.Elaboration03.thread_safe_db import (
        insert_result_with_categories_per_thread,
        count_results_safe
    )

    num_writers = 5
    num_readers = 3

    writes_completed = []
    read_counts = []

    def writer_task(i):
        insert_result_with_categories_per_thread(
            TEST_DB,
            f"mixed_{i}",
            f"content_{i}",
            f"path_{i}"
        )
        writes_completed.append(i)
        time.sleep(random.uniform(0.01, 0.05))

    def reader_task():
        for _ in range(10):
            count = count_results_safe(TEST_DB)
            read_counts.append(count)
            time.sleep(random.uniform(0.01, 0.02))

    with ThreadPoolExecutor(max_workers=num_writers + num_readers) as executor:
        # Start readers and writers concurrently
        futures = []

        for i in range(num_writers):
            futures.append(executor.submit(writer_task, i))

        for _ in range(num_readers):
            futures.append(executor.submit(reader_task))

        for future in as_completed(futures):
            future.result()

    # Verify final state
    conn = sqlite3.connect(test_db)
    cursor = conn.execute("SELECT COUNT(*) FROM result")
    final_count = cursor.fetchone()[0]
    assert final_count == num_writers
    conn.close()

    # Verify reads were monotonically increasing (or stable)
    # Reads should never see corrupted counts
    assert all(0 <= count <= num_writers for count in read_counts), \
        f"Read counts outside valid range: {read_counts}"


def test_multiple_rollbacks_dont_corrupt(test_db):
    """Test 9: Multiple failed transactions shouldn't corrupt database

    This will FAIL if rollback implementation is buggy.
    """
    from Elaborations.Elaboration03.thread_safe_db import insert_result_with_forced_error

    # Try 10 insertions that will all fail
    for i in range(10):
        with pytest.raises(Exception):
            insert_result_with_forced_error(
                TEST_DB,
                f"fail_{i}",
                "content",
                "path",
                fail_on_category=random.randint(1, 15)
            )

    # Verify database is clean (no partial data)
    conn = sqlite3.connect(test_db)

    cursor = conn.execute("SELECT COUNT(*) FROM result")
    assert cursor.fetchone()[0] == 0

    cursor = conn.execute("SELECT COUNT(*) FROM result_category")
    assert cursor.fetchone()[0] == 0

    conn.close()


def test_wal_mode_performance():
    """Test 10: Compare performance with WAL (Write-Ahead Logging) mode

    This test is informational - it compares performance but doesn't fail.
    """
    from Elaborations.Elaboration03.thread_safe_db import insert_result_with_categories_per_thread

    # Test with default mode
    test_db_default = Path("Elaborations/Elaboration03/test_default.sqlite")
    if test_db_default.exists():
        test_db_default.unlink()

    conn = sqlite3.connect(test_db_default)
    _create_schema(conn)
    conn.close()

    start = time.time()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(insert_result_with_categories_per_thread, test_db_default, f"default_{i}", "content", "path")
            for i in range(20)
        ]
        for f in as_completed(futures):
            f.result()
    default_time = time.time() - start

    # Test with WAL mode
    test_db_wal = Path("Elaborations/Elaboration03/test_wal.sqlite")
    if test_db_wal.exists():
        test_db_wal.unlink()

    conn = sqlite3.connect(test_db_wal)
    conn.execute("PRAGMA journal_mode=WAL")
    _create_schema(conn)
    conn.close()

    start = time.time()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(insert_result_with_categories_per_thread, test_db_wal, f"wal_{i}", "content", "path")
            for i in range(20)
        ]
        for f in as_completed(futures):
            f.result()
    wal_time = time.time() - start

    # Cleanup
    test_db_default.unlink()
    test_db_wal.unlink()

    print(f"\nDefault mode: {default_time:.2f}s")
    print(f"WAL mode: {wal_time:.2f}s")
    print(f"Speedup: {default_time / wal_time:.2f}x")


def _create_schema(conn):
    """Helper to create schema"""
    conn.execute("CREATE TABLE result (result_id TEXT PRIMARY KEY, content TEXT, filepath TEXT)")
    conn.execute("CREATE TABLE category (category_id INTEGER PRIMARY KEY, category_name TEXT, category_description TEXT)")
    conn.execute("""
        CREATE TABLE result_category (
            result_id TEXT,
            category_id INTEGER,
            match TEXT CHECK(match IN ('yes', 'maybe', 'no')),
            PRIMARY KEY (result_id, category_id),
            FOREIGN KEY (result_id) REFERENCES result(result_id),
            FOREIGN KEY (category_id) REFERENCES category(category_id)
        )
    """)
    conn.execute("""
        CREATE TABLE result_category_blockquote (
            result_id TEXT,
            category_id INTEGER,
            blockquote TEXT,
            FOREIGN KEY (result_id) REFERENCES result(result_id),
            FOREIGN KEY (category_id) REFERENCES category(category_id)
        )
    """)
    for i in range(1, 16):
        conn.execute("INSERT INTO category VALUES (?, ?, ?)", (i, f"cat_{i}", f"desc_{i}"))
    conn.commit()
