# Batch Processing Pipeline

Production scripts for vLLM batch processing with SHA-256 resumability.

## Quick Start

```bash
# Process 10 documents
LIMIT=10 bash process_corpus.sh

# Process all documents
bash process_corpus.sh

# Or run steps manually:
python generate_batch.py --limit 10    # Generate batch file
bash run_batch.sh batch.jsonl          # Run vLLM
python batch_to_db.py results.jsonl    # Insert to database
```

## Scripts

### generate_batch.py
Generates batch JSONL file for vLLM processing.

**Features:**
- Creates database if missing (from schema.sql)
- Syncs categories from POC-prompts/ (SHA-256 hash)
- Syncs documents from input/ (SHA-256 hash)
- Generates requests only for missing (document, category) pairs
- Resumable: rerun to process only remaining pairs

**Usage:**
```bash
python generate_batch.py [OPTIONS]

Options:
  --limit N           Process only first N documents
  --output FILE       Output batch file (default: batch.jsonl)
  --db PATH          Database path (default: corpus.db)
  --model NAME       Model name (default: openai/gpt-oss-20b)
```

### run_batch.sh
Runs vLLM batch processing with timing collection.

**Usage:**
```bash
bash run_batch.sh <batch.jsonl> [model] [output.jsonl]
```

**Output:**
- `results.jsonl` - vLLM batch results
- `results_timing.txt` - Performance metrics

### batch_to_db.py
Parses batch results and inserts into database.

**Usage:**
```bash
python batch_to_db.py <results.jsonl> [db_path]
```

### process_corpus.sh
Orchestrates full pipeline (generate → run → insert).

**Environment Variables:**
- `LIMIT` - Number of documents to process (default: all)
- `MODEL` - Model name (default: openai/gpt-oss-20b)
- `DB_PATH` - Database path (default: ./corpus.db)
- `TENSOR_PARALLEL_SIZE` - Number of GPUs to use (default: auto-detected)

**GPU Auto-Detection:**
The pipeline automatically detects available GPUs using `nvidia-smi` and configures tensor parallelism accordingly. You can override this by setting `TENSOR_PARALLEL_SIZE`.

**Usage:**
```bash
# Process 10 documents (auto-detect GPUs)
LIMIT=10 bash process_corpus.sh

# Use different model
MODEL=openai/gpt-oss-120b bash process_corpus.sh

# Override GPU count (use fewer than available)
TENSOR_PARALLEL_SIZE=2 MODEL=openai/gpt-oss-20b bash process_corpus.sh

# Custom database location
DB_PATH=/work/20251104-FirstRun/corpus.db bash process_corpus.sh
```

**Model-GPU Recommendations:**
- `openai/gpt-oss-20b` - Works well with 1-2 GPUs
- `openai/gpt-oss-120b` - Requires 4 GPUs for optimal performance

## HPC Usage

The pipeline automatically detects available GPUs, so it works seamlessly as you scale GPU allocation:

```bash
# With 1 GPU (current allocation)
LIMIT=10 bash process_corpus.sh

# Scale to 2 GPUs (auto-detected)
LIMIT=100 bash process_corpus.sh

# Scale to 4 GPUs for 120b model (auto-detected)
MODEL=openai/gpt-oss-120b bash process_corpus.sh
```

**GPU Scaling:**
- Start with 1 GPU for testing and small batches
- Scale to 2 GPUs for faster processing with gpt-oss-20b
- Scale to 4 GPUs when ready to run gpt-oss-120b on full corpus

## Database Schema

See [schema.sql](schema.sql) for complete schema.

**Key tables:**
- `result` - Documents with SHA-256 content hash
- `category` - Prompts with SHA-256 prompt hash
- `result_category` - Classification results
- `result_category_blockquote` - Evidence quotes

**Views:**
- `result_summary` - Document-level statistics
- `blockquotes_by_category` - All evidence with category names
- `category_matches` - Category-level results

## Resumability

The pipeline is fully resumable:

1. **Database tracks progress**: `result_category` table records completed pairs
2. **Hash-based change detection**:
   - Document edits → new result_id
   - Prompt changes → new category_id
3. **Crash recovery**: Just rerun - generates batch only for missing pairs

## Performance Monitoring

After each run:
- Check `results_timing.txt` for throughput metrics
- Query database for completion percentage:

```sql
SELECT
    COUNT(*) || ' / ' ||
    (SELECT COUNT(*) FROM result) * (SELECT COUNT(*) FROM category)
FROM result_category;
```
