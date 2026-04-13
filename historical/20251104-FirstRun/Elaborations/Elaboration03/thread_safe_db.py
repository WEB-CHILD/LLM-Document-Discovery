"""
Thread-Safe Database Layer - STUB IMPLEMENTATION

These functions are intentionally broken to make tests fail.
Once tests confirm they can detect the problems, we'll implement proper versions.
"""

import sqlite3
from pathlib import Path
import random


# WRONG: Shared connection (not thread-safe)
_shared_conn = None


def insert_result_with_categories_shared(db_path: Path, result_id: str, content: str, filepath: str):
    """
    INTENTIONALLY BROKEN: Uses shared connection across threads.

    This will cause thread safety violations and should make tests fail.
    """
    global _shared_conn

    if _shared_conn is None:
        _shared_conn = sqlite3.connect(db_path)

    # This is NOT thread-safe - will cause errors
    _shared_conn.execute(
        "INSERT INTO result (result_id, content, filepath) VALUES (?, ?, ?)",
        (result_id, content, filepath)
    )

    for cat_id in range(1, 16):
        _shared_conn.execute(
            "INSERT INTO result_category (result_id, category_id, match) VALUES (?, ?, ?)",
            (result_id, cat_id, random.choice(["yes", "maybe", "no"]))
        )

    _shared_conn.commit()


def insert_result_with_categories_per_thread(db_path: Path, result_id: str, content: str, filepath: str):
    """
    TODO: Implement proper connection-per-thread pattern.

    STUB: Just raises NotImplementedError to make test fail.
    """
    raise NotImplementedError("Connection per thread not implemented yet")


def insert_result_with_forced_error(
    db_path: Path,
    result_id: str,
    content: str,
    filepath: str,
    fail_on_category: int
):
    """
    TODO: Implement atomic transaction with forced failure.

    STUB: Just raises NotImplementedError to make test fail.
    """
    raise NotImplementedError("Forced error transaction not implemented yet")


def insert_result_with_categories_atomic(db_path: Path, result_id: str, content: str, filepath: str):
    """
    TODO: Implement atomic batch insert (all 15 categories or none).

    STUB: Just raises NotImplementedError to make test fail.
    """
    raise NotImplementedError("Atomic batch insert not implemented yet")


def count_results_safe(db_path: Path) -> int:
    """
    TODO: Implement thread-safe read operation.

    STUB: Just raises NotImplementedError to make test fail.
    """
    raise NotImplementedError("Safe read not implemented yet")
