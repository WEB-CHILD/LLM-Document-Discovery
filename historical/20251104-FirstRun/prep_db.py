#!/usr/bin/env python
"""
Prepare database for corpus processing.

This script:
1. Creates database from schema.sql if it doesn't exist
2. Syncs category table with POC-prompts/ directory (SHA-256 hash tracking)
3. Syncs result table with input directory (SHA-256 hash tracking)
4. Reports status: pending pairs, completed pairs, etc.

Run this BEFORE starting unified_processor.py to ensure DB is ready.

Usage:
    uv run python prep_db.py --db corpus.db --input-dir input/markdown_corpus
    uv run python prep_db.py --db corpus.db --input-dir input/markdown_corpus --quiet

Arguments:
    --db          Database path (default: corpus.db)
    --input-dir   Corpus directory (default: INPUT_DIR env var, or input/markdown_corpus)
    --quiet, -q   Suppress per-file output, show only summary

For different corpora:
    uv run python prep_db.py --db corpus_kidlink.db --input-dir input/kidlink_corpus
"""

import argparse
import hashlib
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import yaml
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# Quiet mode - set via --quiet flag
QUIET = False

# Minimum content length to be considered valid (after URL header)
MIN_CONTENT_LENGTH = 100
MAX_CONTENT_LENGTH = 80000  # ~16k words - documents larger than this are split

# Split configuration
SPLIT_TARGET_SIZE = 70000  # Target size for split parts (chars)
SPLIT_MAX_SIZE = 80000     # Maximum size for split parts (chars)
SPLIT_OVERLAP = 500        # Overlap between parts for context continuity

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


def get_content_body(content: str) -> str:
    """Extract body after URL header line."""
    if "\n\n" in content:
        return content.split("\n\n", 1)[1]
    return content


def is_binary_content(content: str) -> tuple[bool, str]:
    """Check if content starts with binary magic bytes."""
    body = get_content_body(content)
    if not body:
        return False, ""

    body_bytes = body[:10].encode("utf-8", errors="ignore")

    for magic, file_type in BINARY_MAGIC.items():
        if body_bytes.startswith(magic):
            return True, file_type
    return False, ""


def is_valid_text_content(content: str) -> tuple[bool, str]:
    """Check if content is valid text, not binary garbage."""
    if not content:
        return False, "empty content"

    body = get_content_body(content)
    if not body or len(body) < MIN_CONTENT_LENGTH:
        return False, f"content too short ({len(body) if body else 0} chars)"

    is_binary, binary_type = is_binary_content(content)
    if is_binary:
        return False, f"binary content detected ({binary_type})"

    if "\x00" in content:
        return False, "contains null bytes"

    printable = sum(1 for c in body if c.isprintable() or c in "\n\r\t")
    ratio = printable / len(body)
    if ratio < 0.85:
        return False, f"low printable ratio ({ratio:.1%})"

    return True, ""


def sha256_file(filepath: Path) -> str:
    """Calculate SHA-256 hash of file contents."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def sha256_string(content: str) -> str:
    """Calculate SHA-256 hash of string content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# Text splitter for large documents - uses LangChain for robust splitting
# Separators verified against Kidlink corpus: forums use "* * *", docs use paragraphs
_text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=SPLIT_TARGET_SIZE,
    chunk_overlap=SPLIT_OVERLAP,
    separators=[
        "\n * * *\n",   # Forum post separators (with leading space)
        "\n* * *\n",    # Forum post separators (no leading space)
        "\n---\n",      # Horizontal rules
        "\n\n\n",       # Triple newlines
        "\n\n",         # Paragraphs
        "\n",           # Lines
        ". ",           # Sentences
        " ",            # Words
        "",             # Characters (last resort)
    ],
    length_function=len,
    is_separator_regex=False,
)


def split_document(content: str, url_header: str) -> list[str]:
    """
    Split a large document into parts at natural break points.

    Uses LangChain's RecursiveCharacterTextSplitter for robust splitting
    that respects forum post boundaries and paragraph structure.

    Args:
        content: Full document content (including URL header)
        url_header: The URL header line to preserve in each part

    Returns:
        List of content strings for each part (each includes the URL header)
    """
    body = get_content_body(content)
    if not body:
        return [content]

    # If content fits, no split needed
    if len(content) <= SPLIT_MAX_SIZE:
        return [content]

    # Split the body using LangChain
    body_parts = _text_splitter.split_text(body)

    # Prepend URL header to each part
    return [f"{url_header}\n\n{part}" for part in body_parts]


