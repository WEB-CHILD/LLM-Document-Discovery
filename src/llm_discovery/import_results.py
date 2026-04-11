"""Import JSON/JSONL result files to SQLite database.

Reads result files from the output directory and imports them into the SQLite
database. Handles both individual JSON files (r*_c*.json) and consolidated
JSONL file (results.jsonl). Adapted from FirstRun/import_results.py.
"""

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
    required = ["result_id", "category_id", "match"]
    if not all(k in data for k in required):
        stats["errors"] += 1
        return 0

    blockquote_count = 0
    try:
        cursor.execute(
            """INSERT OR IGNORE INTO result_category
               (result_id, category_id, match, reasoning_trace)
               VALUES (?, ?, ?, ?)""",
            (
                data["result_id"],
                data["category_id"],
                data["match"],
                data.get("reasoning_trace", ""),
            ),
        )
        if cursor.rowcount > 0:
            stats["imported"] += 1
            for bq in data.get("blockquotes", []):
                cursor.execute(
                    """INSERT INTO result_category_blockquote
                       (result_id, category_id, blockquote)
                       VALUES (?, ?, ?)""",
                    (data["result_id"], data["category_id"], bq),
                )
                blockquote_count += 1
        else:
            stats["skipped"] += 1
    except sqlite3.Error:
        stats["errors"] += 1

    return blockquote_count


def _make_progress(label: str) -> Progress:
    """Create a standard import progress bar."""
    return Progress(
        SpinnerColumn(),
        TextColumn(f"[bold blue]Importing {label}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    )


def run_import(db_path: Path, input_dir: Path) -> dict:
    """Import JSON/JSONL files to SQLite database. Returns stats dict."""
    stats = {
        "total": 0,
        "imported": 0,
        "skipped": 0,
        "errors": 0,
        "blockquotes": 0,
    }

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Step 1: Import JSONL if present
    jsonl_path = input_dir / "results.jsonl"
    if jsonl_path.exists():
        with jsonl_path.open() as f:
            jsonl_lines = sum(1 for line in f if line.strip())

        console.print(f"[dim]Importing {jsonl_lines} records from results.jsonl[/dim]")
        with _make_progress("JSONL") as progress:
            task = progress.add_task("JSONL", total=jsonl_lines)
            with jsonl_path.open() as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    stats["total"] += 1
                    try:
                        data = json.loads(stripped)
                        stats["blockquotes"] += import_record(cursor, data, stats)
                    except json.JSONDecodeError:
                        stats["errors"] += 1
                    progress.advance(task)
        conn.commit()

    # Step 2: Import individual JSON files
    json_files = list(input_dir.glob("r*_c*.json"))
    if json_files:
        console.print(f"[dim]Found {len(json_files)} JSON files to import[/dim]")
        with _make_progress("JSON") as progress:
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

    if stats["total"] == 0:
        console.print(f"[yellow]No files found in {input_dir}[/yellow]")

    conn.close()

    # Display results
    table = Table(title="Import Complete", show_header=False, box=None)
    table.add_column("Metric", style="bold")
    table.add_column("Value", style="cyan")
    table.add_row("Total files", str(stats["total"]))
    table.add_row("Imported", str(stats["imported"]))
    table.add_row("Skipped (dup)", str(stats["skipped"]))
    table.add_row("Errors", str(stats["errors"]))
    table.add_row("Blockquotes", str(stats["blockquotes"]))
    console.print(Panel(table, border_style="green"))

    return stats
