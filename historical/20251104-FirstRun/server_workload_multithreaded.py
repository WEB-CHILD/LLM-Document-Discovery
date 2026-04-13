#!/usr/bin/env python
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple
import urllib.request
import urllib.error


def log(msg: str) -> None:
    now = time.strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def do_request(
    idx: int,
    custom_id: str,
    body: Dict[str, Any],
    server_url: str,
) -> Dict[str, Any]:
    url = server_url.rstrip("/") + "/v1/chat/completions"
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    start = time.time()
    ok = True
    error: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    resp_json: Optional[Dict[str, Any]] = None

    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
        resp_json = json.loads(raw.decode("utf-8"))
        usage = resp_json.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
    except urllib.error.HTTPError as e:
        ok = False
        error = f"HTTPError {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        ok = False
        error = f"URLError: {e.reason}"
    except Exception as e:  # noqa: BLE001
        ok = False
        error = f"Exception: {e!r}"

    end = time.time()
    elapsed = end - start

    return {
        "index": idx,
        "custom_id": custom_id,
        "elapsed_sec": elapsed,
        "ok": ok,
        "error": error,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "response": resp_json if ok else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multithreaded vLLM server workload driver over batch.jsonl"
    )
    parser.add_argument(
        "--batch-file",
        default="batch.jsonl",
        help="Path to batch.jsonl with {custom_id, body} lines (default: batch.jsonl)",
    )
    parser.add_argument(
        "--num-items",
        type=int,
        default=21000,
        help="Number of items to process from batch.jsonl (default: 21000)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Number of concurrent requests to send (default: 8)",
    )
    parser.add_argument(
        "--server-url",
        default="http://localhost:8000",
        help="Base URL of vLLM server (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--output-jsonl",
        required=True,
        help="Where to write JSONL with full responses and timing",
    )
    parser.add_argument(
        "--stats-csv",
        required=True,
        help="Where to write CSV with per-request timing stats",
    )
    args = parser.parse_args()

    batch_path: str = args.batch_file
    num_items: int = args.num_items
    concurrency: int = args.concurrency
    server_url: str = args.server_url

    log(f"Loading up to {num_items} items from {batch_path}...")
    items: List[Tuple[int, str, Dict[str, Any]]] = []
    with open(batch_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if idx >= num_items:
                break
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            custom_id = obj.get("custom_id", f"idx_{idx}")
            body = obj["body"]
            items.append((idx, custom_id, body))

    actual_n = len(items)
    if actual_n == 0:
        log("No items loaded; exiting.")
        return

    log(f"Loaded {actual_n} items. Concurrency: {concurrency}")

    import csv

    jsonl_f = open(args.output_jsonl, "w", encoding="utf-8")
    csv_f = open(args.stats_csv, "w", encoding="utf-8", newline="")
    csv_writer = csv.writer(csv_f)
    csv_writer.writerow(
        ["index", "custom_id", "elapsed_sec", "ok", "error", "prompt_tokens", "completion_tokens"]
    )

    overall_start = time.time()

    num_ok = 0
    num_err = 0
    sum_elapsed = 0.0
    min_elapsed = float("inf")
    max_elapsed = 0.0

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = []
        for idx, custom_id, body in items:
            futures.append(executor.submit(do_request, idx, custom_id, body, server_url))

        for i, fut in enumerate(as_completed(futures), start=1):
            result = fut.result()
            json.dump(result, jsonl_f)
            jsonl_f.write("\n")

            csv_writer.writerow(
                [
                    result["index"],
                    result["custom_id"],
                    f"{result['elapsed_sec']:.9f}",
                    "1" if result["ok"] else "0",
                    result["error"] or "",
                    result["prompt_tokens"] if result["prompt_tokens"] is not None else "",
                    result["completion_tokens"] if result["completion_tokens"] is not None else "",
                ]
            )

            elapsed = result["elapsed_sec"]
            sum_elapsed += elapsed
            if elapsed < min_elapsed:
                min_elapsed = elapsed
            if elapsed > max_elapsed:
                max_elapsed = elapsed
            if result["ok"]:
                num_ok += 1
            else:
                num_err += 1

            if i % 100 == 0 or i == actual_n:
                log(
                    f"Completed {i}/{actual_n} requests "
                    f"(ok={num_ok}, err={num_err}); last elapsed={elapsed:.3f}s"
                )

    overall_end = time.time()
    total_time = overall_end - overall_start
    mean_elapsed = sum_elapsed / actual_n

    jsonl_f.close()
    csv_f.close()

    log("")
    log("============================================================")
    log("Multithreaded Server Workload Complete")
    log("============================================================")
    log(f"Total wall-clock time: {total_time:.3f}s")
    log(f"Items processed: {actual_n}")
    log(f"Average time per item (mean of per-request): {mean_elapsed:.3f}s")
    log(f"Min/Max per-request latency: {min_elapsed:.3f}s / {max_elapsed:.3f}s")
    log(f"Throughput (items/sec): {actual_n / total_time:.3f}")
    log(f"Successes: {num_ok}, Errors: {num_err}")
    log(f"JSONL results: {args.output_jsonl}")
    log(f"CSV stats: {args.stats_csv}")


if __name__ == "__main__":
    main()
