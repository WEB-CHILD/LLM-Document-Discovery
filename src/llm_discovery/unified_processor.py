"""Unified Corpus Processor: streaming architecture with JSON file output.

Architecture:
- Reader thread: fetchmany() from DB, builds request bodies, feeds work_queue
- Worker threads: pull from work_queue, make HTTP requests, write JSON files
- Bounded queues provide backpressure

Adapted from FirstRun/unified_processor.py.
"""

import json
import os
import queue
import re
import socket
import sqlite3
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yaml
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
    TimeRemainingColumn,
)
from rich.table import Table

console = Console()

# Configuration
MAX_CONTENT_LENGTH = 80000
WORK_QUEUE_MAXSIZE = 100
FETCH_BATCH_SIZE = 50


def log(msg: str) -> None:
    """Log message with timestamp."""
    now = time.strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def open_db(db_path: str | Path) -> sqlite3.Connection:
    """Open SQLite connection with proper timeout settings."""
    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.execute("PRAGMA busy_timeout = 60000")
    return conn


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def extract_json_from_text(text: str) -> dict | None:
    """Extract JSON from response text by finding balanced braces."""
    if "{" not in text:
        return None
    start = text.find("{")
    depth = 0
    in_string = False
    escape = False
    for i, char in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if char == "\\" and in_string:
            escape = True
            continue
        if char == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def extract_reasoning(text: str) -> str:
    """Extract reasoning text before JSON."""
    json_start = text.rfind("{")
    if json_start == -1:
        return ""
    return text[:json_start].strip()


def parse_custom_id(custom_id: str) -> tuple[int, int]:
    """Parse custom_id to extract result_id and category_id."""
    parts = custom_id.split("_c")
    return int(parts[0][1:]), int(parts[1])


def parse_response(
    custom_id: str, response: dict | None, error: str | None
) -> tuple[dict | None, str | None]:
    """Parse server response into database-ready format."""
    if error:
        return None, f"HTTP error: {error}"
    if response is None:
        return None, "No response received"
    choices = response.get("choices", [])
    if not choices:
        return None, "No choices in response"
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if not content:
        return None, "Empty content in response"

    result_id, category_id = parse_custom_id(custom_id)
    category_result = extract_json_from_text(content)
    if category_result is None:
        preview = content[:200].replace("\n", " ")
        return None, f"No JSON found in response. Preview: {preview}..."
    if "match" not in category_result:
        return None, f"Missing 'match' field in JSON: {category_result}"

    reasoning = message.get("reasoning_content", "") or extract_reasoning(content)
    return {
        "result_id": result_id,
        "category_id": category_id,
        "match": category_result["match"],
        "reasoning_trace": reasoning,
        "blockquotes": category_result.get("blockquotes", []),
    }, None


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------


def load_system_prompt(system_prompt_path: Path) -> str:
    """Load universal system prompt."""
    with open(system_prompt_path) as f:
        return f.read()


def load_category_prompts(prompts_dir: Path) -> dict[str, str]:
    """Load category prompts from YAML files."""
    prompts = {}
    for yaml_file in prompts_dir.glob("*.yaml"):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        prompts[yaml_file.name] = data.get("prompt", "")
    return prompts


# ---------------------------------------------------------------------------
# Request body construction
# ---------------------------------------------------------------------------


def build_request_body(
    result_id: int,
    category_id: int,
    content: str,
    category_filename: str,
    system_prompt: str,
    category_prompts: dict[str, str],
    model: str,
) -> tuple[str, dict[str, Any]]:
    """Build request body for vLLM server."""
    custom_id = f"r{result_id}_c{category_id}"
    category_prompt = category_prompts.get(category_filename, "")
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": f"""# Category Instructions

{category_prompt}

# Document to Analyze

{content}

# Response Format

