"""Tests for import_results module."""

import json
import sqlite3

from llm_discovery.import_results import import_record, run_import
from llm_discovery.prep_db import sync_categories, sync_documents


class TestImportRecord:
    def test_valid_record_imported(self, tmp_db, sample_corpus_dir, sample_prompts_dir):
        sync_categories(tmp_db, sample_prompts_dir)
        sync_documents(tmp_db, sample_corpus_dir)

        conn = sqlite3.connect(tmp_db)
        cursor = conn.cursor()
        stats = {"imported": 0, "skipped": 0, "errors": 0}

        data = {
            "result_id": 1,
            "category_id": 1,
            "match": "yes",
            "reasoning_trace": "Found kid references",
            "blockquotes": ["kids aged 10-15", "making new friends"],
        }
        bq_count = import_record(cursor, data, stats)
        conn.commit()

        assert stats["imported"] == 1
        assert bq_count == 2

        cursor.execute(
            "SELECT match FROM result_category WHERE result_id = 1 AND category_id = 1"
        )
        assert cursor.fetchone()[0] == "yes"

        cursor.execute(
            "SELECT COUNT(*) FROM result_category_blockquote WHERE result_id = 1"
        )
        assert cursor.fetchone()[0] == 2
        conn.close()

    def test_idempotent_import(self, tmp_db, sample_corpus_dir, sample_prompts_dir):
        sync_categories(tmp_db, sample_prompts_dir)
        sync_documents(tmp_db, sample_corpus_dir)

        conn = sqlite3.connect(tmp_db)
        cursor = conn.cursor()
        stats = {"imported": 0, "skipped": 0, "errors": 0}

        data = {"result_id": 1, "category_id": 1, "match": "no", "blockquotes": []}
        import_record(cursor, data, stats)
        conn.commit()

        # Import same record again
        stats2 = {"imported": 0, "skipped": 0, "errors": 0}
        import_record(cursor, data, stats2)
        conn.commit()

        assert stats2["skipped"] == 1
        assert stats2["imported"] == 0
        conn.close()

    def test_missing_fields_rejected(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        cursor = conn.cursor()
        stats = {"imported": 0, "skipped": 0, "errors": 0}

        data = {"result_id": 1}  # Missing category_id and match
        import_record(cursor, data, stats)
        assert stats["errors"] == 1
        conn.close()


class TestRunImport:
    def test_imports_json_files(
        self, tmp_db, sample_corpus_dir, sample_prompts_dir, tmp_path
    ):
        sync_categories(tmp_db, sample_prompts_dir)
        sync_documents(tmp_db, sample_corpus_dir)

        # Create JSON result files
        json_dir = tmp_path / "out"
        json_dir.mkdir()
        record = {
            "result_id": 1,
            "category_id": 1,
            "match": "yes",
            "reasoning_trace": "test",
            "blockquotes": ["quote1"],
        }
        (json_dir / "r1_c1.json").write_text(json.dumps(record))

        stats = run_import(tmp_db, json_dir)
        assert stats["imported"] == 1
        assert stats["blockquotes"] == 1

    def test_handles_malformed_json(self, tmp_db, tmp_path):
        json_dir = tmp_path / "out"
        json_dir.mkdir()
        (json_dir / "r1_c1.json").write_text("not valid json{{{")

        stats = run_import(tmp_db, json_dir)
        assert stats["errors"] == 1
        assert stats["imported"] == 0
