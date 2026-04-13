#!/usr/bin/env python3
"""
Pre-flight check for corpus database.

Scans for and optionally removes documents that will fail vLLM processing.
Uses AFFIRMATIVE validation - documents must prove they contain usable text,
not just lack obvious problems.

Usage:
    python preflight_check.py --db corpus.db           # Report only
    python preflight_check.py --db corpus.db --delete  # Delete problematic docs
"""

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Binary file magic bytes (at start of content body)
BINARY_MAGIC: Dict[bytes, str] = {
    # Archives
    b'PK': 'ZIP archive',
    b'Rar!': 'RAR archive',
    b'7z\xbc\xaf': '7-Zip archive',
    # Executables
    b'MZ': 'DOS/Windows EXE',
    b'\x7fELF': 'Linux ELF binary',
    # Multimedia containers
    b'RIFF': 'AVI/WAV container',
    b'CWS': 'Compressed SWF (Flash)',
    b'FWS': 'Uncompressed SWF (Flash)',
    b'OggS': 'Ogg container',
    b'fLaC': 'FLAC audio',
    b'ID3': 'MP3 with ID3 tag',
    b'\xff\xfb': 'MP3 audio',
    # Images
    b'GIF87a': 'GIF image',
    b'GIF89a': 'GIF image',
    b'\x89PNG': 'PNG image',
    b'\xff\xd8\xff': 'JPEG image',
    b'BM': 'BMP image',
    # Documents
    b'%PDF': 'PDF document',
    b'\xd0\xcf\x11\xe0': 'MS Office (old)',
    b'PK\x03\x04': 'MS Office (new)/EPUB',
}

# Minimum body length to be considered useful
MIN_BODY_LENGTH = 100

# Minimum printable ratio for valid text
MIN_PRINTABLE_RATIO = 0.85


def get_content_body(content: str) -> str:
    """Extract body after URL header line."""
    if '\n\n' in content:
        return content.split('\n\n', 1)[1]
    return content


def check_document(content: str, filepath: str) -> Tuple[bool, str]:
    """
    AFFIRMATIVELY validate document contains usable text.

    Returns:
        Tuple of (is_valid, rejection_reason)

    Validation requires:
    1. Content exists and has body after header
    2. Body meets minimum length
    3. No binary magic bytes detected
    4. No null bytes
    5. High ratio of printable characters
    """
    # 1. Content must exist
    if not content:
        return False, 'empty content'

    # 2. Must have body after URL header
    body = get_content_body(content)
    if not body:
        return False, 'no body after header'

    # 3. Body must meet minimum length
    if len(body) < MIN_BODY_LENGTH:
        return False, f'body too short ({len(body)} chars, need {MIN_BODY_LENGTH})'

    # 4. Check for binary magic bytes at start of body
    body_bytes = body[:20].encode('utf-8', errors='ignore')
    for magic, file_type in BINARY_MAGIC.items():
        if body_bytes.startswith(magic):
            return False, f'binary content ({file_type})'

    # 5. No null bytes anywhere
    if '\x00' in content:
        return False, 'contains null bytes'

    # 6. AFFIRMATIVE: Must have high ratio of printable text
    printable = sum(1 for c in body if c.isprintable() or c in '\n\r\t')
    ratio = printable / len(body)
    if ratio < MIN_PRINTABLE_RATIO:
        return False, f'low printable ratio ({ratio:.1%}, need {MIN_PRINTABLE_RATIO:.0%})'

    # All checks passed - document is valid
    return True, ''


def get_excluded_count(cursor: sqlite3.Cursor) -> int:
    """Get count of already-excluded files."""
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='excluded_file'
    """)
    if not cursor.fetchone():
        return 0

    cursor.execute("SELECT COUNT(*) FROM excluded_file")
    return cursor.fetchone()[0]


def scan_database(db_path: Path) -> Tuple[List[Tuple[int, str, str]], int, int]:
    """
    Scan database for problematic documents.

    Returns:
        Tuple of (problematic_docs, total_docs, already_excluded_count)
        where problematic_docs is List of (result_id, filepath, rejection_reason)
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    already_excluded = get_excluded_count(cursor)

    cursor.execute("SELECT result_id, filepath, content FROM result")
    rows = cursor.fetchall()
    total = len(rows)

    problematic = []
    for result_id, filepath, content in rows:
        is_valid, reason = check_document(content, filepath)
        if not is_valid:
            problematic.append((result_id, filepath, reason))

    conn.close()
    return problematic, total, already_excluded


