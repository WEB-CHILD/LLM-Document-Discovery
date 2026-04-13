#!/usr/bin/env python
"""
Import JSON/JSONL result files to SQLite database.

This script reads result files from the output directory and imports them
into the SQLite database. It handles both:
- Individual JSON files (r*_c*.json) from the processor
- JSONL file (results.jsonl) consolidated by the janitor

Usage:
    uv run python import_results.py --db corpus.db --input-dir out/

The script:
1. Imports results.jsonl if present (consolidated results)
2. Imports any remaining r*_c*.json files
3. Inserts blockquotes into result_category_blockquote table
4. Skips duplicates (INSERT OR IGNORE)
5. Reports statistics on completion
"""

import argparse
import json
import sqlite3
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

console = Console()


def import_record(cursor: sqlite3.Cursor, data: dict, stats: dict) -> int:
    """Import a single record. Returns blockquote count."""
    blockquote_count = 0

    # Validate required fields
    required = ["result_id", "category_id", "match"]
    if not all(k in data for k in required):
        stats["errors"] += 1
        return 0

    try:
        cursor.execute(
            """
            INSERT OR IGNORE INTO result_category
            (result_id, category_id, match, reasoning_trace)
            VALUES (?, ?, ?, ?)
            """,
            (
                data["result_id"],
                data["category_id"],
                data["match"],
                data.get("reasoning_trace", ""),
            ),
        )

        if cursor.rowcount > 0:
            stats["imported"] += 1

            # Insert blockquotes
            for bq in data.get("blockquotes", []):
                cursor.execute(
                    """
                    INSERT INTO result_category_blockquote
                    (result_id, category_id, blockquote)
                    VALUES (?, ?, ?)
                    """,
                    (data["result_id"], data["category_id"], bq),
                )
                blockquote_count += 1
        else:
            stats["skipped"] += 1

    except sqlite3.Error:
        stats["errors"] += 1

    return blockquote_count


def import_results_to_db(input_dir: Path, db_path: Path) -> dict:
    """
    Import JSON/JSONL files to SQLite database.

    Returns dict with import statistics.
    """
    stats = {"total": 0, "imported": 0, "skipped": 0, "errors": 0, "blockquotes": 0}

    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Step 1: Import JSONL file if present
    jsonl_path = input_dir / "results.jsonl"
    jsonl_lines = 0
    if jsonl_path.exists():
        console.print(f"[dim]Found results.jsonl, counting lines...[/dim]")
        with open(jsonl_path) as f:
            jsonl_lines = sum(1 for line in f if line.strip())
        console.print(f"[dim]Importing {jsonl_lines} records from results.jsonl[/dim]")

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Importing JSONL"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        )

        with progress:
            task = progress.add_task("JSONL", total=jsonl_lines)
            with open(jsonl_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    stats["total"] += 1
                    try:
                        data = json.loads(line)
                        stats["blockquotes"] += import_record(cursor, data, stats)
                    except json.JSONDecodeError:
                        stats["errors"] += 1
                    progress.advance(task)

        # Commit after JSONL
        conn.commit()
        console.print(f"[green]✓ JSONL import complete[/green]")

    # Step 2: Import individual JSON files
    json_files = list(input_dir.glob("r*_c*.json"))

    if json_files:
        console.print(f"[dim]Found {len(json_files)} JSON files to import[/dim]")

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Importing JSON"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        )

        with progress:
            task = progress.add_task("JSON", total=len(json_files))

            for json_file in json_files:
                stats["total"] += 1
                try:
                    data = json.loads(json_file.read_text())
                    stats["blockquotes"] += import_record(cursor, data, stats)
                except json.JSONDecodeError as e:
                    console.print(f"[red]Error parsing {json_file.name}: {e}[/red]")
                    stats["errors"] += 1
                progress.advance(task)

        conn.commit()
        console.print(f"[green]✓ JSON import complete[/green]")

    if stats["total"] == 0:
        console.print(f"[yellow]No files found in {input_dir}[/yellow]")

    conn.close()
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Import JSON result files to SQLite database"
    )
    parser.add_argument(
        "--db",
        required=True,
        help="Path to corpus.db",
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Directory containing JSON result files",
    )
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    input_dir = Path(args.input_dir).resolve()

    # Validate paths
    if not db_path.exists():
        console.print(f"[red]Database not found: {db_path}[/red]")
        return 1

    if not input_dir.exists():
        console.print(f"[red]Input directory not found: {input_dir}[/red]")
        return 1

    # Show config
    config_table = Table(title="Import Configuration", show_header=False, box=None)
    config_table.add_column("Setting", style="bold")
    config_table.add_column("Value", style="cyan")
    config_table.add_row("Database", str(db_path))
    config_table.add_row("Input dir", str(input_dir))
    console.print(Panel(config_table, border_style="blue"))
    console.print()

    # Run import
    stats = import_results_to_db(input_dir, db_path)

    # Show results
    result_table = Table(title="Import Complete", show_header=False, box=None)
    result_table.add_column("Metric", style="bold")
    result_table.add_column("Value", style="cyan")
    result_table.add_row("Total files", str(stats["total"]))
    result_table.add_row("Imported", str(stats["imported"]))
    result_table.add_row("Skipped (dup)", str(stats["skipped"]))
    result_table.add_row("Errors", str(stats["errors"]))
    result_table.add_row("Blockquotes", str(stats.get("blockquotes", 0)))

    console.print()
    console.print(Panel(result_table, border_style="green"))

    return 0


if __name__ == "__main__":
    exit(main())
