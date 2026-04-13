"""
Generate vLLM batch file for corpus processing.

This script:
1. Syncs category table with POC-prompts/ directory (SHA-256 hash)
2. Syncs result table with input/ directory (SHA-256 hash)
3. Generates batch JSONL using SQL WHERE NOT EXISTS for missing pairs
4. Supports resumability - only generates requests for unprocessed pairs

Usage:
    python generate_batch.py [--limit N] [--output batch.jsonl] [--db corpus.db]
"""

import argparse
import hashlib
import json
import sqlite3
import sys
import yaml
from pathlib import Path
from typing import Dict, List, Tuple

# Binary file magic bytes (at start of content body)
BINARY_MAGIC: Dict[bytes, str] = {
    # Archives
    b'PK': 'ZIP archive',
    b'Rar!': 'RAR archive',
    b'7z\xbc\xaf': '7-Zip archive',
    # Executables
    b'MZ': 'DOS/Windows EXE',
    b'\x7fELF': 'Linux ELF binary',
    # Multimedia containers
    b'RIFF': 'AVI/WAV container',
    b'CWS': 'Compressed SWF (Flash)',
    b'FWS': 'Uncompressed SWF (Flash)',
    b'OggS': 'Ogg container',
    b'fLaC': 'FLAC audio',
    b'ID3': 'MP3 with ID3 tag',
    b'\xff\xfb': 'MP3 audio',
    # Images
    b'GIF87a': 'GIF image',
    b'GIF89a': 'GIF image',
    b'\x89PNG': 'PNG image',
    b'\xff\xd8\xff': 'JPEG image',
    b'BM': 'BMP image',
    # Documents
    b'%PDF': 'PDF document',
    b'\xd0\xcf\x11\xe0': 'MS Office (old)',
    b'PK\x03\x04': 'MS Office (new)/EPUB',
}

# Minimum content length to be considered valid (after URL header)
MIN_CONTENT_LENGTH = 100


def get_content_body(content: str) -> str:
    """Extract body after URL header line."""
    if '\n\n' in content:
        return content.split('\n\n', 1)[1]
    return content


def is_binary_content(content: str) -> Tuple[bool, str]:
    """
    Check if content starts with binary magic bytes.

    Returns:
        Tuple of (is_binary, detected_type)
    """
    body = get_content_body(content)
    if not body:
        return False, ''

    body_bytes = body[:10].encode('utf-8', errors='ignore')

    for magic, file_type in BINARY_MAGIC.items():
        if body_bytes.startswith(magic):
            return True, file_type
    return False, ''


def is_valid_text_content(content: str) -> Tuple[bool, str]:
    """
    Check if content is valid text, not binary garbage.

    Returns:
        Tuple of (is_valid, rejection_reason)
    """
    if not content:
        return False, 'empty content'

    body = get_content_body(content)
    if not body or len(body) < MIN_CONTENT_LENGTH:
        return False, f'content too short ({len(body) if body else 0} chars)'

    # Check for binary magic
    is_binary, binary_type = is_binary_content(content)
    if is_binary:
        return False, f'binary content detected ({binary_type})'

    # Check for null bytes
    if '\x00' in content:
        return False, 'contains null bytes'

    # Check printable ratio (allow unicode)
    printable = sum(1 for c in body if c.isprintable() or c in '\n\r\t')
    ratio = printable / len(body)
    if ratio < 0.85:
        return False, f'low printable ratio ({ratio:.1%})'

    return True, ''


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


def sync_documents(cursor: sqlite3.Cursor, input_dir: Path) -> Tuple[List[int], int]:
    """
    Sync result table with input/ directory.

    Always syncs ALL documents - LIMIT is applied later when generating batch.
    Validates content before inserting to skip binary/invalid files.

    Args:
        cursor: Database cursor
        input_dir: Directory containing markdown files

    Returns:
        Tuple of (list of result_ids that were synced, count of skipped files)
    """
    md_files = sorted(input_dir.glob("*.md"))

    if not md_files:
        raise ValueError(f"No .md files found in {input_dir}")

    result_ids = []
    skipped_count = 0
    added_count = 0
    total_files = len(md_files)
    last_progress = -1

    print(f"  Found {total_files:,} files to sync")

    for i, md_file in enumerate(md_files):
        # Progress output: immediately at start, then every 5%
        progress = ((i + 1) * 100) // total_files
        if progress == 0 and last_progress == -1:
            print("  Sync progress: 0% (starting...)")
            last_progress = 0
        elif progress >= last_progress + 5:
            print(f"  Sync progress: {progress}% ({i + 1:,}/{total_files:,})")
            last_progress = progress

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
            # New document or content changed - validate before inserting
            with open(md_file) as f:
                content = f.read()

            # Validate content
            is_valid, rejection_reason = is_valid_text_content(content)
            if not is_valid:
                skipped_count += 1
                continue

            # Insert new result
            cursor.execute("""
                INSERT INTO result (filepath, content, content_sha256)
                VALUES (?, ?, ?)
            """, (str(md_file), content, content_hash))

            result_id = cursor.lastrowid
            result_ids.append(result_id)
            added_count += 1

    print(f"  Sync complete: {added_count:,} added, {skipped_count:,} skipped")
    return result_ids, skipped_count


