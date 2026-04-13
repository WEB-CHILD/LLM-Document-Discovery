#!/usr/bin/env python
"""
DEPRECATED: Use unified_processor.py instead.

This script read from a batch.jsonl file and sent requests to vLLM server.
The new unified_processor.py streams directly from DB to vLLM server to DB,
eliminating the need for this intermediate file-based approach.

Kept for reference only.

---

vLLM server client with direct database insertion.

Sends concurrent HTTP requests to a running vLLM server and writes results
directly to SQLite database. Supports resumability by skipping already-completed
document-category pairs.

Usage:
    uv run python server_client.py --batch-file batch.jsonl --db corpus.db --concurrency 8
"""

import argparse
import json
import queue
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from typing import Any


def log(msg: str) -> None:
    """Log message with timestamp."""
    now = time.strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


# -----------------------------------------------------------------------------
# Response parsing (from batch_to_db.py)
# -----------------------------------------------------------------------------


def extract_json_from_text(text: str) -> dict | None:
    """Extract JSON from response text."""
    if "{" not in text or "}" not in text:
        return None

    json_start = text.rfind("{")
    json_end = text.rfind("}") + 1

    if json_start >= json_end:
        return None

    try:
        json_str = text[json_start:json_end]
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


def extract_reasoning(text: str) -> str:
    """Extract reasoning text before JSON."""
    json_start = text.rfind("{")
    if json_start == -1:
        return ""
    return text[:json_start].strip()


def parse_custom_id(custom_id: str) -> tuple[int, int]:
    """
    Parse custom_id to extract result_id and category_id.

    Format: "r{result_id}_c{category_id}"
    Example: "r42_c7" -> (42, 7)
    """
    if not custom_id.startswith("r") or "_c" not in custom_id:
        raise ValueError(f"Invalid custom_id format: {custom_id}")

    parts = custom_id.split("_c")
    result_id = int(parts[0][1:])
    category_id = int(parts[1])

    return result_id, category_id


def parse_response(custom_id: str, response: dict | None, error: str | None) -> dict | None:
    """
    Parse a server response into database-ready format.

    Returns dict with keys: result_id, category_id, match, reasoning_trace, blockquotes
    or None if parsing failed.
    """
    if error or response is None:
        log(f"[WARN] Skipping {custom_id}: {error}")
        return None

    # Server API returns OpenAI format directly (no 'body' wrapper)
    choices = response.get("choices", [])

    if not choices:
        log(f"[WARN] Skipping {custom_id}: No choices in response")
        return None

    message = choices[0].get("message", {})
    content = message.get("content", "")

    if not content:
        log(f"[WARN] Skipping {custom_id}: Empty response content")
        return None

    result_id, category_id = parse_custom_id(custom_id)

    category_result = extract_json_from_text(content)
    if category_result is None:
        log(f"[WARN] Skipping {custom_id}: Failed to parse JSON from response")
        return None

    if "match" not in category_result or "blockquotes" not in category_result:
        log(f"[WARN] Skipping {custom_id}: Invalid JSON structure (missing match/blockquotes)")
        return None

    reasoning = extract_reasoning(content)

    return {
        "result_id": result_id,
        "category_id": category_id,
        "match": category_result["match"],
        "reasoning_trace": reasoning,
        "blockquotes": category_result.get("blockquotes", []),
    }


# -----------------------------------------------------------------------------
# Database operations
# -----------------------------------------------------------------------------


