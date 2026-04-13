#!/usr/bin/env python
"""
Unified Corpus Processor: Streaming architecture with JSON file output.

Architecture (from Elaboration07):
- Reader thread: fetchmany() from DB, builds request bodies, feeds work_queue
- Worker threads: pull from work_queue, make HTTP requests, write JSON files
- Bounded queues provide backpressure

Benefits:
- Crash-safe: atomic file writes (temp + rename)
- Resumable: skip existing output files
- High throughput: streaming keeps workers saturated
- Syncthing-safe: individual files sync atomically

Usage:
    uv run python unified_processor.py \\
        --db corpus.db \\
        --output-dir out/ \\
        --server-url http://localhost:8000 \\
        --concurrency 128 \\
        --limit 100
"""

import argparse
import hashlib
import json
import os
import queue
import re
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

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

MAX_CONTENT_LENGTH = 80000  # ~16k words - documents larger than this are split
MIN_CONTENT_LENGTH = 100

# Split configuration (must match prep_db.py)
SPLIT_TARGET_SIZE = 70000  # Target size for split parts (chars)
SPLIT_MAX_SIZE = 80000     # Maximum size for split parts (chars)
SPLIT_OVERLAP = 500        # Overlap between parts for context continuity

# Queue sizes for backpressure (from Elaboration07)
WORK_QUEUE_MAXSIZE = 100
FETCH_BATCH_SIZE = 50


# Binary file magic bytes (at start of content body)
BINARY_MAGIC: dict[bytes, str] = {
    # Archives
    b"PK": "ZIP archive",
    b"Rar!": "RAR archive",
    b"7z\xbc\xaf": "7-Zip archive",
    # Executables
    b"MZ": "DOS/Windows EXE",
    b"\x7fELF": "Linux ELF binary",
    # Multimedia containers
    b"RIFF": "AVI/WAV container",
    b"CWS": "Compressed SWF (Flash)",
    b"FWS": "Uncompressed SWF (Flash)",
    b"OggS": "Ogg container",
    b"fLaC": "FLAC audio",
    b"ID3": "MP3 with ID3 tag",
    b"\xff\xfb": "MP3 audio",
    # Images
    b"GIF87a": "GIF image",
    b"GIF89a": "GIF image",
    b"\x89PNG": "PNG image",
    b"\xff\xd8\xff": "JPEG image",
    b"BM": "BMP image",
    # Documents
    b"%PDF": "PDF document",
    b"\xd0\xcf\x11\xe0": "MS Office (old)",
    b"PK\x03\x04": "MS Office (new)/EPUB",
}


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------


def log(msg: str) -> None:
    """Log message with timestamp."""
    now = time.strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def open_db(db_path: str | Path) -> sqlite3.Connection:
    """Open SQLite connection with proper timeout settings for concurrent access."""
    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.execute("PRAGMA busy_timeout = 60000")  # 60s in milliseconds
    return conn


# -----------------------------------------------------------------------------
# Content validation (from generate_batch.py)
# -----------------------------------------------------------------------------


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


# Patterns for natural split points (in priority order)
SPLIT_PATTERNS = [
    # Email headers (start of new email)
    re.compile(r"^Date:\s+", re.MULTILINE),
    # Horizontal rules
    re.compile(r"^\* \* \*$", re.MULTILINE),
    re.compile(r"^-{3,}$", re.MULTILINE),
    re.compile(r"^={3,}$", re.MULTILINE),
    # Markdown headings
    re.compile(r"^#{1,3} ", re.MULTILINE),
    # Double blank lines (paragraph break)
    re.compile(r"\n\n\n"),
]

# Sentence boundary for fallback
SENTENCE_BOUNDARY = re.compile(r"\. (?=[A-Z\n])")


def find_split_points(content: str) -> list[int]:
    """Find all potential split points in content."""
    points = set()
    for pattern in SPLIT_PATTERNS:
        for match in pattern.finditer(content):
            points.add(match.start())
    for match in SENTENCE_BOUNDARY.finditer(content):
        points.add(match.end())
    return sorted(points)


def split_document(content: str, url_header: str) -> list[str]:
    """Split a large document into parts at natural break points."""
    body = get_content_body(content)
    if not body or len(content) <= SPLIT_MAX_SIZE:
        return [content]

    split_points = find_split_points(body)
    parts = []
    current_start = 0
    body_length = len(body)

    while current_start < body_length:
        target_end = current_start + SPLIT_TARGET_SIZE
        max_end = current_start + SPLIT_MAX_SIZE

        if target_end >= body_length or max_end >= body_length:
            parts.append(f"{url_header}\n\n{body[current_start:]}")
            break

        best_point = None
        for point in split_points:
            if point <= current_start:
                continue
            if point > max_end:
                break
            if best_point is None or abs(point - target_end) < abs(best_point - target_end):
                best_point = point

        if best_point is None:
            best_point = target_end

        parts.append(f"{url_header}\n\n{body[current_start:best_point]}")
        current_start = max(0, best_point - SPLIT_OVERLAP)

    return parts


