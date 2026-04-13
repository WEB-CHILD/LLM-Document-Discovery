#!/bin/bash
#
# HPC Machine Setup Script
# Run this ONCE when provisioning a new HPC machine
# This installs system dependencies that persist on the /work volume
#

set -e

echo "========================================"
echo "HPC Machine Setup"
echo "Started: $(date)"
echo "Node: $(hostname)"
echo "========================================"
echo ""

mkdir -p /work/apt-cache/archives/partial

cd /work/20251104-FirstRun

# Verify script integrity - print hashes for comparison with local machine
echo "## Script Integrity Check"
echo "SHA256 hashes of key files:"
sha256sum hpc_setup.sh run_unattended.sh process_corpus.sh start_server_hpc.sh runner.sh 2>/dev/null || echo "(some files not found)"
sha256sum unified_processor.py prep_db.py preflight_check.py import_results.py 2>/dev/null || echo "(some files not found)"
echo ""

# sudo dpkg --install ./cuda-keyring_1.1-1_all.deb
# sudo cp cuda-ubuntu2404.pin /etc/apt/preferences.d/cuda-repository-pin-60
# sudo dpkg -i cuda-repo-ubuntu2404-13-0-local_13.0.2-580.95.05-1_amd64.deb
# sudo cp /var/cuda-repo-ubuntu2404-13-0-local/cuda-*-keyring.gpg /usr/share/keyrings/

# Update package lists
echo "## Step 1: Updating package lists..."
if sudo apt update -y > /tmp/apt-update.log 2>&1; then
    echo "  ✓ Package lists updated"
else
    echo "  ✗ apt update failed:"
    cat /tmp/apt-update.log
    exit 1
fi

# sudo apt upgrade -y

#sudo apt install -y cuda-toolkit-13-0 build-essential
echo "## Step 2: Installing packages..."
if sudo apt-get -o Dir::Cache::Archives="/work/apt-cache/archives" \
                -o Dir::Cache="/work/apt-cache" \
        install -y bc nvidia-cuda-toolkit build-essential sqlite3 byobu > /tmp/apt-install.log 2>&1; then
    echo "  ✓ Packages installed"
else
    echo "  ✗ apt-get install failed:"
    cat /tmp/apt-install.log
    exit 1
fi

byobu-enable > /dev/null 2>&1
byobu-ctrl-a screen > /dev/null 2>&1

# Verify CUDA installation
echo "## Step 3: Verifying CUDA..."
if which nvcc > /dev/null 2>&1; then
    echo "  ✓ nvcc found: $(nvcc --version 2>&1 | grep release | awk '{print $5}' | tr -d ',')"
else
    echo "  ✗ nvcc not found"
fi
echo "  CUDA_HOME: ${CUDA_HOME:-not set}"

# Install uv if not present
echo "## Step 4: Installing uv..."
if curl -LsSf https://astral.sh/uv/install.sh 2>/dev/null | sh > /tmp/uv-install.log 2>&1; then
    echo "  ✓ uv installed"
else
    echo "  ✗ uv install failed:"
    cat /tmp/uv-install.log
fi
export PATH="$HOME/.local/bin:$PATH"


# Add environment variables to .bashrc for persistence
echo "## Step 5: Adding environment variables to .bashrc..."

# Check if already added
if ! grep -q "# vLLM Environment Variables" /home/ucloud/.bashrc; then
    cat >> /home/ucloud/.bashrc << 'EOF'

# Cache directories on /scratch (500GB available, regeneratable)
export VLLM_BASE="/scratch/cache/vllm"
export HF_HOME="/scratch/cache/huggingface"
export HUGGINGFACE_HUB_CACHE="/scratch/cache/huggingface/hub"
export VLLM_CACHE_ROOT="/scratch/cache/vllm"
export TORCH_HOME="/scratch/cache/torch"