First, provide your reasoning and analysis.
Then, provide ONLY valid JSON with this structure:
{{
  "match": "yes" or "maybe" or "no",
  "blockquotes": ["quote 1", "quote 2"]
}}""",
        },
    ]
    return custom_id, {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 32000,
    }


# ---------------------------------------------------------------------------
# HTTP request
# ---------------------------------------------------------------------------


def do_request(custom_id: str, body: dict[str, Any], server_url: str) -> dict[str, Any]:
    """Send single request to vLLM server."""
    url = server_url.rstrip("/") + "/v1/chat/completions"
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    start = time.time()
    response = None
    error = None
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = resp.read()
        response = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        error = f"HTTPError {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        error = f"URLError: {e.reason}"
    except Exception as e:
        error = f"Exception: {e!r}"

    return {
        "custom_id": custom_id,
        "response": response,
        "error": error,
        "elapsed_sec": time.time() - start,
    }


# ---------------------------------------------------------------------------
# Atomic JSON file writer
# ---------------------------------------------------------------------------


def save_result_to_file(parsed: dict, output_dir: Path) -> bool:
    """Atomically write parsed result to JSON file. Returns True if saved."""
    custom_id = f"r{parsed['result_id']}_c{parsed['category_id']}"
    final_path = output_dir / f"{custom_id}.json"
    if final_path.exists():
        return False
    temp_path = output_dir / f".{custom_id}.json.tmp"
    temp_path.write_text(json.dumps(parsed, indent=2))
    temp_path.rename(final_path)
    return True


# ---------------------------------------------------------------------------
# Completed pairs tracking
# ---------------------------------------------------------------------------


def get_completed_pairs(output_dir: Path) -> set[tuple[int, int]]:
    """Get set of (result_id, category_id) pairs already completed."""
    completed = set()
    for f in output_dir.glob("r*_c*.json"):
        match = re.match(r"r(\d+)_c(\d+)\.json", f.name)
        if match:
            completed.add((int(match.group(1)), int(match.group(2))))
    jsonl_path = output_dir / "results.jsonl"
    if jsonl_path.exists():
        try:
            with open(jsonl_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if "result_id" in data and "category_id" in data:
                            completed.add((int(data["result_id"]), int(data["category_id"])))
                    except (json.JSONDecodeError, KeyError, ValueError):
                        pass
        except OSError:
            pass
    return completed


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class Metrics:
    """Collect metrics for monitoring."""

    def __init__(self):
        self.lock = threading.Lock()
        self.request_times: list[float] = []

    def record_request_time(self, elapsed: float) -> None:
        with self.lock:
            self.request_times.append(elapsed)

    def summary(self) -> dict:
        if self.request_times:
            return {
                "request_time_avg": f"{statistics.mean(self.request_times):.2f}s",
                "request_time_min": f"{min(self.request_times):.2f}s",
                "request_time_max": f"{max(self.request_times):.2f}s",
            }
        return {}


# ---------------------------------------------------------------------------
# Run statistics
# ---------------------------------------------------------------------------


def start_run(db_path: Path, model: str) -> int:
    """Create a new run record and return its ID."""
    conn = open_db(db_path)
    cursor = conn.cursor()
    hostname = socket.gethostname()
    cursor.execute(
        "INSERT INTO run_stats (started_at, model, hostname) VALUES (datetime('now'), ?, ?)",
        (model, hostname),
    )
    run_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return run_id


def finish_run(
    db_path: Path,
    run_id: int,
    pairs_processed: int,
    pairs_saved: int,
    pairs_failed: int,
    pairs_skipped: int,
    processing_seconds: float,
    notes: str | None = None,
) -> None:
    """Update run record with final statistics."""
    conn = open_db(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE run_stats SET finished_at = datetime('now'),
           pairs_processed = ?, pairs_saved = ?, pairs_failed = ?,
           pairs_skipped = ?, processing_seconds = ?, notes = ?
           WHERE run_id = ?""",
        (pairs_processed, pairs_saved, pairs_failed, pairs_skipped, processing_seconds, notes, run_id),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Streaming: Reader thread
# ---------------------------------------------------------------------------