def delete_documents(
    db_path: Path,
    problematic: List[Tuple[int, str, str]]
) -> Tuple[int, int, int]:
    """
    Delete documents and their related records from database.
    Also records them in excluded_file table for future runs.

    Args:
        db_path: Path to database
        problematic: List of (result_id, filepath, reason) tuples

    Returns:
        Tuple of (deleted_blockquotes, deleted_categories, deleted_results)
    """
    if not problematic:
        return 0, 0, 0

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    result_ids = [r[0] for r in problematic]
    placeholders = ','.join('?' * len(result_ids))

    # First, get content hashes for excluded files
    cursor.execute(f"""
        SELECT filepath, content_sha256 FROM result
        WHERE result_id IN ({placeholders})
    """, result_ids)
    hash_map = {row[0]: row[1] for row in cursor.fetchall()}

    # Ensure excluded_file table exists (for existing DBs)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS excluded_file (
            filepath TEXT PRIMARY KEY,
            reason TEXT NOT NULL,
            content_sha256 TEXT,
            excluded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Record exclusions
    for result_id, filepath, reason in problematic:
        content_hash = hash_map.get(filepath)
        cursor.execute("""
            INSERT OR REPLACE INTO excluded_file (filepath, reason, content_sha256)
            VALUES (?, ?, ?)
        """, (filepath, reason, content_hash))

    # Delete in order due to FK constraints
    cursor.execute(f"""
        DELETE FROM result_category_blockquote
        WHERE result_id IN ({placeholders})
    """, result_ids)
    deleted_blockquotes = cursor.rowcount

    cursor.execute(f"""
        DELETE FROM result_category
        WHERE result_id IN ({placeholders})
    """, result_ids)
    deleted_categories = cursor.rowcount

    cursor.execute(f"""
        DELETE FROM result
        WHERE result_id IN ({placeholders})
    """, result_ids)
    deleted_results = cursor.rowcount

    conn.commit()
    conn.close()

    return deleted_blockquotes, deleted_categories, deleted_results


def main():
    parser = argparse.ArgumentParser(
        description="Pre-flight check for corpus database"
    )
    parser.add_argument(
        "--db",
        default="corpus.db",
        help="Database path (default: corpus.db)"
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete problematic documents (default: report only)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show all problematic documents"
    )

    args = parser.parse_args()
    db_path = Path(args.db)

    if not db_path.exists():
        print(f"Error: Database not found: {db_path}")
        sys.exit(1)

    print("=" * 60)
    print("Pre-flight Database Check")
    print("=" * 60)
    print(f"Database: {db_path}")
    print(f"Min body length: {MIN_BODY_LENGTH} chars")
    print(f"Min printable ratio: {MIN_PRINTABLE_RATIO:.0%}")
    print()

    # Scan for problematic documents
    print("Scanning documents...")
    problematic, total, already_excluded = scan_database(db_path)

    valid_count = total - len(problematic)
    print(f"Total documents in DB: {total}")
    print(f"Already excluded (from previous runs): {already_excluded}")
    print(f"Valid: {valid_count} ({valid_count/total*100:.1f}%)" if total > 0 else "Valid: 0")
    print(f"Problematic: {len(problematic)} ({len(problematic)/total*100:.1f}%)" if total > 0 else "Problematic: 0")

    if not problematic:
        print()
        print("✓ All documents passed validation")
        sys.exit(0)

    # Group by reason
    by_reason: Dict[str, List[Tuple[int, str]]] = {}
    for result_id, filepath, reason in problematic:
        if reason not in by_reason:
            by_reason[reason] = []
        by_reason[reason].append((result_id, filepath))

    print()
    print("Issues found:")
    for reason, docs in sorted(by_reason.items(), key=lambda x: -len(x[1])):
        print(f"  {reason}: {len(docs)}")
        if args.verbose:
            for result_id, filepath in docs[:5]:
                filename = Path(filepath).name
                print(f"    - r{result_id}: {filename}")
            if len(docs) > 5:
                print(f"    ... and {len(docs) - 5} more")

    if args.delete:
        print()
        print("=" * 60)
        print("Deleting problematic documents...")
        print("=" * 60)

        deleted_bq, deleted_cat, deleted_res = delete_documents(db_path, problematic)

        print(f"✓ Deleted {deleted_res} documents")
        print(f"  - {deleted_cat} category results")
        print(f"  - {deleted_bq} blockquotes")
        print()
        print(f"Remaining valid documents: {valid_count}")
        sys.exit(0)
    else:
        print()
        print("Run with --delete to remove problematic documents")
        sys.exit(1)


if __name__ == "__main__":
    main()
