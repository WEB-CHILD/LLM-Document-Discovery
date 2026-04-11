"""Pre-flight check for corpus database.

Scans for and optionally removes documents that will fail vLLM processing.
Uses affirmative validation — documents must prove they contain usable text.
Adapted from FirstRun/preflight_check.py.
"""

import sqlite3
from pathlib import Path

from rich.console import Console

from llm_discovery.content_utils import (
    BINARY_MAGIC,
    MIN_CONTENT_LENGTH,
    MIN_PRINTABLE_RATIO,
    get_content_body,
)

console = Console()


def check_document(content: str) -> tuple[bool, str]:
    """Affirmatively validate document contains usable text.

    Returns (is_valid, rejection_reason).
    """
    if not content:
        return False, "empty content"

    body = get_content_body(content)
    if not body:
        return False, "no body after header"

    if len(body) < MIN_CONTENT_LENGTH:
        return False, f"body too short ({len(body)} chars, need {MIN_CONTENT_LENGTH})"

    body_bytes = body[:20].encode("utf-8", errors="ignore")
    for magic, file_type in BINARY_MAGIC.items():
        if body_bytes.startswith(magic):
            return False, f"binary content ({file_type})"

    if "\x00" in content:
        return False, "contains null bytes"

    printable = sum(1 for c in body if c.isprintable() or c in "\n\r\t")
    ratio = printable / len(body)
    if ratio < MIN_PRINTABLE_RATIO:
        return False, f"low printable ratio ({ratio:.1%}, need {MIN_PRINTABLE_RATIO:.0%})"

    return True, ""


def run_preflight(db_path: Path, delete: bool = False) -> dict:
    """Scan database for problematic documents.

    Returns dict with keys: total, valid, problematic, deleted, by_reason.
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT result_id, filepath, content FROM result")
        rows = cursor.fetchall()
        total = len(rows)

        problematic: list[tuple[int, str, str]] = []
        for result_id, filepath, content in rows:
            is_valid, reason = check_document(content)
            if not is_valid:
                problematic.append((result_id, filepath, reason))

        by_reason: dict[str, int] = {}
        for _, _, reason in problematic:
            by_reason[reason] = by_reason.get(reason, 0) + 1

        result = {
            "total": total,
            "valid": total - len(problematic),
            "problematic": len(problematic),
            "deleted": 0,
            "by_reason": by_reason,
        }

        if delete and problematic:
            result_ids = [r[0] for r in problematic]
            placeholders = ",".join("?" * len(result_ids))

            cursor.execute(
                f"SELECT filepath, content_sha256 FROM result WHERE result_id IN ({placeholders})",
                result_ids,
            )
            hash_map = {row[0]: row[1] for row in cursor.fetchall()}

            for result_id, filepath, reason in problematic:
                content_hash = hash_map.get(filepath)
                cursor.execute(
                    "INSERT OR REPLACE INTO excluded_file (filepath, reason, content_sha256) VALUES (?, ?, ?)",
                    (filepath, reason, content_hash),
                )

            cursor.execute(
                f"DELETE FROM result_category_blockquote WHERE result_id IN ({placeholders})",
                result_ids,
            )
            cursor.execute(
                f"DELETE FROM result_category WHERE result_id IN ({placeholders})",
                result_ids,
            )
            cursor.execute(
                f"DELETE FROM result WHERE result_id IN ({placeholders})",
                result_ids,
            )

            conn.commit()
            result["deleted"] = len(problematic)

    return result