def reader_thread_fn(
    db_path: str,
    output_dir: Path,
    work_queue: queue.Queue,
    stop_event: threading.Event,
    system_prompt: str,
    category_prompts: dict[str, str],
    model: str,
    metrics: Metrics,
    limit: int | None,
) -> None:
    """Reader thread: fetch rows from DB, build request bodies, put on queue."""
    completed = get_completed_pairs(output_dir)
    log(f"Reader: found {len(completed)} completed pairs in output dir")

    limit_clause = f"LIMIT {limit * 2}" if limit else ""
    query = f"""
        SELECT r.result_id, r.filepath, r.content,
               c.category_id, c.category_filename, c.category_name
        FROM result r
        CROSS JOIN category c
        WHERE NOT EXISTS (
            SELECT 1 FROM result_category rc
            WHERE rc.result_id = r.result_id AND rc.category_id = c.category_id
        )
        AND (
            r.part_number IS NOT NULL
            OR (r.parent_result_id IS NULL AND r.part_number IS NULL
                AND LENGTH(r.content) <= {MAX_CONTENT_LENGTH}
                AND NOT EXISTS (
                    SELECT 1 FROM result child WHERE child.parent_result_id = r.result_id
                ))
        )
        ORDER BY r.result_id, c.category_id
        {limit_clause}
    """

    conn = open_db(db_path)
    cursor = conn.cursor()
    cursor.execute(query)
    total_queued = 0

    while not stop_event.is_set():
        rows = cursor.fetchmany(FETCH_BATCH_SIZE)
        if not rows:
            break
        for row in rows:
            result_id, _, content, category_id, category_filename, _ = row
            if (result_id, category_id) in completed:
                continue
            custom_id, body = build_request_body(
                result_id, category_id, content, category_filename,
                system_prompt, category_prompts, model,
            )
            work_queue.put((custom_id, body))
            total_queued += 1
            if limit and total_queued >= limit:
                break
        if limit and total_queued >= limit:
            break

    cursor.close()
    conn.close()
    work_queue.put(None)
    log(f"Reader complete: {total_queued} items queued")


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def run_processor(
    db_path: Path,
    output_dir: Path,
    server_url: str,
    system_prompt_path: Path,
    concurrency: int = 128,
    limit: int | None = None,
    model: str = "openai/gpt-oss-20b",
    prompts_dir: Path | None = None,
) -> dict:
    """Run the streaming processor. Returns stats dict."""
    if prompts_dir is None:
        prompts_dir = db_path.parent / "prompts"

    output_dir.mkdir(parents=True, exist_ok=True)

    # Load prompts
    system_prompt = load_system_prompt(system_prompt_path)
    category_prompts = load_category_prompts(prompts_dir)

    # Start run tracking
    run_id = start_run(db_path, model)

    # Count pending work
    conn = open_db(db_path)
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT COUNT(*) FROM result r CROSS JOIN category c
        WHERE NOT EXISTS (
            SELECT 1 FROM result_category rc
            WHERE rc.result_id = r.result_id AND rc.category_id = c.category_id
        )
        AND (r.part_number IS NOT NULL
            OR (r.parent_result_id IS NULL AND r.part_number IS NULL
                AND LENGTH(r.content) <= {MAX_CONTENT_LENGTH}
                AND NOT EXISTS (
                    SELECT 1 FROM result child WHERE child.parent_result_id = r.result_id
                )))
    """)
    pending_in_db = cursor.fetchone()[0]
    conn.close()

    json_completed = get_completed_pairs(output_dir)
    pairs_to_process = min(pending_in_db, limit) if limit else pending_in_db

    if pairs_to_process == 0:
        finish_run(db_path, run_id, 0, 0, 0, 0, 0.0, notes="No pairs to process")
        return {"run_id": run_id, "total": 0, "saved": 0, "skipped": 0, "failed": 0}

    log(f"Will process up to {pairs_to_process} pairs")
    if json_completed:
        console.print(f"[dim]Reader will skip {len(json_completed)} pairs with existing JSON files[/dim]")

    # Set up queues and events
    work_queue_obj: queue.Queue = queue.Queue(maxsize=WORK_QUEUE_MAXSIZE)
    stop_event = threading.Event()
    metrics = Metrics()
    stats = {"saved": 0, "failed": 0, "skipped": 0}
    stats_lock = threading.Lock()

    # Start reader thread
    reader = threading.Thread(
        target=reader_thread_fn,
        args=(str(db_path), output_dir, work_queue_obj, stop_event,
              system_prompt, category_prompts, model, metrics, limit),
    )
    reader.start()

    # Process with thread pool
    overall_start = time.time()
    completed_count = 0

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        TextColumn("[cyan]{task.fields[rate]:.2f} req/s"),
        console=console,
        refresh_per_second=4,
    )

    with progress:
        task = progress.add_task(
            f"Processing ({concurrency} workers)", total=pairs_to_process, rate=0.0,
        )
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures: dict[Any, tuple[str, dict, int]] = {}
            reader_done = False
            max_retries = 3

            while not reader_done or futures:
                while not reader_done and len(futures) < concurrency * 2:
                    try:
                        item = work_queue_obj.get(timeout=0.1)
                        if item is None:
                            reader_done = True
                            break
                        custom_id, body = item
                        future = executor.submit(do_request, custom_id, body, server_url)
                        futures[future] = (custom_id, body, 0)
                    except queue.Empty:
                        break

                done_futures = [f for f in futures if f.done()]
                for future in done_futures:
                    custom_id, body, retry_count = futures.pop(future)
                    try:
                        result = future.result()
                        metrics.record_request_time(result["elapsed_sec"])
                        parsed, failure_reason = parse_response(
                            custom_id, result["response"], result["error"]
                        )
                        if parsed:
                            saved = save_result_to_file(parsed, output_dir)
                            with stats_lock:
                                if saved:
                                    stats["saved"] += 1
                                else:
                                    stats["skipped"] += 1
                            completed_count += 1
                        else:
                            if retry_count < max_retries:
                                new_future = executor.submit(do_request, custom_id, body, server_url)
                                futures[new_future] = (custom_id, body, retry_count + 1)
                            else:
                                with stats_lock:
                                    stats["failed"] += 1
                                completed_count += 1

                        elapsed = time.time() - overall_start
                        rate = completed_count / elapsed if elapsed > 0 else 0
                        progress.update(task, completed=completed_count, rate=rate)
                    except Exception as e:
                        console.print(f"[red][ERROR] Worker exception: {e}[/red]")
                        with stats_lock:
                            stats["failed"] += 1
                        completed_count += 1
                        progress.update(task, completed=completed_count)

                time.sleep(0.01)

    reader.join(timeout=60)
    stop_event.set()

    total_time = time.time() - overall_start
    processing_seconds = sum(metrics.request_times) if metrics.request_times else 0.0

    finish_run(db_path, run_id, completed_count, stats["saved"],
               stats["failed"], stats["skipped"], processing_seconds)

    table = Table(title="Processing Complete", show_header=False, box=None)
    table.add_column("Metric", style="bold")
    table.add_column("Value", style="cyan")
    table.add_row("Total time (wall)", f"{total_time:.1f}s")
    table.add_row("Processing time (vLLM)", f"{processing_seconds:.1f}s")
    table.add_row("Processed", str(completed_count))
    table.add_row("Saved", str(stats["saved"]))
    table.add_row("Skipped", str(stats["skipped"]))
    table.add_row("Failed", str(stats["failed"]))
    console.print()
    console.print(Panel(table, border_style="green"))

    return {
        "run_id": run_id,
        "total_time_sec": total_time,
        "processing_seconds": processing_seconds,
        "processed": completed_count,
        "saved": stats["saved"],
        "skipped": stats["skipped"],
        "failed": stats["failed"],
    }
