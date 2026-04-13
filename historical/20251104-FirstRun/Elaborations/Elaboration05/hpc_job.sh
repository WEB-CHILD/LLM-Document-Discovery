#!/bin/bash
#SBATCH --job-name=e05-vllm-test
#SBATCH --output=/work/20251104-FirstRun/logs/e05_vllm_test_%j.log
#SBATCH --error=/work/20251104-FirstRun/logs/e05_vllm_test_%j.err
#SBATCH --time=01:00:00
#SBATCH --partition=gpu
#SBATCH --gres=gpu:h100:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=YOUR_EMAIL@example.com

#
# Elaboration 05: HPC vLLM Startup & Model Loading Test
#
# Fire-and-forget job script for HPC submission.
# Submit via web interface or CLI: sbatch Elaborations/Elaboration05/hpc_job.sh
#
# Tests:
# - vLLM loads on H100 with tensor parallelism
# - Model downloads to /work/.cache/
# - Harmony integration works
# - Acceptable startup time (< 10 min cold, < 2 min warm)
#

set -eo pipefail  # Exit on error or pipe failure (but allow unbound variables)

echo "=========================================="
echo "E05: HPC vLLM Startup Test"
echo "Job ID: ${SLURM_JOB_ID:-N/A}"
echo "Node: ${SLURM_NODELIST:-local}"
echo "Start time: $(date)"
echo "=========================================="

#
# Environment Setup
#

# Work directory (persistent across VM restarts)
export WORK_DIR="/work/20251104-FirstRun"
export LOG_DIR="${WORK_DIR}/logs"

# HuggingFace cache (persistent) - pattern from document-corpus-llm-project
export HF_HOME="/work/.cache/huggingface"
export TRANSFORMERS_CACHE="/work/.cache/huggingface/transformers"
export TORCH_HOME="/work/.cache/torch"

# Python environment
export PYTHONUNBUFFERED=1
export TOKENIZERS_PARALLELISM=false

# vLLM cache (if needed)
export VLLM_CACHE_DIR="/work/.cache/vllm"

# Create all cache directories before model load
mkdir -p "${LOG_DIR}"
mkdir -p "${HF_HOME}/transformers"
mkdir -p "${TORCH_HOME}"
mkdir -p "${VLLM_CACHE_DIR}"

echo ""
echo "Environment:"
echo "  WORK_DIR: ${WORK_DIR}"
echo "  HF_HOME: ${HF_HOME}"
echo "  TRANSFORMERS_CACHE: ${TRANSFORMERS_CACHE}"
echo "  TORCH_HOME: ${TORCH_HOME}"
echo "  VLLM_CACHE_DIR: ${VLLM_CACHE_DIR}"
echo "  LOG_DIR: ${LOG_DIR}"

# Check cache contents
if [ -d "${HF_HOME}" ]; then
    echo "  HF cache size: $(du -sh ${HF_HOME} 2>/dev/null || echo 'N/A')"
fi

#
# GPU Check
#

echo ""
echo "GPU Information:"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || echo "nvidia-smi not available"

#
# Clone Repository (if not already present)
#

REPO_DIR="${WORK_DIR}/20251104-FirstRun"

if [ ! -d "${REPO_DIR}/.git" ]; then
    echo ""
    echo "Cloning repository..."
    cd "${WORK_DIR}"
    git clone https://github.com/YOUR_ORG/20251104-FirstRun.git
    cd "${REPO_DIR}"
else
    echo ""
    echo "Repository already cloned, pulling latest changes..."
    cd "${REPO_DIR}"
    git pull origin main || echo "Warning: git pull failed (may be offline or detached HEAD)"
fi

#
# Python Environment Setup
#

echo ""
echo "Setting up Python environment..."

# Check if uv is available
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

# Sync dependencies
echo "Syncing dependencies with uv..."
uv sync

echo "Python environment ready"

#
# Test Configuration
#

# Model to test (can be overridden)
export TEST_MODEL="${TEST_MODEL:-openai/gpt-oss-20b}"
export TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-2}"

echo ""
echo "Test Configuration:"
echo "  Model: ${TEST_MODEL}"
echo "  Tensor Parallel Size: ${TENSOR_PARALLEL_SIZE}"

#
# Run Test
#

echo ""
echo "=========================================="
echo "Running E05 vLLM startup test..."
echo "=========================================="

TEST_START=$(date +%s)

# Run the test script
uv run python Elaborations/Elaboration05/test_hpc_vllm_startup.py

TEST_EXIT_CODE=$?
TEST_END=$(date +%s)
TEST_DURATION=$((TEST_END - TEST_START))

echo ""
echo "=========================================="
echo "Test completed"
echo "  Exit code: ${TEST_EXIT_CODE}"
echo "  Duration: ${TEST_DURATION}s ($((TEST_DURATION / 60)) min)"
echo "=========================================="

#
# Save Results
#

RESULTS_FILE="${LOG_DIR}/e05_results_${SLURM_JOB_ID:-manual}.txt"

cat > "${RESULTS_FILE}" <<EOF
Elaboration 05 Results
======================

Job ID: ${SLURM_JOB_ID:-N/A}
Node: ${SLURM_NODELIST:-local}
Start time: $(date -d @${TEST_START})
End time: $(date -d @${TEST_END})
Duration: ${TEST_DURATION}s ($((TEST_DURATION / 60)) min)

Model: ${TEST_MODEL}
Tensor Parallel Size: ${TENSOR_PARALLEL_SIZE}

Exit Code: ${TEST_EXIT_CODE}

EOF

if [ ${TEST_EXIT_CODE} -eq 0 ]; then
    echo "Status: PASS" >> "${RESULTS_FILE}"
    echo ""
    echo "✅ E05 Test PASSED"
else
    echo "Status: FAIL" >> "${RESULTS_FILE}"
    echo ""
    echo "❌ E05 Test FAILED"
fi

echo ""
echo "Results saved to: ${RESULTS_FILE}"

#
# Cleanup (optional)
#

# Optionally clear GPU cache to free memory
# (Comment out if you want cache to persist for subsequent runs)
# python -c "import torch; torch.cuda.empty_cache()" 2>/dev/null || true

echo ""
echo "=========================================="
echo "Job finished: $(date)"
echo "=========================================="

exit ${TEST_EXIT_CODE}
