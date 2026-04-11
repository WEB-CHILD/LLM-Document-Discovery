"""Tests for preflight_check module."""

import sqlite3

from llm_discovery.preflight_check import check_document, run_preflight


class TestCheckDocument:
    def test_valid_markdown_passes(self):
        content = (
            "20040701020553/http://www.example.com/\n\n" + "Valid text content. " * 20
        )
        is_valid, reason = check_document(content)
        assert is_valid is True
        assert reason == ""

    def test_empty_content_rejected(self):
        is_valid, reason = check_document("")
        assert is_valid is False
        assert "empty" in reason

    def test_binary_gif_rejected(self):
        content = "20040701020553/http://www.example.com/\n\nGIF89a" + "x" * 200
        is_valid, reason = check_document(content)
        assert is_valid is False
        assert "GIF" in reason

    def test_binary_pdf_rejected(self):
        content = "20040701020553/http://www.example.com/\n\n%PDF-1.4" + "x" * 200
        is_valid, reason = check_document(content)
        assert is_valid is False
        assert "PDF" in reason

    def test_short_body_rejected(self):
        content = "20040701020553/http://www.example.com/\n\nToo short"
        is_valid, reason = check_document(content)
        assert is_valid is False
        assert "short" in reason

    def test_null_bytes_rejected(self):
        content = (
            "20040701020553/http://www.example.com/\n\n"
            + "Valid text\x00more text" * 20
        )
        is_valid, reason = check_document(content)
        assert is_valid is False
        assert "null" in reason

    def test_low_printable_ratio_rejected(self):
        body = "\x01\x02\x03\x04\x05" * 50  # Non-printable bytes
        content = "20040701020553/http://www.example.com/\n\n" + body
        is_valid, reason = check_document(content)
        assert is_valid is False
        assert "printable" in reason


class TestRunPreflight:
    def test_all_valid_documents(self, tmp_db, sample_corpus_dir):
        # First sync documents into the DB
        from llm_discovery.prep_db import sync_documents

        sync_documents(tmp_db, sample_corpus_dir)

        result = run_preflight(tmp_db)
        assert result["total"] == 3
        assert result["valid"] == 3
        assert result["problematic"] == 0

    def test_detects_invalid_documents(self, tmp_db):
        # Insert a document with binary content directly
        conn = sqlite3.connect(tmp_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO result (filepath, content, content_sha256) VALUES (?, ?, ?)",
            ("bad.md", "20040701020553/http://x.com/\n\nGIF89a" + "x" * 200, "abc123"),
        )
        cursor.execute(
            "INSERT INTO result (filepath, content, content_sha256) VALUES (?, ?, ?)",
            (
                "good.md",
                "20040701020553/http://x.com/\n\n" + "Valid content. " * 20,
                "def456",
            ),
        )
        conn.commit()
        conn.close()

        result = run_preflight(tmp_db)
        assert result["total"] == 2
        assert result["valid"] == 1
        assert result["problematic"] == 1

    def test_delete_removes_problematic(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO result (filepath, content, content_sha256) VALUES (?, ?, ?)",
            ("bad.md", "20040701020553/http://x.com/\n\nGIF89a" + "x" * 200, "abc123"),
        )
        conn.commit()
        conn.close()

        result = run_preflight(tmp_db, delete=True)
        assert result["deleted"] == 1

        conn = sqlite3.connect(tmp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM result")
        assert cursor.fetchone()[0] == 0
        conn.close()
