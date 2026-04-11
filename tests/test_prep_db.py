"""Tests for prep_db module."""

import sqlite3
from pathlib import Path

from llm_discovery.prep_db import (
    create_db,
    get_database_status,
    sync_categories,
    sync_documents,
)


class TestCreateDb:
    def test_creates_all_tables(self, tmp_path):
        schema_path = Path(__file__).parent.parent / "schema.sql"
        db_path = tmp_path / "test.db"
        created = create_db(db_path, schema_path)
        assert created is True
        assert db_path.exists()

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "result" in tables
        assert "category" in tables
        assert "result_category" in tables
        assert "result_category_blockquote" in tables
        assert "excluded_file" in tables
        assert "run_stats" in tables

    def test_returns_false_if_exists(self, tmp_db):
        schema_path = Path(__file__).parent.parent / "schema.sql"
        created = create_db(tmp_db, schema_path)
        assert created is False


class TestSyncCategories:
    def test_populates_category_table(self, tmp_db, sample_prompts_dir):
        count = sync_categories(tmp_db, sample_prompts_dir)
        assert count == 2

        conn = sqlite3.connect(tmp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM category")
        assert cursor.fetchone()[0] == 2
        conn.close()

    def test_no_duplicates_on_resync(self, tmp_db, sample_prompts_dir):
        sync_categories(tmp_db, sample_prompts_dir)
        sync_categories(tmp_db, sample_prompts_dir)

        conn = sqlite3.connect(tmp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM category")
        assert cursor.fetchone()[0] == 2
        conn.close()

    def test_raises_on_empty_dir(self, tmp_db, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        try:
            sync_categories(tmp_db, empty_dir)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


class TestSyncDocuments:
    def test_populates_result_table(self, tmp_db, sample_corpus_dir):
        total, skipped, split_count = sync_documents(tmp_db, sample_corpus_dir)
        assert total == 3
        assert skipped == 0

        conn = sqlite3.connect(tmp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM result")
        assert cursor.fetchone()[0] == 3
        conn.close()

    def test_no_duplicates_on_resync(self, tmp_db, sample_corpus_dir):
        sync_documents(tmp_db, sample_corpus_dir)
        total, _, _ = sync_documents(tmp_db, sample_corpus_dir)
        assert total == 3

        conn = sqlite3.connect(tmp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM result")
        assert cursor.fetchone()[0] == 3
        conn.close()


class TestGetDatabaseStatus:
    def test_returns_correct_stats(self, tmp_db, sample_corpus_dir, sample_prompts_dir):
        sync_categories(tmp_db, sample_prompts_dir)
        sync_documents(tmp_db, sample_corpus_dir)
        stats = get_database_status(tmp_db)

        assert stats["original_documents"] == 3
        assert stats["total_categories"] == 2
        assert stats["total_possible_pairs"] == 6  # 3 docs x 2 categories
        assert stats["pending_pairs"] == 6
        assert stats["processed_pairs"] == 0