# -----------------------------------------------------------------------------
# Database sync (from generate_batch.py)
# -----------------------------------------------------------------------------


def create_database(db_path: Path, schema_path: Path) -> None:
    """Create database from schema if it doesn't exist."""
    if db_path.exists():
        return

    console.print(f"[dim]Creating database: {db_path}[/dim]")

    conn = open_db(db_path)
    cursor = conn.cursor()

    with open(schema_path) as f:
        schema_sql = f.read()

    cursor.executescript(schema_sql)
    conn.commit()
    conn.close()

    console.print(f"[green]✓ Database created: {db_path}[/green]")


def sync_categories(cursor: sqlite3.Cursor, prompts_dir: Path) -> dict[int, dict]:
    """Sync category table with POC-prompts/ directory."""
    category_files = sorted(prompts_dir.glob("*.yaml"))

    if not category_files:
        raise ValueError(f"No YAML files found in {prompts_dir}")

    categories = {}

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
                "prompt": data.get("prompt", ""),
                "hash": prompt_hash,
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
                "prompt": data.get("prompt", ""),
                "hash": prompt_hash,
            }
            console.print(
                f"[dim]  + Added category {category_id}: {cat_file.name}[/dim]"
            )

    return categories


def sync_documents(
    cursor: sqlite3.Cursor, input_dir: Path, quiet: bool = False
) -> tuple[list[int], int, int]:
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
    added_count = 0
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
                url_header = content.split("\n\n", 1)[0] if "\n\n" in content else ""

                # Insert original (not processed, just for reference)
                cursor.execute(
                    """
                    INSERT INTO result (filepath, content, content_sha256, part_number, parent_result_id)
                    VALUES (?, ?, ?, NULL, NULL)
                """,
                    (str(md_file), content, content_hash),
                )
                parent_id = cursor.lastrowid
                result_ids.append(parent_id)

                # Split and insert parts
                parts = split_document(content, url_header)
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
                    result_ids.append(cursor.lastrowid)

                split_count += 1
                added_count += 1
            else:
                # Normal document
                cursor.execute(
                    """
                    INSERT INTO result (filepath, content, content_sha256, part_number, parent_result_id)
                    VALUES (?, ?, ?, NULL, NULL)
                """,
                    (str(md_file), content, content_hash),
                )
                result_id = cursor.lastrowid
                result_ids.append(result_id)
                added_count += 1

    console.print(f"[dim]  Sync complete: {added_count} added, {skipped_count} skipped, {split_count} split[/dim]")
    return result_ids, skipped_count, split_count


# -----------------------------------------------------------------------------
# Metrics collection
# -----------------------------------------------------------------------------


class Metrics:
    """Collect metrics for monitoring."""

    def __init__(self):
        self.lock = threading.Lock()
        self.queue_depths: list[int] = []
        self.rss_samples: list[int] = []
        self.request_times: list[float] = []
        self.db_write_times: list[float] = []
        self.body_construction_times: list[float] = []

    def record_queue_depth(self, depth: int) -> None:
        with self.lock:
            self.queue_depths.append(depth)

    def record_rss(self, rss_bytes: int) -> None:
        with self.lock:
            self.rss_samples.append(rss_bytes)

    def record_request_time(self, elapsed: float) -> None:
        with self.lock:
            self.request_times.append(elapsed)

    def record_db_write_time(self, elapsed: float) -> None:
        with self.lock:
            self.db_write_times.append(elapsed)

    def record_body_construction_time(self, elapsed: float) -> None:
        with self.lock:
            self.body_construction_times.append(elapsed)

    def summary(self) -> dict:
        """Generate summary statistics."""
        summary = {}

        if self.rss_samples:
            max_rss_mb = max(self.rss_samples) / (1024 * 1024)
            summary["max_rss_mb"] = f"{max_rss_mb:.1f}"

        if self.request_times:
            summary["request_time_avg"] = f"{statistics.mean(self.request_times):.2f}s"
            summary["request_time_min"] = f"{min(self.request_times):.2f}s"
            summary["request_time_max"] = f"{max(self.request_times):.2f}s"

        return summary