def create_database(db_path: Path, schema_path: Path) -> bool:
    """Create database from schema. Returns True if created, False if existed."""
    if db_path.exists():
        console.print(f"[dim]Database exists: {db_path}[/dim]")
        return False

    console.print(f"[bold]Creating database: {db_path}[/bold]")

    conn = sqlite3.connect(db_path, timeout=60.0)
    cursor = conn.cursor()

    with open(schema_path) as f:
        schema_sql = f.read()

    cursor.executescript(schema_sql)
    conn.commit()
    conn.close()

    console.print(f"[green]✓ Database created[/green]")
    return True


def sync_categories(cursor: sqlite3.Cursor, prompts_dir: Path) -> dict[int, dict[str, Any]]:
    """Sync category table with POC-prompts/ directory."""
    category_files = sorted(prompts_dir.glob("*.yaml"))

    if not category_files:
        raise ValueError(f"No YAML files found in {prompts_dir}")

    categories = {}
    added = 0

    for cat_file in category_files:
        prompt_hash = sha256_file(cat_file)

        with open(cat_file) as f:
            data = yaml.safe_load(f)

        category_name = data.get("name", "")
        category_description = data.get("description", "")

        cursor.execute(
            """
            SELECT category_id, category_name, category_description
            FROM category
            WHERE category_filename = ? AND prompt_sha256 = ?
        """,
            (cat_file.name, prompt_hash),
        )

        row = cursor.fetchone()

        if row:
            category_id = row[0]
            categories[category_id] = {
                "filename": cat_file.name,
                "name": row[1],
                "description": row[2],
            }
        else:
            cursor.execute(
                """
                INSERT INTO category (category_filename, category_name,
                                    category_description, prompt_sha256)
                VALUES (?, ?, ?, ?)
            """,
                (cat_file.name, category_name, category_description, prompt_hash),
            )

            category_id = cursor.lastrowid
            categories[category_id] = {
                "filename": cat_file.name,
                "name": category_name,
                "description": category_description,
            }
            if not QUIET:
                console.print(f"[dim]  + Added category {category_id}: {cat_file.name}[/dim]")
            added += 1

    return categories


def sync_documents(cursor: sqlite3.Cursor, input_dir: Path) -> tuple[list[int], int, int]:
    """
    Sync result table with input/ directory.

    Returns:
        Tuple of (result_ids, skipped_count, split_count)
    """
    md_files = sorted(input_dir.glob("*.md"))

    if not md_files:
        raise ValueError(f"No .md files found in {input_dir}")

    result_ids = []
    skipped_count = 0
    split_count = 0
    added = 0
    total_files = len(md_files)
    last_progress = -1  # Start at -1 so first file triggers 0% message

    console.print(f"[dim]  Found {total_files:,} files to sync[/dim]")

    for i, md_file in enumerate(md_files):
        # Progress output: immediately at start, then every 5%
        progress = ((i + 1) * 100) // total_files
        if progress == 0 and last_progress == -1:
            console.print(f"[dim]  Sync progress: 0% (starting...)[/dim]")
            last_progress = 0
        elif progress >= last_progress + 5:
            console.print(f"[dim]  Sync progress: {progress}% ({i + 1:,}/{total_files:,})[/dim]")
            last_progress = progress

        content_hash = sha256_file(md_file)

        cursor.execute(
            """
            SELECT result_id FROM result
            WHERE filepath = ? AND content_sha256 = ?
        """,
            (str(md_file), content_hash),
        )

        row = cursor.fetchone()

        if row:
            result_ids.append(row[0])
        else:
            with open(md_file) as f:
                content = f.read()

            is_valid, rejection_reason = is_valid_text_content(content)
            if not is_valid:
                skipped_count += 1
                continue

            # Check if document needs splitting
            if len(content) > MAX_CONTENT_LENGTH:
                # Extract URL header for split parts
                url_header = content.split("\n\n", 1)[0] if "\n\n" in content else ""

                # Insert the original document (not processed, just for reference)
                cursor.execute(
                    """
                    INSERT INTO result (filepath, content, content_sha256, part_number, parent_result_id)
                    VALUES (?, ?, ?, NULL, NULL)
                """,
                    (str(md_file), content, content_hash),
                )
                parent_id = cursor.lastrowid
                result_ids.append(parent_id)

                # Split the document
                parts = split_document(content, url_header)

                # Insert each part
                for part_num, part_content in enumerate(parts, start=1):
                    part_filepath = f"{md_file}_{part_num}"
                    part_hash = sha256_string(part_content)

                    cursor.execute(
                        """
                        INSERT INTO result (filepath, content, content_sha256, part_number, parent_result_id)
                        VALUES (?, ?, ?, ?, ?)
                    """,
                        (part_filepath, part_content, part_hash, part_num, parent_id),
                    )
                    part_id = cursor.lastrowid
                    result_ids.append(part_id)

                split_count += 1
                added += 1
            else:
                # Normal document - insert as-is
                cursor.execute(
                    """
                    INSERT INTO result (filepath, content, content_sha256, part_number, parent_result_id)
                    VALUES (?, ?, ?, NULL, NULL)
                """,
                    (str(md_file), content, content_hash),
                )

                result_id = cursor.lastrowid
                result_ids.append(result_id)
                added += 1

    console.print(f"[dim]  Sync complete: {added} added, {skipped_count} skipped, {split_count} split[/dim]")
    return result_ids, skipped_count, split_count


