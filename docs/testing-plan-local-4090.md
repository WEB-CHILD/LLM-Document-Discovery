# Testing Plan: Local RTX 4090 → Gadi → UCloud

Escalation path from local development GPU through to production HPC.

## Tier 1: Local RTX 4090 + Gemma 4 E4B

**Goal:** Demonstrate the pipeline runs end-to-end on a single consumer GPU.

**Hardware:** RTX 4090 (24GB VRAM)
**Model:** `google/gemma-4-E4B-it` (effective 4B params, BF16, fits in 24GB)
**vLLM:** nightly (`--pre` from `wheels.vllm.ai/nightly/cu129`)

### Prerequisites

```bash
# Install vLLM nightly (cannot be in uv.lock — PEP 440 incompatible)
uv pip install -U vllm --pre \
  --extra-index-url https://wheels.vllm.ai/nightly/cu129 \
  --extra-index-url https://download.pytorch.org/whl/cu129 \
  --index-strategy unsafe-best-match
uv pip install transformers==5.5.0

# If HF cache fills root disk, symlink to external storage:
# ln -s /media/brian/storage/.cache/huggingface ~/.cache/huggingface
```

### Run

```bash
uv run llm-discovery run \
  --platform local \
  --gpu-type RTX4090 \
  --model google/gemma-4-E4B-it \
  --yes
```

This fetches 5 demo pages, starts vLLM with `--gpu-memory-utilization 0.85 --max-num-seqs 16`, runs prep-db → preflight → process → import-results, and kills the server on exit.

### Verification checklist

```bash
# 1. Pipeline completed without error
echo $?  # expect 0

# 2. Database has results for all 5 docs x 21 categories
sqlite3 corpus.db "SELECT COUNT(*) FROM result_category"
# expect: 105 (or more if documents were split)

# 3. All categories covered
sqlite3 corpus.db "SELECT COUNT(DISTINCT category_id) FROM result_category"
# expect: 21

# 4. All documents covered
sqlite3 corpus.db "SELECT COUNT(DISTINCT result_id) FROM result_category"
# expect: 5 (or more if split)

# 5. Match values are valid
sqlite3 corpus.db "SELECT DISTINCT match FROM result_category"
# expect: yes, maybe, no (some subset)

# 6. Blockquotes extracted
sqlite3 corpus.db "SELECT COUNT(*) FROM result_category_blockquote"
# expect: > 0

# 7. Browse results
datasette corpus.db
```

### Known caveats (from melica spike)

- **Structured output not enforced:** vLLM nightly doesn't enforce `response_format: json_schema` for Gemma 4. Responses may wrap JSON in markdown fences. The `extract_json_from_text()` parser in `unified_processor.py` handles this — it finds balanced braces regardless of surrounding text.
- **Performance:** ~1-2s per request on RTX 4090, so 105 pairs ≈ 2-4 minutes.
- **Quality:** Gemma 4 E4B is a small model. Classification quality will be lower than gpt-oss-120b. This tier validates the pipeline mechanics, not output quality.

---

## Tier 2: NCI Gadi (gpuhopper — H200)

**Goal:** Run the full pipeline at production scale on HPC with the production model.

**Hardware:** 4x H200 (141GB VRAM each, 564GB total)
**Queue:** gpuhopper
**Model:** `mistralai/gpt-oss-120b`
**vLLM params:** tp=4, gpu_mem=0.92, max_seqs=384

### Prerequisites

See [docs/gadi-setup.md](gadi-setup.md) for SSH, project allocation, HF_TOKEN, uv installation.

### Run

```bash
uv run llm-discovery run \
  --platform gadi \
  --project <NCI_PROJECT> \
  --gpu-queue gpuhopper \
  --yes
```

This validates SSH → rsyncs code → submits PBS job → polls qstat → retrieves corpus.db.

### Verification checklist

Same as Tier 1 checklist, plus:

```bash
# 8. Run stats recorded
sqlite3 corpus.db "SELECT * FROM run_stats"
# expect: 1 row with model=mistralai/gpt-oss-120b, pairs_processed=105

# 9. Compare quality against Tier 1
sqlite3 corpus.db "SELECT match, COUNT(*) FROM result_category GROUP BY match"
# expect: distribution should be more nuanced than Gemma 4 E4B
```

### Fallback: gpuvolta (V100)

If gpuhopper allocation unavailable:

```bash
uv run llm-discovery run \
  --platform gadi \
  --project <NCI_PROJECT> \
  --gpu-queue gpuvolta \
  --yes
```

V100 nodes (4x32GB = 128GB total). `gpt-oss-120b` at FP16 needs ~240GB — won't fit. Options:
- Use a quantised model variant
- Use Gemma 4 E4B (same as local, validates HPC pipeline without production model)
- Wait for gpuhopper allocation

---

## Tier 3: DeiC UCloud (H100)

**Goal:** Demonstrate cross-platform HPC portability.

**Hardware:** 4x H100 (80GB VRAM each, 320GB total)
**Model:** `mistralai/gpt-oss-120b`
**vLLM params:** tp=4, gpu_mem=0.92, max_seqs=384

### Run

UCloud requires manual submission (no SSH-based automation):

```bash
# Sync code manually (git clone or UCloud Drive upload)
# Then inside UCloud Terminal:
cd /work/llm-discovery
bash hpc/ucloud_batch.sh
```

Or via the CLI (prints manual instructions):

```bash
uv run llm-discovery deploy --platform ucloud
```

### Verification checklist

Same as Tier 2 checklist. Additionally:

```bash
# 10. Retrieve results from UCloud
# (manual: download corpus.db via UCloud Drive or scp)

# 11. Compare results across all 3 tiers
# Same 5 documents, same 21 categories — results should be
# structurally identical (same schema) with different quality/match
# distributions reflecting model capability.
```

---

## Summary

| Tier | GPU | Model | Purpose | Pairs | Est. time |
|------|-----|-------|---------|-------|-----------|
| 1 | RTX 4090 (1x24GB) | Gemma 4 E4B | Pipeline validation | 105 | ~3 min |
| 2 | H200 (4x141GB) | gpt-oss-120b | Production quality | 105 | ~1 min |
| 3 | H100 (4x80GB) | gpt-oss-120b | Cross-platform check | 105 | ~1 min |
