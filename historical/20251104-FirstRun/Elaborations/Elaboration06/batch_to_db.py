"""
Transform vLLM batch results into database inserts.

This script:
1. Reads batch results JSONL
2. Parses JSON from each response
3. Writes to SQLite database using the schema from schema.sql

Database schema requirements:
- result(result_id, content, filepath)
- result_category(result_id, category_id, match, reasoning_trace)
- result_category_blockquote(result_id, category_id, blockquote)
"""

import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Tuple


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


def parse_custom_id(custom_id: str) -> Tuple[int, int]:
    """
    Parse custom_id to extract result_id and category_id.

    Format: "r{result_id}_c{category_id}"
    Example: "r42_c7" -> (42, 7)
    Returns: (result_id, category_id)
    """
    if not custom_id.startswith("r") or "_c" not in custom_id:
        raise ValueError(f"Invalid custom_id format: {custom_id}")

    parts = custom_id.split("_c")
    result_id = int(parts[0][1:])  # Remove "r" prefix and convert to int
    category_id = int(parts[1])

    return result_id, category_id


def process_batch_result(result: dict) -> Dict | None:
    """
    Process a single batch result into database-ready format.

    Returns:
        Dict with keys: result_id, category_id, match, reasoning_trace, blockquotes
        or None if parsing failed
    """
    custom_id = result["custom_id"]
    response = result.get("response", {})
    error = result.get("error")

    if error:
        print(f"[WARN] Skipping {custom_id}: {error}")
        return None

    # Extract response body
    body = response.get("body", {})
    choices = body.get("choices", [])

    if not choices:
        print(f"[WARN] Skipping {custom_id}: No choices in response")
        return None

    # Get message content
    message = choices[0].get("message", {})
    content = message.get("content", "")

    if not content:
        print(f"[WARN] Skipping {custom_id}: Empty response content")
        return None

    # Parse custom_id
    result_id, category_id = parse_custom_id(custom_id)

    # Extract JSON
    category_result = extract_json_from_text(content)

    if category_result is None:
        print(f"[WARN] Skipping {custom_id}: Failed to parse JSON")
        return None

    # Extract reasoning
    reasoning = extract_reasoning(content)

    # Validate structure
    if "match" not in category_result or "blockquotes" not in category_result:
        print(f"[WARN] Skipping {custom_id}: Invalid JSON structure")
        return None

    return {
        "result_id": result_id,
        "category_id": category_id,
        "match": category_result["match"],
        "reasoning_trace": reasoning,
        "blockquotes": category_result.get("blockquotes", [])
    }


def insert_to_database(db_path: Path, parsed_results: List[Dict]):
    """
    Insert parsed results into SQLite database.

    Args:
        db_path: Path to SQLite database
        parsed_results: List of parsed result dicts

    Note:
        - result table is already populated by generate_batch_full.py
        - This only inserts result_category and blockquotes
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Group by result_id for progress reporting
        results_by_doc = {}
        for r in parsed_results:
            result_id = r["result_id"]
            if result_id not in results_by_doc:
                results_by_doc[result_id] = []
            results_by_doc[result_id].append(r)

        # Insert result_category and blockquotes
        total_inserted = 0
        for r in parsed_results:
            # Insert result_category
            cursor.execute("""
                INSERT OR REPLACE INTO result_category
                (result_id, category_id, match, reasoning_trace)
                VALUES (?, ?, ?, ?)
            """, (r["result_id"], r["category_id"], r["match"], r["reasoning_trace"]))

            # Insert blockquotes
            for blockquote in r["blockquotes"]:
                cursor.execute("""
                    INSERT INTO result_category_blockquote
                    (result_id, category_id, blockquote)
                    VALUES (?, ?, ?)
                """, (r["result_id"], r["category_id"], blockquote))

            total_inserted += 1

        conn.commit()

        print(f"✓ Inserted {total_inserted} category results")
        print(f"  Documents affected: {len(results_by_doc)}")
        print(f"  Total blockquotes: {sum(len(r['blockquotes']) for r in parsed_results)}")

    except Exception as e:
        conn.rollback()
        print(f"✗ Database error: {e}")
        raise
    finally:
        conn.close()


def main():
    """Process batch results and insert into database."""
    if len(sys.argv) < 2:
        print("Usage: python batch_to_db.py <results.jsonl> [db_path]")
        print("\nExample:")
        print("  python batch_to_db.py results.jsonl")
        print("  python batch_to_db.py results.jsonl ../../corpus.db")
        sys.exit(1)

    results_file = Path(sys.argv[1])
    db_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("../../corpus.db")

    if not results_file.exists():
        print(f"Error: {results_file} not found")
        sys.exit(1)

    if not db_path.exists():
        print(f"Error: Database {db_path} not found")
        print("Please run generate_batch_full.py first to create database")
        sys.exit(1)

    # Parse all results
    parsed_results = []
    failed_results = []

    print(f"Parsing batch results from {results_file}...")

    with open(results_file) as f:
        for line_num, line in enumerate(f, 1):
            result = json.loads(line)
            parsed = process_batch_result(result)

            if parsed:
                parsed_results.append(parsed)
            else:
                failed_results.append((line_num, result.get("custom_id", "unknown")))

    if not parsed_results:
        print("✗ No valid results to insert")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"Parsing Summary")
    print(f"{'='*60}")
    print(f"Total lines: {line_num}")
    print(f"Successful: {len(parsed_results)} ({len(parsed_results)/line_num*100:.1f}%)")
    print(f"Failed: {len(failed_results)} ({len(failed_results)/line_num*100:.1f}%)")

    if failed_results:
        print(f"\nFailed custom_ids:")
        for line_num, custom_id in failed_results[:10]:  # Show first 10
            print(f"  Line {line_num}: {custom_id}")
        if len(failed_results) > 10:
            print(f"  ... and {len(failed_results) - 10} more")

    # Insert to database
    print(f"\n{'='*60}")
    print(f"Database Insertion")
    print(f"{'='*60}")

    insert_to_database(db_path, parsed_results)

    print(f"\n✓ Database updated: {db_path}")


if __name__ == "__main__":
    main()
