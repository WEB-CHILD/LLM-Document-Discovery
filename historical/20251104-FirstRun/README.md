# Boolean Index POC - Children's Web Corpus (1996-2005)

Proof of concept for building a boolean index on historical children's web content using LLM-based extraction.

## Quick Start

```bash
# Install dependencies
uv sync

# Run extraction on test file
uv run main.py

# View results in web UI
uv run datasette serve corpus.db
```

## What It Does

Processes markdown files through ollama (gpt-oss:20b) to extract evidence of 15 linguistic/structural categories:

1. Imperative verbs (commands)
2. Explicit age/child references
3. Corporate register markers
4. Educational register markers
5. Non-standard spelling
6. Syntactic irregularities
7. Topic mixing markers
8. Age/identity claims
9. Gendered direct address
10. Gendered activities/objects
11. Interactive element text
12. Colour/style words in HTML
13. Youth slang/informality
14. Question forms
15. First-person plural inclusivity

For each category, returns:
- Match status: `yes` / `maybe` / `no`
- Blockquotes: Array of extracted evidence

## Database Views

The SQLite database includes two denormalized views for easy querying:

### `result_summary`
One row per document with all 15 categories as columns:
- `result_id`, `filepath`, `created_at`
- 15 category columns (yes/maybe/no)
- `total_blockquotes` count

### `blockquotes_by_category`
All blockquotes with category metadata:
- `result_id`, `filepath`, `category_name`
- `match` status, `blockquote` text
- Useful for browsing evidence

## Datasette Tips

When you run `uv run datasette serve corpus.db`:

1. Browse **result_summary** table for overview
2. Use column headers to filter/facet by category
3. Click into **blockquotes_by_category** to see evidence
4. Use SQL queries for complex analysis

Example queries:
```sql
-- Documents with "yes" for imperatives and child references
SELECT * FROM result_summary
WHERE imperative_verbs = 'yes'
AND explicit_age_child_references = 'yes';

-- All youth slang blockquotes
SELECT filepath, blockquote
FROM blockquotes_by_category
WHERE category_name = 'youth_slang_informality';
```

## Architecture

```
input/                  # Test files (single .md file)
input/markdown_corpus/  # Full corpus (7,466 files)
prompts/                # 15 category YAML definitions
system_prompt.txt       # Universal extraction instructions
schemas.py              # Pydantic output validation
schema.sql              # Database schema + views
processor.py            # Ollama interaction
db.py                   # SQLite operations
main.py                 # Orchestrator with Rich progress
corpus.db               # Output database
```

## Processing Full Corpus

To process all 7,466 files:

1. Update [main.py](main.py:128) to read from `input/markdown_corpus/`
2. Run: `uv run main.py`
3. Expected time: ~15 ollama calls × 7,466 files = ~112K calls
4. Monitor progress with Rich progress bars

## Methodology

- **No interpretation**: LLM extracts text patterns, humans interpret meaning
- **Broad net**: Over-inclusion preferred (`maybe` status for ambiguous cases)
- **Multilingual**: English, Danish, Korean support
- **Temporal agnostic**: No year-specific judgments across 1996-2005
- **Evidence-based**: Stores verbatim blockquotes for verification