def load_completed_pairs(db_path: str) -> set[str]:
    """Load already-completed document-category pairs from database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    completed = set()
    cursor.execute("SELECT result_id, category_id FROM result_category")
    for row in cursor:
        completed.add(f"r{row[0]}_c{row[1]}")

    conn.close()
    log(f"Loaded {len(completed)} completed pairs from database")
    return completed


def db_writer_thread(
    db_path: str,
    db_queue: queue.Queue,
    stop_event: threading.Event,
    stats: dict,
) -> None:
    """
    Dedicated thread for database writes.

    Consumes parsed results from queue and inserts into database.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    while not stop_event.is_set() or not db_queue.empty():
        try:
            item = db_queue.get(timeout=0.1)
        except queue.Empty:
            continue

        custom_id = item["custom_id"]
        response = item["response"]
        error = item["error"]

        parsed = parse_response(custom_id, response, error)

        if parsed is None:
            stats["failed"] += 1
            db_queue.task_done()
            continue

        try:
            # Insert result_category
            cursor.execute(
                """
                INSERT OR REPLACE INTO result_category
                (result_id, category_id, match, reasoning_trace)
                VALUES (?, ?, ?, ?)
                """,
                (
                    parsed["result_id"],
                    parsed["category_id"],
                    parsed["match"],
                    parsed["reasoning_trace"],
                ),
            )

            # Delete existing blockquotes (for idempotency)
            cursor.execute(
                """
                DELETE FROM result_category_blockquote
                WHERE result_id = ? AND category_id = ?
                """,
                (parsed["result_id"], parsed["category_id"]),
            )

            # Insert blockquotes
            for blockquote in parsed["blockquotes"]:
                cursor.execute(
                    """
                    INSERT INTO result_category_blockquote
                    (result_id, category_id, blockquote)
                    VALUES (?, ?, ?)
                    """,
                    (parsed["result_id"], parsed["category_id"], blockquote),
                )

            conn.commit()
            stats["inserted"] += 1
            stats["blockquotes"] += len(parsed["blockquotes"])

        except sqlite3.Error as e:
            log(f"[ERROR] Database error for {custom_id}: {e}")
            stats["failed"] += 1

        db_queue.task_done()

    conn.close()


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
        with urllib.request.urlopen(req) as resp:
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
# Main
# -----------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="vLLM server client with direct database insertion"
    )
    parser.add_argument(
        "--batch-file",
        default="batch.jsonl",
        help="Path to batch.jsonl (default: batch.jsonl)",
    )
    parser.add_argument(
        "--db",
        required=True,
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--num-items",
        type=int,
        default=0,
        help="Limit number of items to process (0 = all)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Number of concurrent requests (default: 8)",
    )
    parser.add_argument(
        "--server-url",
        default="http://localhost:8000",
        help="vLLM server URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Process all items (don't skip completed pairs)",
    )
    args = parser.parse_args()

    # Load completed pairs for resumability
    if args.no_resume:
        completed = set()
    else:
        completed = load_completed_pairs(args.db)

    # Load batch file
    log(f"Loading batch file: {args.batch_file}")
    items: list[tuple[str, dict[str, Any]]] = []

    with open(args.batch_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            custom_id = obj["custom_id"]

            # Skip completed pairs
            if custom_id in completed:
                continue

            body = obj["body"]
            items.append((custom_id, body))

            if args.num_items > 0 and len(items) >= args.num_items:
                break

    if not items:
        log("No items to process (all completed or empty batch)")
        return

    log(f"Items to process: {len(items)} (skipped {len(completed)} completed)")
    log(f"Concurrency: {args.concurrency}")

    # Set up database writer thread
    db_queue: queue.Queue = queue.Queue()
    stop_event = threading.Event()
    stats = {"inserted": 0, "failed": 0, "blockquotes": 0}

    writer = threading.Thread(
        target=db_writer_thread,
        args=(args.db, db_queue, stop_event, stats),
    )
    writer.start()

    # Process requests with thread pool
    from concurrent.futures import ThreadPoolExecutor, as_completed

    overall_start = time.time()
    completed_count = 0

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(do_request, custom_id, body, args.server_url): custom_id
            for custom_id, body in items
        }

        for future in as_completed(futures):
            result = future.result()
            db_queue.put(result)
            completed_count += 1

            if completed_count % 100 == 0 or completed_count == len(items):
                elapsed = time.time() - overall_start
                rate = completed_count / elapsed if elapsed > 0 else 0
                log(
                    f"Progress: {completed_count}/{len(items)} "
                    f"({rate:.2f} req/s, inserted={stats['inserted']}, failed={stats['failed']})"
                )

    # Wait for all database writes to complete
    db_queue.join()
    stop_event.set()
    writer.join()

    # Final statistics
    total_time = time.time() - overall_start

    log("")
    log("=" * 60)
    log("Processing Complete")
    log("=" * 60)
    log(f"Total time: {total_time:.1f}s")
    log(f"Requests: {len(items)}")
    log(f"Throughput: {len(items) / total_time:.2f} req/s")
    log(f"Inserted: {stats['inserted']}")
    log(f"Failed: {stats['failed']}")
    log(f"Blockquotes: {stats['blockquotes']}")
    log(f"Database: {args.db}")


if __name__ == "__main__":
    main()