def load_system_prompt(project_root: Path) -> str:
    """Load universal system prompt."""
    with open(project_root / "system_prompt.txt") as f:
        return f.read()


def generate_batch_jsonl(
    cursor: sqlite3.Cursor,
    output_file: Path,
    system_prompt: str,
    prompts_dir: Path,
    model: str = "openai/gpt-oss-20b",
    limit: int = None,
    max_content_length: int = 80000  # ~16k words at 5 chars/word
):
    """
    Generate batch JSONL using SQL WHERE NOT EXISTS.

    Only generates requests for (result, category) pairs that haven't been processed.

    Args:
        limit: Maximum number of DOCUMENTS to process (not total requests)
        max_content_length: Maximum content length in characters (default 80k = ~16k words)
    """
    # Find all missing (result_id, category_id) pairs
    # Apply LIMIT at the document level, not the request level
    # Exclude documents longer than max_content_length
    limit_clause = f"LIMIT {limit}" if limit else ""

    cursor.execute(f"""
        SELECT r.result_id, r.filepath, r.content,
               c.category_id, c.category_filename, c.category_name
        FROM result r
        CROSS JOIN category c
        WHERE NOT EXISTS (
            SELECT 1 FROM result_category rc
            WHERE rc.result_id = r.result_id
            AND rc.category_id = c.category_id
        )
        AND LENGTH(r.content) <= {max_content_length}
        AND r.result_id IN (
            SELECT DISTINCT r2.result_id
            FROM result r2
            CROSS JOIN category c2
            WHERE NOT EXISTS (
                SELECT 1 FROM result_category rc2
                WHERE rc2.result_id = r2.result_id
                AND rc2.category_id = c2.category_id
            )
            AND LENGTH(r2.content) <= {max_content_length}
            ORDER BY r2.result_id
            {limit_clause}
        )
        ORDER BY r.result_id, c.category_id
    """)

    missing_pairs = cursor.fetchall()

    if not missing_pairs:
        print("No missing pairs to process")
        return 0

    print(f"\nGenerating batch for {len(missing_pairs)} missing pairs...")

    # Load category prompts
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
                    "max_tokens": 32000,
                }
            }

            f.write(json.dumps(request) + "\n")
            requests_written += 1

    return requests_written


def main():
    """Generate batch file for corpus processing."""
    parser = argparse.ArgumentParser(description="Generate batch file for corpus processing")
    parser.add_argument("--limit", type=int, help="Limit number of documents to process")
    parser.add_argument("--output", default="batch.jsonl", help="Output batch file")
    parser.add_argument("--db", default="corpus.db", help="Database path")
    parser.add_argument("--model", default="openai/gpt-oss-20b", help="Model name")
    parser.add_argument("--max-length", type=int, default=80000,
                        help="Maximum document length in characters (default: 80000 = ~16k words)")

    args = parser.parse_args()

    # Setup paths (all relative to script directory = project root)
    project_root = Path(__file__).parent
    db_path = project_root / args.db
    output_file = project_root / args.output
    prompts_dir = project_root / "POC-prompts"
    input_dir = project_root / "input" / "markdown_corpus"
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

        result_ids, skipped_count = sync_documents(cursor, input_dir)
        print(f"✓ Synced {len(result_ids)} documents (total in database)")
        if skipped_count > 0:
            print(f"  Skipped {skipped_count} invalid files (binary/empty/corrupt)")

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
            prompts_dir,
            model=args.model,
            limit=args.limit,
            max_content_length=args.max_length
        )

        print(f"\n✓ Generated {requests_written} requests in {output_file}")
        print(f"  Model: {args.model}")
        print(f"  Max document length: {args.max_length:,} chars (~{args.max_length // 5:,} words)")
        print(f"  Documents: {len(result_ids)}")
        print(f"  Categories: {len(categories)}")
        print(f"  File size: {output_file.stat().st_size:,} bytes")

        # Show database stats
        cursor.execute("SELECT COUNT(*) FROM result")
        total_results = cursor.fetchone()[0]

        cursor.execute(f"SELECT COUNT(*) FROM result WHERE LENGTH(content) > {args.max_length}")
        excluded_docs = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM category")
        total_categories = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM result_category")
        total_processed = cursor.fetchone()[0]

        total_possible = total_results * total_categories

        print(f"\nDatabase Status:")
        print(f"  Total documents: {total_results}")
        print(f"  Excluded (too long): {excluded_docs}")
        print(f"  Eligible documents: {total_results - excluded_docs}")
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