def get_rss_bytes() -> int:
    """Get current RSS memory usage in bytes (Linux only)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    return 0


# -----------------------------------------------------------------------------
# Response parsing
# -----------------------------------------------------------------------------


def extract_json_from_text(text: str) -> dict | None:
    """Extract JSON from response text by finding balanced braces."""
    if "{" not in text:
        return None

    # Find first opening brace
    start = text.find("{")

    # Find matching closing brace by counting depth
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
    result_id = int(parts[0][1:])
    category_id = int(parts[1])
    return result_id, category_id


def parse_response(
    custom_id: str, response: dict | None, error: str | None
) -> tuple[dict | None, str | None]:
    """
    Parse server response into database-ready format.

    Returns (parsed_result, failure_reason) tuple.
    If parsing succeeds, failure_reason is None.
    If parsing fails, parsed_result is None and failure_reason explains why.
    """
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
        # Log first 200 chars of content for debugging
        preview = content[:200].replace('\n', ' ')
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


# -----------------------------------------------------------------------------
# Prompt loading
# -----------------------------------------------------------------------------


def load_system_prompt(project_root: Path) -> str:
    """Load universal system prompt."""
    with open(project_root / "system_prompt.txt") as f:
        return f.read()


def load_category_prompts(prompts_dir: Path) -> dict[str, str]:
    """Load category prompts from YAML files."""
    prompts = {}
    for yaml_file in prompts_dir.glob("*.yaml"):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        prompts[yaml_file.name] = data.get("prompt", "")
    return prompts


# -----------------------------------------------------------------------------
# Request body construction
# -----------------------------------------------------------------------------


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

    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 32000,
    }

    return custom_id, body


# -----------------------------------------------------------------------------
# HTTP request
# -----------------------------------------------------------------------------


def do_request(
    custom_id: str,
    body: dict[str, Any],
    server_url: str,
) -> dict[str, Any]:
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
    except Exception as e:  # noqa: BLE001
        error = f"Exception: {e!r}"

    elapsed = time.time() - start

    return {
        "custom_id": custom_id,
        "response": response,
        "error": error,
        "elapsed_sec": elapsed,
    }


# -----------------------------------------------------------------------------
# Streaming: Reader thread
# -----------------------------------------------------------------------------


def get_completed_pairs(output_dir: Path) -> set[tuple[int, int]]:
    """Get set of (result_id, category_id) pairs already completed.

    Checks both:
    - Individual JSON files (r{id}_c{id}.json)
    - JSONL file (results.jsonl) created by janitor
    """
    completed = set()

    # Check individual JSON files
    for f in output_dir.glob("r*_c*.json"):
        match = re.match(r"r(\d+)_c(\d+)\.json", f.name)
        if match:
            completed.add((int(match.group(1)), int(match.group(2))))

    # Check JSONL file
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
                        pass  # Skip malformed lines
        except OSError:
            pass  # File might be being written to

    return completed


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
    """
    Reader thread: fetch rows from DB, build request bodies, put on queue.

    Skips pairs that already have output files (resumability).
    """
    # Get already-completed pairs
    completed = get_completed_pairs(output_dir)
    log(f"Reader: found {len(completed)} completed pairs in output dir")

    # Build query
    limit_clause = f"LIMIT {limit * 2}" if limit else ""  # Over-fetch to account for skips

    # Query eligible documents:
    # - Split parts (part_number IS NOT NULL) - always process
    # - Unsplit originals (parent_result_id IS NULL AND part_number IS NULL) that fit
    # - Exclude parent documents that have children (they've been split)
    query = f"""
        SELECT r.result_id, r.filepath, r.content,
               c.category_id, c.category_filename, c.category_name
        FROM result r
        CROSS JOIN category c
        WHERE NOT EXISTS (
            SELECT 1 FROM result_category rc
            WHERE rc.result_id = r.result_id
            AND rc.category_id = c.category_id
        )
        AND (
            -- Split parts: always process
            r.part_number IS NOT NULL
            OR (
                -- Unsplit originals: must fit in size AND not have children
                r.parent_result_id IS NULL
                AND r.part_number IS NULL
                AND LENGTH(r.content) <= {MAX_CONTENT_LENGTH}
                AND NOT EXISTS (
                    SELECT 1 FROM result child
                    WHERE child.parent_result_id = r.result_id
                )
            )
        )
        ORDER BY r.result_id, c.category_id
        {limit_clause}
    """

    # Create connection in this thread (SQLite requires same-thread usage)
    conn = open_db(db_path)
    cursor = conn.cursor()
    cursor.execute(query)

    total_read = 0
    total_queued = 0

    while not stop_event.is_set():
        # Fetch a batch
        rows = cursor.fetchmany(FETCH_BATCH_SIZE)
        if not rows:
            break

        for row in rows:
            result_id, filepath, content, category_id, category_filename, _ = row

            # Skip if already completed (file exists)
            if (result_id, category_id) in completed:
                continue

            # Build request body
            body_start = time.time()
            custom_id, body = build_request_body(
                result_id,
                category_id,
                content,
                category_filename,
                system_prompt,
                category_prompts,
                model,
            )
            body_time = time.time() - body_start
            metrics.record_body_construction_time(body_time)

            # Put on queue (blocks if full - backpressure)
            work_queue.put((custom_id, body))
            total_queued += 1

            # Periodic progress
            if total_queued % 1000 == 0:
                log(f"Reader: queued {total_queued} items")

            if limit and total_queued >= limit:
                break

            total_read += 1

        if limit and total_queued >= limit:
            break

    cursor.close()
    conn.close()

    # Signal completion
    work_queue.put(None)
    log(f"Reader complete: {total_queued} items queued")


# -----------------------------------------------------------------------------
# Streaming: Metrics sampler thread
# -----------------------------------------------------------------------------


def metrics_sampler_fn(
    work_queue: queue.Queue,
    stop_event: threading.Event,
    metrics: Metrics,
) -> None:
    """Sample queue depth and RSS periodically."""
    while not stop_event.is_set():
        metrics.record_queue_depth(work_queue.qsize())
        metrics.record_rss(get_rss_bytes())
        time.sleep(0.5)


# -----------------------------------------------------------------------------
# Janitor thread: consolidate JSON files to JSONL
# -----------------------------------------------------------------------------


class JanitorStats:
    """Track janitor statistics."""

    def __init__(self):
        self.lock = threading.Lock()
        self.appended = 0
        self.deleted = 0
        self.errors = 0

    def record_append(self, count: int) -> None:
        with self.lock:
            self.appended += count

    def record_delete(self, count: int) -> None:
        with self.lock:
            self.deleted += count

    def record_error(self) -> None:
        with self.lock:
            self.errors += 1

    def get_stats(self) -> dict:
        with self.lock:
            return {
                "appended": self.appended,
                "deleted": self.deleted,
                "errors": self.errors,
            }


def load_jsonl_pairs(jsonl_path: Path) -> set[tuple[int, int]]:
    """Load (result_id, category_id) pairs from JSONL file."""
    pairs = set()
    if not jsonl_path.exists():
        return pairs
    try:
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if "result_id" in data and "category_id" in data:
                        pairs.add((int(data["result_id"]), int(data["category_id"])))
                except (json.JSONDecodeError, KeyError, ValueError):
                    pass
    except OSError:
        pass
    return pairs


def janitor_thread_fn(
    db_path: str,  # Unused but kept for interface compatibility
    output_dir: Path,
    stop_event: threading.Event,
    janitor_stats: JanitorStats,
    batch_size: int = 100,
    min_age_seconds: float = 2.0,
) -> None:
    """
    Janitor thread: consolidate JSON files to JSONL.

    Flow (safe, verify-before-delete):
    1. Scan for JSON files older than min_age_seconds
    2. For each file:
       a. If NOT in JSONL: append to JSONL
       b. If already in JSONL (or just appended): delete JSON file
    3. Periodically reload JSONL index for verification
    """
    jsonl_path = output_dir / "results.jsonl"

    # Load existing pairs from JSONL
    jsonl_pairs = load_jsonl_pairs(jsonl_path)
    log(f"Janitor: loaded {len(jsonl_pairs)} existing pairs from JSONL")

    def process_batch(files: list[Path]) -> None:
        """Process a batch of JSON files."""
        nonlocal jsonl_pairs

        to_append = []
        to_delete = []

        for json_file in files:
            try:
                # Parse filename to get IDs
                match = re.match(r"r(\d+)_c(\d+)\.json", json_file.name)
                if not match:
                    continue
                pair = (int(match.group(1)), int(match.group(2)))

                # Check if already in JSONL
                if pair in jsonl_pairs:
                    # Already consolidated, safe to delete
                    to_delete.append(json_file)
                    continue

                # Read and validate
                data = json.loads(json_file.read_text())
                if not all(k in data for k in ["result_id", "category_id", "match"]):
                    log(f"Janitor: missing fields in {json_file.name}")
                    janitor_stats.record_error()
                    continue

                to_append.append((json_file, data, pair))

            except json.JSONDecodeError as e:
                log(f"Janitor: JSON error in {json_file.name}: {e}")
                janitor_stats.record_error()
            except Exception as e:  # noqa: BLE001
                log(f"Janitor: error processing {json_file.name}: {e}")
                janitor_stats.record_error()

        # Append new entries to JSONL (with fsync for crash safety)
        if to_append:
            try:
                with open(jsonl_path, "a") as f:
                    for json_file, data, pair in to_append:
                        f.write(json.dumps(data) + "\n")
                        jsonl_pairs.add(pair)
                        to_delete.append(json_file)
                    f.flush()
                    os.fsync(f.fileno())  # Ensure on disk before deleting sources
                janitor_stats.record_append(len(to_append))
            except OSError as e:
                log(f"Janitor: error appending to JSONL: {e}")
                janitor_stats.record_error()
                return  # Don't delete if append failed

        # Delete consolidated files
        deleted_count = 0
        for f in to_delete:
            try:
                f.unlink()
                deleted_count += 1
            except OSError:
                pass  # File may already be gone
        janitor_stats.record_delete(deleted_count)

        # Periodic progress
        stats = janitor_stats.get_stats()
        if stats["appended"] > 0 and stats["appended"] % 1000 < len(to_append):
            log(f"Janitor: {stats['appended']} appended, {stats['deleted']} deleted")

    # Main loop
    refresh_interval = 60  # Reload JSONL index every 60s for verification
    last_refresh = time.time()

    while not stop_event.is_set():
        # Periodically refresh JSONL index
        if time.time() - last_refresh > refresh_interval:
            jsonl_pairs = load_jsonl_pairs(jsonl_path)
            last_refresh = time.time()

        # Find JSON files older than min_age_seconds
        now = time.time()
        candidates = []

        try:
            for f in output_dir.glob("r*_c*.json"):
                try:
                    if now - f.stat().st_mtime >= min_age_seconds:
                        candidates.append(f)
                except OSError:
                    pass  # File may have been deleted
        except Exception:  # noqa: BLE001
            pass  # Glob may fail during heavy I/O

        if not candidates:
            time.sleep(1.0)
            continue

        # Process batch
        batch = candidates[:batch_size]
        process_batch(batch)

        # Brief pause between batches
        time.sleep(0.1)

    # Final sweep on shutdown - process all remaining files
    log("Janitor: final sweep starting")
    jsonl_pairs = load_jsonl_pairs(jsonl_path)  # Fresh reload
    sweep_count = 0
    while True:
        candidates = list(output_dir.glob("r*_c*.json"))
        if not candidates:
            break
        process_batch(candidates[:batch_size])
        sweep_count += 1
        if sweep_count % 100 == 0:
            stats = janitor_stats.get_stats()
            log(f"Janitor: sweep progress - {stats['appended']} appended, {len(candidates)} remaining")

    stats = janitor_stats.get_stats()
    log(f"Janitor: complete - {stats['appended']} appended, {stats['deleted']} deleted, {stats['errors']} errors")


# -----------------------------------------------------------------------------
# Atomic JSON file writer
# -----------------------------------------------------------------------------


def save_result_to_file(parsed: dict, output_dir: Path) -> bool:
    """
    Atomically write parsed result to JSON file.

    Returns True if saved, False if already exists.
    """
    custom_id = f"r{parsed['result_id']}_c{parsed['category_id']}"
    final_path = output_dir / f"{custom_id}.json"

    if final_path.exists():
        return False

    # Atomic write: temp file + rename
    temp_path = output_dir / f".{custom_id}.json.tmp"
    temp_path.write_text(json.dumps(parsed, indent=2))
    temp_path.rename(final_path)  # Atomic on POSIX
    return True


# -----------------------------------------------------------------------------
# Run statistics tracking
# -----------------------------------------------------------------------------


def get_hostname() -> str:
    """Get hostname for run tracking."""
    import socket
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def ensure_run_stats_table(db_path: Path) -> None:
    """Ensure run_stats table exists (for databases created before this feature)."""
    conn = open_db(db_path)
    cursor = conn.cursor()

    # Check if table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='run_stats'
    """)
    if cursor.fetchone() is None:
        log("Creating run_stats table (migration)")
        cursor.execute("""
            CREATE TABLE run_stats (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TIMESTAMP NOT NULL,
                finished_at TIMESTAMP,
                model TEXT NOT NULL,
                pairs_processed INTEGER DEFAULT 0,
                pairs_saved INTEGER DEFAULT 0,
                pairs_failed INTEGER DEFAULT 0,
                pairs_skipped INTEGER DEFAULT 0,
                processing_seconds REAL,
                janitor_imported INTEGER DEFAULT 0,
                janitor_seconds REAL,
                hostname TEXT,
                notes TEXT
            )
        """)
        conn.commit()

    conn.close()


