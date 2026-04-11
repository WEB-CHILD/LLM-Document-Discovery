"""Prepare database for corpus processing.

Creates database from schema.sql, syncs categories from prompts/*.yaml,
and syncs documents from input directory. Adapted from FirstRun/prep_db.py.
"""

import sqlite3
from pathlib import Path
from typing import Any

import yaml
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from llm_discovery.content_utils import (
    get_content_body,
    is_valid_text_content,
    sha256_file,
    sha256_string,
)

console = Console()

MAX_CONTENT_LENGTH = 80000  # ~16k words — documents larger than this are split

# Split configuration
SPLIT_TARGET_SIZE = 70000
SPLIT_MAX_SIZE = 80000
SPLIT_OVERLAP = 500

_text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=SPLIT_TARGET_SIZE,
    chunk_overlap=SPLIT_OVERLAP,
    separators=[
        "\n * * *\n",
        "\n* * *\n",
        "\n---\n",
        "\n\n\n",
        "\n\n",
        "\n",
        ". ",
        " ",
        "",
    ],
    length_function=len,
    is_separator_regex=False,
)


def split_document(content: str, url_header: str) -> list[str]:
    """Split a large document into parts at natural break points."""
    body = get_content_body(content)
    if not body or len(content) <= SPLIT_MAX_SIZE:
        return [content]
    body_parts = _text_splitter.split_text(body)
    return [f"{url_header}\n\n{part}" for part in body_parts]


def create_db(db_path: Path, schema_path: Path) -> bool:
    """Create database from schema.sql if it doesn't exist.

    Returns True if created, False if already existed.
    """
    if db_path.exists():
        return False
    with sqlite3.connect(db_path, timeout=60.0) as conn:
        cursor = conn.cursor()
        with open(schema_path) as f:
            cursor.executescript(f.read())
        conn.commit()
    return True


def sync_categories(
    db_path: Path, prompts_dir: Path, quiet: bool = False
) -> int:
    """Sync category table with prompts/*.yaml directory.

    Returns the number of categories now in the table.
    """
    category_files = sorted(prompts_dir.glob("*.yaml"))
    if not category_files:
        raise ValueError(f"No YAML files found in {prompts_dir}")

    with sqlite3.connect(db_path, timeout=60.0) as conn:
        cursor = conn.cursor()
        count = 0
        added = 0

        for cat_file in category_files:
            prompt_hash = sha256_file(cat_file)
            with open(cat_file) as f:
                data = yaml.safe_load(f)

            category_name = data.get("name", "")
            category_description = data.get("description", "")

            cursor.execute(
                "SELECT category_id FROM category WHERE category_filename = ? AND prompt_sha256 = ?",
                (cat_file.name, prompt_hash),
            )
            row = cursor.fetchone()

            if row:
                count += 1
            else:
                cursor.execute(
                    """INSERT INTO category (category_filename, category_name,
                       category_description, prompt_sha256)
                       VALUES (?, ?, ?, ?)""",
                    (cat_file.name, category_name, category_description, prompt_hash),
                )
                count += 1
                added += 1
                if not quiet:
                    console.print(f"[dim]  + Added category: {cat_file.name}[/dim]")

        conn.commit()
    return count