def get_database_status(cursor: sqlite3.Cursor) -> dict[str, Any]:
    """Get comprehensive database status."""
    stats: dict[str, Any] = {}

    # Total rows in result table
    cursor.execute("SELECT COUNT(*) FROM result")
    stats["total_rows"] = cursor.fetchone()[0]

    # Original documents (not split parts)
    cursor.execute("SELECT COUNT(*) FROM result WHERE parent_result_id IS NULL")
    stats["original_documents"] = cursor.fetchone()[0]

    # Split parent documents (have children)
    cursor.execute("""
        SELECT COUNT(DISTINCT parent_result_id) FROM result
        WHERE parent_result_id IS NOT NULL
    """)
    stats["split_documents"] = cursor.fetchone()[0]

    # Split parts
    cursor.execute("SELECT COUNT(*) FROM result WHERE part_number IS NOT NULL")
    stats["split_parts"] = cursor.fetchone()[0]

    # Eligible for processing: split parts OR unsplit originals that fit in size limit
    # (Parent documents of splits are NOT processed - only their parts are)
    # Uses NOT EXISTS instead of NOT IN for O(n log n) vs O(n²) on 289k rows
    cursor.execute(f"""
        SELECT COUNT(*) FROM result r
        WHERE (r.part_number IS NOT NULL)  -- Split parts
           OR (r.parent_result_id IS NULL AND r.part_number IS NULL
               AND LENGTH(r.content) <= {MAX_CONTENT_LENGTH}
               AND NOT EXISTS (
                   SELECT 1 FROM result child WHERE child.parent_result_id = r.result_id
               ))
    """)
    stats["eligible_documents"] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM category")
    stats["total_categories"] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM result_category")
    stats["processed_pairs"] = cursor.fetchone()[0]

    stats["total_possible_pairs"] = stats["eligible_documents"] * stats["total_categories"]
    stats["pending_pairs"] = stats["total_possible_pairs"] - stats["processed_pairs"]

    # Get run stats if table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='run_stats'
    """)
    if cursor.fetchone():
        cursor.execute("""
            SELECT COUNT(*), COALESCE(SUM(pairs_processed), 0),
                   COALESCE(SUM(processing_seconds), 0)
            FROM run_stats WHERE finished_at IS NOT NULL
        """)
        row = cursor.fetchone()
        stats["completed_runs"] = row[0]
        stats["cumulative_pairs"] = row[1]
        stats["cumulative_hours"] = row[2] / 3600.0
    else:
        stats["completed_runs"] = 0
        stats["cumulative_pairs"] = 0
        stats["cumulative_hours"] = 0.0

    return stats


def main():
    """Prepare database for corpus processing."""
    global QUIET

    parser = argparse.ArgumentParser(description="Prepare database for corpus processing")
    parser.add_argument("--db", default="corpus.db", help="Database path (default: corpus.db)")
    parser.add_argument(
        "--input-dir",
        default=os.environ.get("INPUT_DIR"),
        help="Input corpus directory (default: INPUT_DIR env var, or input/markdown_corpus)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress per-file output, show only summary",
    )

    args = parser.parse_args()
    QUIET = args.quiet

    # Setup paths
    project_root = Path(__file__).parent
    db_path = project_root / args.db
    prompts_dir = project_root / "POC-prompts"
    # Use --input-dir if provided, else INPUT_DIR env var, else default
    if args.input_dir:
        input_dir = Path(args.input_dir)
        if not input_dir.is_absolute():
            input_dir = project_root / input_dir
    else:
        input_dir = project_root / "input" / "markdown_corpus"
    schema_path = project_root / "schema.sql"

    # Validate paths
    if not prompts_dir.exists():
        console.print(f"[red]Error: POC-prompts directory not found: {prompts_dir}[/red]")
        sys.exit(1)

    if not input_dir.exists():
        console.print(f"[red]Error: input directory not found: {input_dir}[/red]")
        sys.exit(1)

    if not schema_path.exists():
        console.print(f"[red]Error: schema.sql not found: {schema_path}[/red]")
        sys.exit(1)

    # Step 1: Create database
    console.print("\n[bold]Step 1: Database[/bold]")
    create_database(db_path, schema_path)

    # Connect
    conn = sqlite3.connect(db_path, timeout=60.0)
    cursor = conn.cursor()

    try:
        # Step 2: Sync categories
        console.print("\n[bold]Step 2: Sync Categories[/bold]")
        categories = sync_categories(cursor, prompts_dir)
        console.print(f"[green]✓ {len(categories)} categories synced[/green]")

        # Step 3: Sync documents
        console.print("\n[bold]Step 3: Sync Documents[/bold]")
        result_ids, skipped, split_count = sync_documents(cursor, input_dir)
        console.print(f"[green]✓ {len(result_ids)} documents synced[/green]")
        if skipped:
            console.print(f"[yellow]  Skipped {skipped} invalid files[/yellow]")
        if split_count:
            console.print(f"[cyan]  Split {split_count} large documents[/cyan]")

        conn.commit()

        # Step 4: Report status
        console.print("\n[bold]Step 4: Database Status[/bold]")
        stats = get_database_status(cursor)

        table = Table(show_header=False, box=None)
        table.add_column("Metric", style="bold")
        table.add_column("Value", style="cyan", justify="right")

        table.add_row("Original documents", str(stats["original_documents"]))
        if stats["split_documents"] > 0:
            table.add_row("  Split into parts", str(stats["split_documents"]))
            table.add_row("  Total parts", str(stats["split_parts"]))
        table.add_row("Eligible for processing", str(stats["eligible_documents"]))
        table.add_row("Categories", str(stats["total_categories"]))
        table.add_row("", "")
        table.add_row("Total pairs possible", f"{stats['total_possible_pairs']:,}")
        table.add_row("Processed pairs", f"{stats['processed_pairs']:,}")
        table.add_row("[bold]Pending pairs[/bold]", f"[bold]{stats['pending_pairs']:,}[/bold]")

        if stats["completed_runs"] > 0:
            table.add_row("", "")
            table.add_row("Completed runs", str(stats["completed_runs"]))
            table.add_row("Cumulative processing", f"{stats['cumulative_hours']:.2f}h")

        progress_pct = (
            stats["processed_pairs"] / stats["total_possible_pairs"] * 100
            if stats["total_possible_pairs"] > 0
            else 0
        )
        table.add_row("", "")
        table.add_row("Progress", f"{progress_pct:.1f}%")

        console.print(Panel(table, title="Corpus Status", border_style="green"))

        if stats["pending_pairs"] == 0:
            console.print("\n[green]✓ All pairs processed! Nothing to do.[/green]")
        else:
            console.print(f"\n[bold]Ready to process {stats['pending_pairs']:,} pairs.[/bold]")
            console.print("[dim]Run: unified_processor.py --db corpus.db --skip-sync ...[/dim]")

    except Exception as e:
        conn.rollback()
        console.print(f"[red]Error: {e}[/red]")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
