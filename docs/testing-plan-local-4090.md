# Testing Plan: Local → Gadi → UCloud

Escalation path with model choice at each tier. The `--model` flag overrides
the per-GPU-type default at any tier.

## Available Models

| Model | ID | Architecture | Fits on |
|-------|----|-------------|---------|
| Gemma 4 E4B | `google/gemma-4-E4B-it` | eff. 4B dense | 1x 24GB+ |
| Gemma 4 31B | `google/gemma-4-31B-it` | 31B dense | 2x 80GB (TP2) or 4x 32GB (TP4) |
| GPT-OSS-120B | `openai/gpt-oss-120b` | 117B MoE / 5.1B active | 1x 80GB |

Sources: [vLLM Gemma 4 Recipe](https://docs.vllm.ai/projects/recipes/en/latest/Google/Gemma4.html), [gpt-oss-120b](https://huggingface.co/openai/gpt-oss-120b)

---

## Tier 1: Local RTX 4090

**Hardware:** 1x RTX 4090 (24GB)
**Default model:** `google/gemma-4-E4B-it`
**Config:** tp=1, mem=0.85, max_model_len=131072

### Prerequisites

```bash
uv pip install -U vllm --pre \
  --extra-index-url https://wheels.vllm.ai/nightly/cu129 \
  --extra-index-url https://download.pytorch.org/whl/cu129 \
  --index-strategy unsafe-best-match
uv pip install transformers==5.5.0
```

### Run

```bash
# Default (Gemma 4 E4B)
uv run llm-discovery run --platform local --gpu-type RTX4090 --yes

# Or override model
uv run llm-discovery run --platform local --gpu-type RTX4090 \
  --model google/gemma-4-E2B-it --yes
```

---

## Tier 2: Gadi gpuvolta (V100)

**Hardware:** 4x V100-32GB (128GB total)
**Default model:** `google/gemma-4-31B-it`
**Config:** tp=4, mem=0.90, max_model_len=262144

### Run

```bash
# Default (Gemma 4 31B)
uv run llm-discovery run --platform gadi --project <CODE> \
  --gpu-queue gpuvolta --yes

# Override to E4B for quick validation
uv run llm-discovery run --platform gadi --project <CODE> \
  --gpu-queue gpuvolta --model google/gemma-4-E4B-it --yes
```

---

## Tier 3: Gadi gpuhopper (H200)

**Hardware:** 4x H200-141GB (564GB total)
**Default model:** `openai/gpt-oss-120b`
**Config:** tp=4, mem=0.92, max_seqs=384

### Run

```bash
# Production model
uv run llm-discovery run --platform gadi --project <CODE> \
  --gpu-queue gpuhopper --yes

# Gemma 4 31B for comparison
uv run llm-discovery run --platform gadi --project <CODE> \
  --gpu-queue gpuhopper --model google/gemma-4-31B-it --yes
```

### Production comparison

Run both models on the same 5 documents, then compare:

```bash
# Run 1: gpt-oss-120b
uv run llm-discovery run --platform gadi --project <CODE> \
  --gpu-queue gpuhopper --yes
cp corpus.db corpus-gptoss.db

# Run 2: gemma-4-31B
rm corpus.db  # fresh DB
uv run llm-discovery run --platform gadi --project <CODE> \
  --gpu-queue gpuhopper --model google/gemma-4-31B-it --yes
cp corpus.db corpus-gemma31b.db

# Compare
sqlite3 corpus-gptoss.db "SELECT match, COUNT(*) FROM result_category GROUP BY match"
sqlite3 corpus-gemma31b.db "SELECT match, COUNT(*) FROM result_category GROUP BY match"

# Detailed comparison via datasette
datasette corpus-gptoss.db corpus-gemma31b.db
```

---

## Tier 4: UCloud (H100)

**Hardware:** 2x H100-80GB (160GB total)
**Default model:** `openai/gpt-oss-120b`
**Config:** tp=2, mem=0.92, max_seqs=128

### Run

```bash
# Inside UCloud Terminal:
cd /work/llm-discovery
bash hpc/ucloud_batch.sh

# Or override model:
VLLM_MODEL=google/gemma-4-31B-it bash hpc/ucloud_batch.sh
```

---

## Verification Checklist (all tiers)

```bash
sqlite3 corpus.db "SELECT COUNT(*) FROM result_category"                  # expect: 105
sqlite3 corpus.db "SELECT COUNT(DISTINCT category_id) FROM result_category" # expect: 21
sqlite3 corpus.db "SELECT COUNT(DISTINCT result_id) FROM result_category"   # expect: 5+
sqlite3 corpus.db "SELECT DISTINCT match FROM result_category"              # expect: yes/maybe/no
sqlite3 corpus.db "SELECT COUNT(*) FROM result_category_blockquote"         # expect: > 0
sqlite3 corpus.db "SELECT model, pairs_processed FROM run_stats"            # verify model name
datasette corpus.db                                                         # browse results
```
