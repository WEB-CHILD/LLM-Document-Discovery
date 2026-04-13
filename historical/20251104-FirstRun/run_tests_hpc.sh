#!/bin/bash
#
# HPC Test Runner
# Cleans cache and runs pytest on HPC
#

echo "========================================"
echo "HPC Test Runner"
echo "Started: $(date)"
echo "========================================"
echo ""

# Load environment variables
echo "## Step 0: Loading environment variables..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/hpc_env.sh" ]; then
    source "$SCRIPT_DIR/hpc_env.sh"
else
    echo "⚠️  Warning: hpc_env.sh not found, using current environment"
fi
echo ""

# Clean __pycache__ to avoid conflicts
echo "## Step 1: Cleaning Python cache..."
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
echo "✓ Cache cleaned"
echo ""

# Run non-GPU tests
echo "## Step 2: Running non-GPU tests..."
uv run pytest tests/ -v -m "not gpu"
echo ""

# Run GPU tests
echo "## Step 3: Running GPU tests..."
uv run pytest tests/ -v -m gpu
echo ""

echo "========================================"
echo "Tests Complete: $(date)"
echo "========================================"