def sync_documents(
    db_path: Path, input_dir: Path, quiet: bool = False
) -> tuple[int, int, int]:
    """Sync result table with input directory.

    Returns (total_synced, skipped_count, split_count).
    """
    md_files = sorted(input_dir.glob("*.md"))
    if not md_files:
        raise ValueError(f"No .md files found in {input_dir}")

    with sqlite3.connect(db_path, timeout=60.0) as conn:
        cursor = conn.cursor()
        total_synced = 0
        skipped_count = 0
        split_count = 0

        for md_file in md_files:
            content_hash = sha256_file(md_file)

            cursor.execute(
                "SELECT result_id FROM result WHERE filepath = ? AND content_sha256 = ?",
                (str(md_file), content_hash),
            )
            if cursor.fetchone():
                total_synced += 1
                continue

            with open(md_file) as f:
                content = f.read()

            is_valid, reason = is_valid_text_content(content)
            if not is_valid:
                if not quiet:
                    console.print(f"[yellow]  Skipping {md_file.name}: {reason}[/yellow]")
                skipped_count += 1
                continue

            if len(content) > MAX_CONTENT_LENGTH:
                url_header = content.split("\n\n", 1)[0] if "\n\n" in content else ""
                cursor.execute(
                    """INSERT INTO result (filepath, content, content_sha256, part_number, parent_result_id)
                       VALUES (?, ?, ?, NULL, NULL)""",
                    (str(md_file), content, content_hash),
                )
                parent_id = cursor.lastrowid
                parts = split_document(content, url_header)
                for part_num, part_content in enumerate(parts, start=1):
                    part_hash = sha256_string(part_content)
                    cursor.execute(
                        """INSERT INTO result (filepath, content, content_sha256, part_number, parent_result_id)
                           VALUES (?, ?, ?, ?, ?)""",
                        (f"{md_file}_{part_num}", part_content, part_hash, part_num, parent_id),
                    )
                split_count += 1
                total_synced += 1
            else:
                cursor.execute(
                    """INSERT INTO result (filepath, content, content_sha256, part_number, parent_result_id)
                       VALUES (?, ?, ?, NULL, NULL)""",
                    (str(md_file), content, content_hash),
                )
                total_synced += 1

        conn.commit()
    return total_synced, skipped_count, split_count


def get_database_status(db_path: Path) -> dict[str, Any]:
    """Get comprehensive database status."""
    with sqlite3.connect(db_path, timeout=60.0) as conn:
        cursor = conn.cursor()
        stats: dict[str, Any] = {}

        cursor.execute("SELECT COUNT(*) FROM result")
        stats["total_rows"] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM result WHERE parent_result_id IS NULL")
        stats["original_documents"] = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(DISTINCT parent_result_id) FROM result WHERE parent_result_id IS NOT NULL"
        )
        stats["split_documents"] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM result WHERE part_number IS NOT NULL")
        stats["split_parts"] = cursor.fetchone()[0]

        cursor.execute(f"""
            SELECT COUNT(*) FROM result r
            WHERE (r.part_number IS NOT NULL)
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

    return stats


def run_prep_db(
    db_path: Path,
    input_dir: Path,
    prompts_dir: Path,
    schema_path: Path,
    quiet: bool = False,
) -> None:
    """Orchestrate full database preparation."""
    console.print("\n[bold]Step 1: Database[/bold]")
    created = create_db(db_path, schema_path)
    if created:
        console.print("[green]Database created[/green]")
    else:
        console.print(f"[dim]Database exists: {db_path}[/dim]")

    console.print("\n[bold]Step 2: Sync Categories[/bold]")
    cat_count = sync_categories(db_path, prompts_dir, quiet=quiet)
    console.print(f"[green]{cat_count} categories synced[/green]")

    console.print("\n[bold]Step 3: Sync Documents[/bold]")
    total, skipped, split_count = sync_documents(db_path, input_dir, quiet=quiet)
    console.print(f"[green]{total} documents synced[/green]")
    if skipped:
        console.print(f"[yellow]  Skipped {skipped} invalid files[/yellow]")
    if split_count:
        console.print(f"[cyan]  Split {split_count} large documents[/cyan]")

    console.print("\n[bold]Step 4: Database Status[/bold]")
    stats = get_database_status(db_path)

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

    console.print(Panel(table, title="Corpus Status", border_style="green"))

    if stats["pending_pairs"] == 0:
        console.print("\n[green]All pairs processed! Nothing to do.[/green]")
    else:
        console.print(f"\n[bold]Ready to process {stats['pending_pairs']:,} pairs.[/bold]")
