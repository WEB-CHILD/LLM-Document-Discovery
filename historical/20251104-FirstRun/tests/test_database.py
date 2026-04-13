"""
Tests for database schema and operations.

TDD: Tests for reasoning_trace column and updated insert function.
"""

import pytest
from pathlib import Path


def test_schema_has_reasoning_trace_column(test_database):
    """Verify new schema includes reasoning_trace column"""
    cursor = test_database.execute("PRAGMA table_info(result_category)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}  # {name: type}

    assert "reasoning_trace" in columns
    assert columns["reasoning_trace"] == "TEXT"


def test_insert_category_result_with_reasoning(test_database):
    """Verify reasoning_trace is stored correctly"""
    from db import insert_result, insert_category_result
    from schemas import CategoryResult

    # First create a result
    insert_result(
        test_database,
        result_id="test_file_001",
        content="Test content",
        filepath="test.md"
    )

    # Insert category result with reasoning
    category_result = CategoryResult(
        match="yes",
        blockquotes=["Test blockquote"]
    )

    insert_category_result(
        test_database,
        result_id="test_file_001",
        category_id=1,
        category_result=category_result,
        reasoning_trace="This is test reasoning from the analysis channel."
    )

    # Verify reasoning was stored
    cursor = test_database.execute(
        "SELECT reasoning_trace FROM result_category WHERE result_id=? AND category_id=?",
        ("test_file_001", 1)
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "This is test reasoning from the analysis channel."


def test_insert_category_result_without_reasoning(test_database):
    """Verify reasoning_trace can be empty (backward compatibility)"""
    from db import insert_result, insert_category_result
    from schemas import CategoryResult

    insert_result(
        test_database,
        result_id="test_file_002",
        content="Test content",
        filepath="test2.md"
    )

    category_result = CategoryResult(
        match="no",
        blockquotes=[]
    )

    # Insert without reasoning (empty string)
    insert_category_result(
        test_database,
        result_id="test_file_002",
        category_id=1,
        category_result=category_result,
        reasoning_trace=""
    )

    # Verify empty reasoning was stored
    cursor = test_database.execute(
        "SELECT reasoning_trace FROM result_category WHERE result_id=? AND category_id=?",
        ("test_file_002", 1)
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == ""


def test_insert_category_result_default_reasoning(test_database):
    """Verify reasoning_trace parameter has default value"""
    from db import insert_result, insert_category_result
    from schemas import CategoryResult
    import inspect

    # Check function signature has default
    sig = inspect.signature(insert_category_result)
    assert "reasoning_trace" in sig.parameters
    assert sig.parameters["reasoning_trace"].default == ""

    # Test it works without specifying reasoning_trace
    insert_result(
        test_database,
        result_id="test_file_003",
        content="Test content",
        filepath="test3.md"
    )

    category_result = CategoryResult(
        match="maybe",
        blockquotes=["Maybe quote"]
    )

    # Call without reasoning_trace parameter
    insert_category_result(
        test_database,
        result_id="test_file_003",
        category_id=1,
        category_result=category_result
    )

    # Verify it worked (should store empty string)
    cursor = test_database.execute(
        "SELECT reasoning_trace FROM result_category WHERE result_id=? AND category_id=?",
        ("test_file_003", 1)
    )
    row = cursor.fetchone()
    assert row is not None


def test_blockquotes_still_work(test_database):
    """Verify blockquote table still functions correctly"""
    from db import insert_result, insert_category_result
    from schemas import CategoryResult

    insert_result(
        test_database,
        result_id="test_file_004",
        content="Test content",
        filepath="test4.md"
    )

    category_result = CategoryResult(
        match="yes",
        blockquotes=["Quote 1", "Quote 2", "Quote 3"]
    )

    insert_category_result(
        test_database,
        result_id="test_file_004",
        category_id=2,
        category_result=category_result,
        reasoning_trace="Analysis with multiple quotes"
    )

    # Verify blockquotes were stored
    cursor = test_database.execute(
        "SELECT blockquote FROM result_category_blockquote "
        "WHERE result_id=? AND category_id=? ORDER BY rowid",
        ("test_file_004", 2)
    )
    blockquotes = [row[0] for row in cursor.fetchall()]
    assert blockquotes == ["Quote 1", "Quote 2", "Quote 3"]


def test_reasoning_trace_can_be_long(test_database):
    """Verify reasoning_trace TEXT column can store long reasoning chains"""
    from db import insert_result, insert_category_result
    from schemas import CategoryResult

    insert_result(
        test_database,
        result_id="test_file_005",
        content="Test content",
        filepath="test5.md"
    )

    # Generate a long reasoning trace (simulating verbose chain-of-thought)
    long_reasoning = "Step 1: " + ("Analysis " * 100) + "\n"
    long_reasoning += "Step 2: " + ("Evaluation " * 100) + "\n"
    long_reasoning += "Step 3: " + ("Conclusion " * 100)

    assert len(long_reasoning) > 3000  # Verify it's actually long

    category_result = CategoryResult(
        match="yes",
        blockquotes=["Evidence"]
    )

    insert_category_result(
        test_database,
        result_id="test_file_005",
        category_id=1,
        category_result=category_result,
        reasoning_trace=long_reasoning
    )

    # Verify full reasoning was stored
    cursor = test_database.execute(
        "SELECT reasoning_trace FROM result_category WHERE result_id=? AND category_id=?",
        ("test_file_005", 1)
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == long_reasoning
    assert len(row[0]) > 3000
