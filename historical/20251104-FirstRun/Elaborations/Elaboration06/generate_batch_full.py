"""
Generate full corpus batch file for vLLM processing.

This script:
1. Syncs category table with POC-prompts/ directory (SHA-256 hash)
2. Syncs result table with input/ directory (SHA-256 hash)
3. Generates batch JSONL using SQL WHERE NOT EXISTS for missing pairs
4. Supports resumability - only generates requests for unprocessed pairs

Usage:
    python generate_batch_full.py [--limit N] [--output batch.jsonl] [--db ../../corpus.db]
"""

import argparse
import hashlib
import json
import sqlite3
import sys
import yaml
from pathlib import Path
from typing import Dict, List, Tuple


def sha256_file(filepath: Path) -> str:
    """Calculate SHA-256 hash of file contents."""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def create_database(db_path: Path, schema_path: Path):
    """Create database from schema if it doesn't exist."""
    if db_path.exists():
        return

    print(f"Creating database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    with open(schema_path) as f:
        schema_sql = f.read()

    cursor.executescript(schema_sql)
    conn.commit()
    conn.close()

    print(f"✓ Database created: {db_path}")


def sync_categories(cursor: sqlite3.Cursor, prompts_dir: Path) -> Dict[int, Dict]:
    """
    Sync category table with POC-prompts/ directory.

    Returns:
        Dict mapping category_id to category metadata
    """
    category_files = sorted(prompts_dir.glob("*.yaml"))

    if not category_files:
        raise ValueError(f"No YAML files found in {prompts_dir}")

    categories = {}

    for cat_file in category_files:
        # Calculate hash of entire file content
        prompt_hash = sha256_file(cat_file)

        # Parse YAML for metadata
        with open(cat_file) as f:
            data = yaml.safe_load(f)

        category_name = data.get("name", "")
        category_description = data.get("description", "")

        # Check if this exact category exists (filename + hash)
        cursor.execute("""
            SELECT category_id, category_name, category_description
            FROM category
            WHERE category_filename = ? AND prompt_sha256 = ?
        """, (cat_file.name, prompt_hash))

        row = cursor.fetchone()

        if row:
            # Category already exists
            category_id = row[0]
            categories[category_id] = {
                "filename": cat_file.name,
                "name": row[1],
                "description": row[2],
                "prompt": data.get("prompt", ""),
                "hash": prompt_hash
            }
        else:
            # New category (new file or changed prompt)
            cursor.execute("""
                INSERT INTO category (category_filename, category_name,
                                    category_description, prompt_sha256)
                VALUES (?, ?, ?, ?)
            """, (cat_file.name, category_name, category_description, prompt_hash))

            category_id = cursor.lastrowid
            categories[category_id] = {
                "filename": cat_file.name,
                "name": category_name,
                "description": category_description,
                "prompt": data.get("prompt", ""),
                "hash": prompt_hash
            }

            print(f"  + Added category {category_id}: {cat_file.name} (hash: {prompt_hash[:8]}...)")

    return categories


def sync_documents(cursor: sqlite3.Cursor, input_dir: Path, limit: int = None) -> List[int]:
    """
    Sync result table with input/ directory.

    Args:
        cursor: Database cursor
        input_dir: Directory containing markdown files
        limit: Optional limit on number of documents to process

    Returns:
        List of result_ids that were synced
    """
    md_files = sorted(input_dir.glob("*.md"))

    if not md_files:
        raise ValueError(f"No .md files found in {input_dir}")

    if limit:
        md_files = md_files[:limit]

    result_ids = []

    for md_file in md_files:
        # Calculate hash of file content
        content_hash = sha256_file(md_file)

        # Check if this exact document exists (filepath + hash)
        cursor.execute("""
            SELECT result_id FROM result
            WHERE filepath = ? AND content_sha256 = ?
        """, (str(md_file), content_hash))

        row = cursor.fetchone()

        if row:
            # Document already exists with same content
            result_ids.append(row[0])
        else:
            # New document or content changed
            # Read content
            with open(md_file) as f:
                content = f.read()

            # Insert new result
            cursor.execute("""
                INSERT INTO result (filepath, content, content_sha256)
                VALUES (?, ?, ?)
            """, (str(md_file), content, content_hash))

            result_id = cursor.lastrowid
            result_ids.append(result_id)

            print(f"  + Added result {result_id}: {md_file.name} (hash: {content_hash[:8]}...)")

    return result_ids


def load_system_prompt(project_root: Path) -> str:
    """Load universal system prompt."""
    with open(project_root / "system_prompt.txt") as f:
        return f.read()


def generate_batch_jsonl(
    cursor: sqlite3.Cursor,
    output_file: Path,
    system_prompt: str,
    model: str = "openai/gpt-oss-20b"
):
    """
    Generate batch JSONL using SQL WHERE NOT EXISTS.

    Only generates requests for (result, category) pairs that haven't been processed.
    """
    # Find all missing (result_id, category_id) pairs
    cursor.execute("""
        SELECT r.result_id, r.filepath, r.content,
               c.category_id, c.category_filename, c.category_name
        FROM result r
        CROSS JOIN category c
        WHERE NOT EXISTS (
            SELECT 1 FROM result_category rc
            WHERE rc.result_id = r.result_id
            AND rc.category_id = c.category_id
        )
        ORDER BY r.result_id, c.category_id
    """)

    missing_pairs = cursor.fetchall()

    if not missing_pairs:
        print("No missing pairs to process")
        return 0

    print(f"\nGenerating batch for {len(missing_pairs)} missing pairs...")

    # Load category prompts (we need the full YAML)
    project_root = Path(__file__).parent / ".." / ".."
    project_root = project_root.resolve()
    prompts_dir = project_root / "POC-prompts"

    category_prompts = {}
    for yaml_file in prompts_dir.glob("*.yaml"):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        category_prompts[yaml_file.name] = data.get("prompt", "")

    # Generate batch requests
    requests_written = 0

    with open(output_file, "w") as f:
        for result_id, filepath, content, category_id, category_filename, category_name in missing_pairs:
            # Get category prompt
            category_prompt = category_prompts.get(category_filename, "")

            if not category_prompt:
                print(f"[WARN] No prompt found for {category_filename}, skipping")
                continue

            # Custom ID format: r{result_id}_c{category_id}
            custom_id = f"r{result_id}_c{category_id}"

            # Construct messages
            system_message = {
                "role": "system",
                "content": system_prompt
            }

            user_message = {
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
}}"""
            }

            # Create batch request
            request = {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": [system_message, user_message],
                    "temperature": 0.0,
                    "max_tokens": 128000,
                }
            }

            f.write(json.dumps(request) + "\n")
            requests_written += 1

    return requests_written


def main():
    """Generate full corpus batch file."""
    parser = argparse.ArgumentParser(description="Generate batch file for full corpus processing")
    parser.add_argument("--limit", type=int, help="Limit number of documents to process")
    parser.add_argument("--output", default="batch.jsonl", help="Output batch file")
    parser.add_argument("--db", default="../../corpus.db", help="Database path")
    parser.add_argument("--model", default="openai/gpt-oss-20b", help="Model name")

    args = parser.parse_args()

    # Setup paths
    script_dir = Path(__file__).parent
    project_root = script_dir / ".." / ".."
    project_root = project_root.resolve()

    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = script_dir / db_path

    output_file = Path(args.output)
    if not output_file.is_absolute():
        output_file = script_dir / output_file

    prompts_dir = project_root / "POC-prompts"
    input_dir = project_root / "input"
    schema_path = project_root / "schema.sql"

    # Validate paths
    if not prompts_dir.exists():
        print(f"Error: POC-prompts directory not found: {prompts_dir}")
        sys.exit(1)

    if not input_dir.exists():
        print(f"Error: input directory not found: {input_dir}")
        sys.exit(1)

    if not schema_path.exists():
        print(f"Error: schema.sql not found: {schema_path}")
        sys.exit(1)

    # Create database if needed
    create_database(db_path, schema_path)

    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("\n" + "="*60)
        print("Step 1: Sync Categories")
        print("="*60)

        categories = sync_categories(cursor, prompts_dir)
        print(f"✓ Synced {len(categories)} categories")

        print("\n" + "="*60)
        print("Step 2: Sync Documents")
        print("="*60)

        result_ids = sync_documents(cursor, input_dir, args.limit)
        print(f"✓ Synced {len(result_ids)} documents")

        # Commit syncs
        conn.commit()

        print("\n" + "="*60)
        print("Step 3: Generate Batch JSONL")
        print("="*60)

        system_prompt = load_system_prompt(project_root)

        requests_written = generate_batch_jsonl(
            cursor,
            output_file,
            system_prompt,
            model=args.model
        )

        print(f"\n✓ Generated {requests_written} requests in {output_file}")
        print(f"  Model: {args.model}")
        print(f"  Documents: {len(result_ids)}")
        print(f"  Categories: {len(categories)}")
        print(f"  File size: {output_file.stat().st_size:,} bytes")

        # Show database stats
        cursor.execute("SELECT COUNT(*) FROM result")
        total_results = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM category")
        total_categories = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM result_category")
        total_processed = cursor.fetchone()[0]

        total_possible = total_results * total_categories

        print(f"\nDatabase Status:")
        print(f"  Total documents: {total_results}")
        print(f"  Total categories: {total_categories}")
        print(f"  Processed pairs: {total_processed:,} / {total_possible:,} ({total_processed/total_possible*100:.1f}%)")
        print(f"  Remaining pairs: {requests_written:,}")

    except Exception as e:
        conn.rollback()
        print(f"\n✗ Error: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