def start_run(db_path: Path, model: str) -> int:
    """Create a new run record and return its ID."""
    conn = open_db(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO run_stats (started_at, model, hostname)
        VALUES (datetime('now'), ?, ?)
        """,
        (model, get_hostname()),
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
    janitor_imported: int = 0,
    janitor_seconds: float = 0.0,
    notes: str | None = None,
) -> None:
    """Update run record with final statistics."""
    conn = open_db(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE run_stats SET
            finished_at = datetime('now'),
            pairs_processed = ?,
            pairs_saved = ?,
            pairs_failed = ?,
            pairs_skipped = ?,
            processing_seconds = ?,
            janitor_imported = ?,
            janitor_seconds = ?,
            notes = ?
        WHERE run_id = ?
        """,
        (
            pairs_processed,
            pairs_saved,
            pairs_failed,
            pairs_skipped,
            processing_seconds,
            janitor_imported,
            janitor_seconds,
            notes,
            run_id,
        ),
    )
    conn.commit()
    conn.close()


def get_cumulative_stats(db_path: Path) -> dict:
    """Get cumulative processing statistics from all completed runs."""
    conn = open_db(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COUNT(*) as total_runs,
            COALESCE(SUM(pairs_processed), 0) as total_pairs_processed,
            COALESCE(SUM(pairs_saved), 0) as total_pairs_saved,
            COALESCE(SUM(pairs_failed), 0) as total_pairs_failed,
            COALESCE(SUM(processing_seconds), 0) as total_processing_seconds,
            COALESCE(SUM(janitor_imported), 0) as total_janitor_imported,
            COALESCE(SUM(janitor_seconds), 0) as total_janitor_seconds
        FROM run_stats
        WHERE finished_at IS NOT NULL
    """)
    row = cursor.fetchone()
    conn.close()

    return {
        "total_runs": row[0],
        "total_pairs_processed": row[1],
        "total_pairs_saved": row[2],
        "total_pairs_failed": row[3],
        "total_processing_seconds": row[4],
        "total_processing_hours": row[4] / 3600.0,
        "total_janitor_imported": row[5],
        "total_janitor_seconds": row[6],
    }


# -----------------------------------------------------------------------------
# Main orchestration
# -----------------------------------------------------------------------------


def count_pending_pairs(db_path: Path) -> int:
    """Count unprocessed pairs in database."""
    conn = open_db(db_path)
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT COUNT(*)
        FROM result r
        CROSS JOIN category c
        WHERE NOT EXISTS (
            SELECT 1 FROM result_category rc
            WHERE rc.result_id = r.result_id
            AND rc.category_id = c.category_id
        )
        AND LENGTH(r.content) <= {MAX_CONTENT_LENGTH}
    """)
    count = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return count