# Virtual environment on /scratch
export UV_PROJECT_ENVIRONMENT="/scratch/venv"
export UV_TORCH_BACKEND=auto
export UV_LINK_MODE=copy

# Model configuration (can be overridden)
export GPT_MODEL="${GPT_MODEL:-openai/gpt-oss-120b}"
export VLLM_TENSOR_PARALLEL_SIZE="${VLLM_TENSOR_PARALLEL_SIZE:-1}"
export VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.98}"
export REASONING_EFFORT="${REASONING_EFFORT:-Medium}"
export HF_TOKEN=REDACTED

# Project paths
export WORK_DIR="/work/20251104-FirstRun"

# Corpus configuration - update these for different corpora:
#   kidlink_corpus  -> corpus_kidlink.db
#   markdown_corpus -> corpus_markdown.db
export CORPUS_NAME="kidlink_corpus"
export INPUT_DIR="$WORK_DIR/input/$CORPUS_NAME"
export DB_PATH="$WORK_DIR/corpus_kidlink.db"

# Add uv to PATH if installed
export PATH="$HOME/.local/bin:$PATH"
EOF
    echo "✓ Environment variables added to .bashrc"
else
    echo "✓ Environment variables already in .bashrc"
fi

# sudo su - ucloud byobu-enable

# Create /scratch directories for cache and venv
sudo mkdir -p /scratch/cache/vllm /scratch/cache/huggingface/hub /scratch/cache/torch /scratch/venv
sudo chown -R "$(whoami)":"$(whoami)" /scratch

echo "## Step 6: Installing Python dependencies..."
if uv sync > /tmp/uv-sync.log 2>&1; then
    echo "  ✓ Dependencies installed"
else
    echo "  ✗ uv sync failed:"
    cat /tmp/uv-sync.log
    exit 1
fi

# Export key variables for current session (batch script runs without re-sourcing .bashrc)
export WORK_DIR="/work/20251104-FirstRun"

# Corpus configuration - must match .bashrc block above
export CORPUS_NAME="kidlink_corpus"
export INPUT_DIR="$WORK_DIR/input/$CORPUS_NAME"
export DB_PATH="$WORK_DIR/corpus_kidlink.db"

export HF_TOKEN=REDACTED

# Cache directories on /scratch (ephemeral, not /work/)
export HF_HOME="/scratch/cache/huggingface"
export HUGGINGFACE_HUB_CACHE="/scratch/cache/huggingface/hub"
export VLLM_CACHE_ROOT="/scratch/cache/vllm"
export TORCH_HOME="/scratch/cache/torch"

echo ""
echo "✓ Setup complete"
echo "  WORK_DIR=$WORK_DIR"
echo "  HF_HOME=$HF_HOME (ephemeral)"
echo "  Model downloads go to /scratch/, not /work/"

#uv run vllm serve openai/gpt-oss-120b  --gpu-memory-utilization 0.95  --max-num-seqs 15 --port 8000

# echo "## Step 6: Starting vLLM server..."

# # Check if server is already running
# if curl -s http://localhost:8000/v1/models > /dev/null 2>&1; then
#     echo "✓ vLLM server already running"
# else
#     # Start server in background with nohup
#     nohup uv run vllm serve openai/gpt-oss-120b \
#         --gpu-memory-utilization 0.95 \
#         --max-num-seqs 15 \
#         --port 8000 \
#         > /work/20251104-FirstRun/vllm_server.log 2>&1 &
    
#     sleep 60

#     # Wait for server to be ready
#     echo "Waiting for vLLM server to start..."
#     for i in {1..60}; do
#         if curl -s http://localhost:8000/v1/models > /dev/null 2>&1; then
#             echo "✓ vLLM server started successfully"
#             break
#         fi
#         sleep 2
#     done
    
#     if ! curl -s http://localhost:8000/v1/models > /dev/null 2>&1; then
#         echo "⚠ vLLM server failed to start. Check /work/20251104-FirstRun/vllm_server.log"
#     fi
# fi