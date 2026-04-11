"""Pre-flight check for corpus database.

Scans for and optionally removes documents that will fail vLLM processing.
Uses affirmative validation — documents must prove they contain usable text.
Adapted from FirstRun/preflight_check.py.
"""

import sqlite3
from pathlib import Path

from rich.console import Console

console = Console()

# Binary file magic bytes (at start of content body)
BINARY_MAGIC: dict[bytes, str] = {
    b"PK": "ZIP archive",
    b"Rar!": "RAR archive",
    b"7z\xbc\xaf": "7-Zip archive",
    b"MZ": "DOS/Windows EXE",
    b"\x7fELF": "Linux ELF binary",
    b"RIFF": "AVI/WAV container",
    b"CWS": "Compressed SWF (Flash)",
    b"FWS": "Uncompressed SWF (Flash)",
    b"OggS": "Ogg container",
    b"fLaC": "FLAC audio",
    b"ID3": "MP3 with ID3 tag",
    b"\xff\xfb": "MP3 audio",
    b"GIF87a": "GIF image",
    b"GIF89a": "GIF image",
    b"\x89PNG": "PNG image",
    b"\xff\xd8\xff": "JPEG image",
    b"BM": "BMP image",
    b"%PDF": "PDF document",
    b"\xd0\xcf\x11\xe0": "MS Office (old)",
    b"PK\x03\x04": "MS Office (new)/EPUB",
}

MIN_BODY_LENGTH = 100
MIN_PRINTABLE_RATIO = 0.85


def get_content_body(content: str) -> str:
    """Extract body after URL header line."""
    if "\n\n" in content:
        return content.split("\n\n", 1)[1]
    return content


def check_document(content: str) -> tuple[bool, str]:
    """Affirmatively validate document contains usable text.

    Returns (is_valid, rejection_reason).
    """
    if not content:
        return False, "empty content"

    body = get_content_body(content)
    if not body:
        return False, "no body after header"

    if len(body) < MIN_BODY_LENGTH:
        return False, f"body too short ({len(body)} chars, need {MIN_BODY_LENGTH})"

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
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT result_id, filepath, content FROM result")
    rows = cursor.fetchall()
    total = len(rows)

    problematic: list[tuple[int, str, str]] = []
    for result_id, filepath, content in rows:
        is_valid, reason = check_document(content)
        if not is_valid:
            problematic.append((result_id, filepath, reason))

    # Group by reason
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

        # Get hashes for excluded_file tracking
        cursor.execute(
            f"SELECT filepath, content_sha256 FROM result WHERE result_id IN ({placeholders})",
            result_ids,
        )
        hash_map = {row[0]: row[1] for row in cursor.fetchall()}

        # Record exclusions
        for result_id, filepath, reason in problematic:
            content_hash = hash_map.get(filepath)
            cursor.execute(
                "INSERT OR REPLACE INTO excluded_file (filepath, reason, content_sha256) VALUES (?, ?, ?)",
                (filepath, reason, content_hash),
            )

        # Delete in FK order
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

    conn.close()
    return result