def process_corpus(
    db_path: Path,
    output_dir: Path,
    server_url: str,
    concurrency: int,
    model: str,
    limit: int | None,
    skip_sync: bool = False,
    enable_janitor: bool = False,
    janitor_batch_size: int = 50,
    janitor_min_age: float = 2.0,
) -> dict:
    """
    Main processing function using streaming architecture.

    Reader thread feeds work_queue, workers pull and process, write JSON files.
    """
    project_root = db_path.parent
    prompts_dir = project_root / "POC-prompts"
    # Use INPUT_DIR env var if set, otherwise default to markdown_corpus
    input_dir_env = os.environ.get("INPUT_DIR")
    input_dir = Path(input_dir_env) if input_dir_env else project_root / "input" / "markdown_corpus"
    schema_path = project_root / "schema.sql"

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Create database if needed
    if not skip_sync:
        create_database(db_path, schema_path)

    # Ensure run_stats table exists (migration for older databases)
    ensure_run_stats_table(db_path)

    # Step 2: Sync categories and documents
    if not skip_sync:
        console.print("[bold]Syncing categories and documents...[/bold]")
        conn = open_db(db_path)
        cursor = conn.cursor()

        try:
            categories = sync_categories(cursor, prompts_dir)
            console.print(f"[dim]  Synced {len(categories)} categories[/dim]")

            result_ids, skipped, split_count = sync_documents(cursor, input_dir)
            console.print(f"[dim]  Synced {len(result_ids)} documents[/dim]")
            if skipped:
                console.print(f"[dim]  Skipped {skipped} invalid files[/dim]")
            if split_count:
                console.print(f"[dim]  Split {split_count} large documents[/dim]")

            conn.commit()
        finally:
            conn.close()

    # Step 3: Load prompts
    console.print("[dim]Loading prompts...[/dim]")
    system_prompt = load_system_prompt(project_root)
    category_prompts = load_category_prompts(prompts_dir)
    console.print(f"[dim]Loaded {len(category_prompts)} category prompts[/dim]")

    # Step 3b: Start run tracking
    run_id = start_run(db_path, model)
    console.print(f"[dim]Started run #{run_id}[/dim]")

    # Step 4: Count pending work (for progress bar)
    # pending_in_db = pairs not yet in result_category table
    # json_files = pairs with JSON files in output dir (may or may not be in DB)
    # The reader thread skips pairs that have JSON files (belt-and-suspenders)
    pending_in_db = count_pending_pairs(db_path)
    json_files_in_output = get_completed_pairs(output_dir)

    # How many JSON files are for pairs that are still "pending" in DB?
    # These are files that exist but haven't been imported to SQLite yet
    # (This shouldn't happen if runner.sh Step 1 ran, but let's be explicit)

    # Actual pairs to process = pending_in_db minus those with JSON files
    # (reader will skip pairs with existing JSON files)
    pairs_with_json_not_in_db = len(json_files_in_output)  # Approximation
    actual_to_process = pending_in_db  # DB query already excludes imported ones

    console.print(f"[dim]Pending in DB (not in result_category): {pending_in_db}[/dim]")
    console.print(f"[dim]JSON files in output dir: {len(json_files_in_output)}[/dim]")

    if len(json_files_in_output) > 0:
        console.print(f"[yellow]Reader will skip {len(json_files_in_output)} pairs that already have JSON files[/yellow]")

    pairs_to_process = min(actual_to_process, limit) if limit else actual_to_process

    if pairs_to_process == 0:
        log("No pairs to process")
        # Still record the run (with 0 pairs)
        finish_run(db_path, run_id, 0, 0, 0, 0, 0.0, 0, 0.0, notes="No pairs to process")
        return {"run_id": run_id, "total": 0, "saved": 0, "skipped": 0, "failed": 0}

    log(f"Will process up to {pairs_to_process} pairs")

    # Step 5: Set up queues and events
    work_queue: queue.Queue = queue.Queue(maxsize=WORK_QUEUE_MAXSIZE)
    stop_event = threading.Event()

    # Set up metrics and stats
    metrics = Metrics()
    stats = {"saved": 0, "failed": 0, "skipped": 0}
    stats_lock = threading.Lock()

    # Set up janitor stats (even if janitor disabled, for cleaner code)
    janitor_stats = JanitorStats()

    # Step 6: Start reader thread
    reader = threading.Thread(
        target=reader_thread_fn,
        args=(
            str(db_path),
            output_dir,
            work_queue,
            stop_event,
            system_prompt,
            category_prompts,
            model,
            metrics,
            limit,
        ),
    )
    reader.start()

    # Step 7: Start metrics sampler
    sampler = threading.Thread(
        target=metrics_sampler_fn,
        args=(work_queue, stop_event, metrics),
    )
    sampler.start()

    # Step 7b: Start janitor thread if enabled
    janitor = None
    if enable_janitor:
        janitor = threading.Thread(
            target=janitor_thread_fn,
            args=(
                str(db_path),
                output_dir,
                stop_event,
                janitor_stats,
                janitor_batch_size,
                janitor_min_age,
            ),
        )
        janitor.start()
        log("Janitor thread started")

    # Step 8: Process with thread pool (streaming pattern from Elaboration07)
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
            f"Processing ({concurrency} workers)",
            total=pairs_to_process,
            rate=0.0,
        )

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {}  # future -> (custom_id, body, retry_count)
            items_submitted = 0
            reader_done = False
            max_retries = 3
            retry_count_total = 0

            while not reader_done or futures:
                # Submit new work if available (keep 2x concurrency in flight)
                while not reader_done and len(futures) < concurrency * 2:
                    try:
                        item = work_queue.get(timeout=0.1)
                        if item is None:
                            reader_done = True
                            break
                        custom_id, body = item
                        future = executor.submit(do_request, custom_id, body, server_url)
                        futures[future] = (custom_id, body, 0)  # retry_count = 0
                        items_submitted += 1
                    except queue.Empty:
                        break

                # Collect completed futures
                done_futures = [f for f in futures if f.done()]
                for future in done_futures:
                    custom_id, body, retry_count = futures.pop(future)
                    try:
                        result = future.result()
                        metrics.record_request_time(result["elapsed_sec"])

                        # Parse and save result
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
                            # Retry logic for failures
                            if retry_count < max_retries:
                                retry_count += 1
                                retry_count_total += 1
                                if retry_count_total <= 10:
                                    console.print(f"[yellow][RETRY {retry_count}/{max_retries}] {custom_id}: {failure_reason[:80]}...[/yellow]")
                                elif retry_count_total == 11:
                                    console.print("[yellow][RETRY] ... (suppressing further retry messages)[/yellow]")
                                # Re-submit with incremented retry count
                                new_future = executor.submit(do_request, custom_id, body, server_url)
                                futures[new_future] = (custom_id, body, retry_count)
                            else:
                                # All retries exhausted
                                with stats_lock:
                                    stats["failed"] += 1
                                    if stats["failed"] <= 5:
                                        console.print(f"[red][FAIL after {max_retries} retries] {custom_id}: {failure_reason}[/red]")
                                    elif stats["failed"] == 6:
                                        console.print("[red][FAIL] ... (suppressing further failure messages)[/red]")
                                completed_count += 1

                        # Update progress
                        elapsed = time.time() - overall_start
                        rate = completed_count / elapsed if elapsed > 0 else 0
                        progress.update(task, completed=completed_count, rate=rate)
                    except Exception as e:
                        console.print(f"[red][ERROR] Worker exception: {e}[/red]")
                        completed_count += 1
                        progress.update(task, completed=completed_count)

                time.sleep(0.01)  # Small sleep to prevent busy-wait

    # Wait for reader (should be quick since it's already done)
    reader.join(timeout=60)
    if reader.is_alive():
        log("WARNING: Reader thread did not finish in 60s, continuing anyway")

    # Stop sampler and janitor
    stop_event.set()
    sampler.join(timeout=10)

    if janitor is not None:
        # Janitor may take a while to import all files - wait up to 30 min
        log("Waiting for janitor to complete import...")
        janitor.join(timeout=1800)
        if janitor.is_alive():
            log("WARNING: Janitor thread did not finish in 30 min, continuing anyway")
        else:
            log("Janitor thread finished")

    # Final statistics
    total_time = time.time() - overall_start
    throughput = completed_count / total_time if total_time > 0 else 0

    # Calculate actual processing time (sum of vLLM request times, not wall clock)
    processing_seconds = sum(metrics.request_times) if metrics.request_times else 0.0
    janitor_seconds = 0.0
    janitor_appended = 0
    if enable_janitor:
        j_stats = janitor_stats.get_stats()
        janitor_appended = j_stats["appended"]

    # Record run completion
    finish_run(
        db_path,
        run_id,
        pairs_processed=completed_count,
        pairs_saved=stats["saved"],
        pairs_failed=stats["failed"],
        pairs_skipped=stats["skipped"],
        processing_seconds=processing_seconds,
        janitor_imported=janitor_appended,
        janitor_seconds=janitor_seconds,
    )

    # Get cumulative stats across all runs
    cumulative = get_cumulative_stats(db_path)

    table = Table(title="Processing Complete", show_header=False, box=None)
    table.add_column("Metric", style="bold")
    table.add_column("Value", style="cyan")
    table.add_row("Total time (wall)", f"{total_time:.1f}s")
    table.add_row("Processing time (vLLM)", f"{processing_seconds:.1f}s")
    table.add_row("Processed", str(completed_count))
    table.add_row("Throughput", f"{throughput:.2f} req/s")
    table.add_row("Saved", str(stats["saved"]))
    table.add_row("Skipped", str(stats["skipped"]))
    table.add_row("Failed", str(stats["failed"]))
    table.add_row("Output dir", str(output_dir))

    # Add janitor stats if enabled
    if enable_janitor:
        table.add_row("", "")  # Spacer row
        table.add_row("[bold]Janitor[/bold]", "")
        table.add_row("  Appended to JSONL", str(j_stats["appended"]))
        table.add_row("  JSON files deleted", str(j_stats["deleted"]))
        table.add_row("  Errors", str(j_stats["errors"]))

    # Add cumulative stats
    table.add_row("", "")  # Spacer row
    table.add_row("[bold]Cumulative (all runs)[/bold]", "")
    table.add_row("  Total runs", str(cumulative["total_runs"]))
    table.add_row("  Total pairs processed", str(cumulative["total_pairs_processed"]))
    table.add_row("  Total pairs saved", str(cumulative["total_pairs_saved"]))
    table.add_row("  Total processing time", f"{cumulative['total_processing_hours']:.2f}h")

    console.print()
    console.print(Panel(table, border_style="green"))

    result = {
        "run_id": run_id,
        "total_time_sec": total_time,
        "processing_seconds": processing_seconds,
        "processed": completed_count,
        "throughput": throughput,
        "saved": stats["saved"],
        "skipped": stats["skipped"],
        "failed": stats["failed"],
        "cumulative": cumulative,
    }

    if enable_janitor:
        result["janitor"] = janitor_stats.get_stats()

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Unified Corpus Processor: Map-reduce with JSON file output"
    )
    parser.add_argument(
        "--db",
        required=True,
        help="Path to corpus.db",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write JSON result files",
    )
    parser.add_argument(
        "--server-url",
        default="http://localhost:8000",
        help="vLLM server URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=128,
        help="Number of concurrent workers (default: 128)",
    )
    parser.add_argument(
        "--model",
        default="openai/gpt-oss-20b",
        help="Model name (default: openai/gpt-oss-20b)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of pairs to process (default: all)",
    )
    parser.add_argument(
        "--skip-sync",
        action="store_true",
        help="Skip category/document sync (faster startup if already synced)",
    )
    parser.add_argument(
        "--no-janitor",
        action="store_true",
        help="Disable janitor thread (by default, janitor imports JSON files to DB and deletes them)",
    )
    parser.add_argument(
        "--janitor-batch-size",
        type=int,
        default=50,
        help="Number of files to import per janitor batch (default: 50)",
    )
    parser.add_argument(
        "--janitor-min-age",
        type=float,
        default=2.0,
        help="Minimum file age in seconds before janitor processes it (default: 2.0)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress per-file output during sync, show only summary",
    )
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    output_dir = Path(args.output_dir).resolve()

    # Show config
    config_table = Table(title="Configuration", show_header=False, box=None)
    config_table.add_column("Setting", style="bold")
    config_table.add_column("Value", style="cyan")
    config_table.add_row("Database", str(db_path))
    config_table.add_row("Output dir", str(output_dir))
    config_table.add_row("Server", args.server_url)
    config_table.add_row("Concurrency", str(args.concurrency))
    config_table.add_row("Model", args.model)
    config_table.add_row("Limit", str(args.limit) if args.limit else "unlimited")
    config_table.add_row("Skip sync", "yes" if args.skip_sync else "no")
    enable_janitor = not args.no_janitor
    config_table.add_row("Janitor", "disabled" if args.no_janitor else "enabled")
    if enable_janitor:
        config_table.add_row("  Batch size", str(args.janitor_batch_size))
        config_table.add_row("  Min age", f"{args.janitor_min_age}s")
    console.print(Panel(config_table, border_style="blue"))
    console.print()

    # Check server health
    server_url = args.server_url.rstrip("/")
    try:
        req = urllib.request.Request(f"{server_url}/health", method="GET")
        with urllib.request.urlopen(req, timeout=5):
            pass
        console.print(f"[green]✓ vLLM server is running at {server_url}[/green]")
    except Exception as e:
        console.print(f"[red]✗ Cannot reach vLLM server at {server_url}: {e}[/red]")
        console.print("[yellow]Start the server with: bash start_server_hpc.sh[/yellow]")
        return 1

    console.print()

    process_corpus(
        db_path,
        output_dir,
        args.server_url,
        args.concurrency,
        args.model,
        args.limit,
        args.skip_sync,
        enable_janitor,
        args.janitor_batch_size,
        args.janitor_min_age,
    )

    return 0


if __name__ == "__main__":
    exit(main())
