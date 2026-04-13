#!/usr/bin/env bash
# Prepare a data directory for the container pipeline.
# Run on the host before launching the container.
#
# Usage: bash scripts/prepare_container_data.sh [DATA_DIR] [HPC_ENV_FILE]
#   DATA_DIR:     Target directory (default: ./data)
#   HPC_ENV_FILE: Path to hpc_env.sh (default: container/hpc_env.rtx4090.sh)

set -euo pipefail

DATA_DIR="${1:-./data}"
HPC_ENV_FILE="${2:-container/hpc_env.rtx4090.sh}"

if [ ! -f "$HPC_ENV_FILE" ]; then
    echo "ERROR: HPC env file not found: $HPC_ENV_FILE"
    exit 1
fi

echo "Preparing container data directory: $DATA_DIR"
mkdir -p "$DATA_DIR/out"

# Fetch demo corpus if not already present
if [ ! -d input/demo_corpus ] || ! find input/demo_corpus -maxdepth 0 -not -empty -print -quit 2>/dev/null | grep -q .; then
    echo "Fetching demo corpus from Internet Archive..."
    uv run llm-discovery fetch --output-dir input/demo_corpus
fi

# Create and populate corpus.db
echo "Building corpus database..."
uv run llm-discovery prep-db \
    --db "$DATA_DIR/corpus.db" \
    --input-dir input/demo_corpus \
    --prompts-dir prompts

# Validate documents
echo "Running preflight checks..."
uv run llm-discovery preflight --db "$DATA_DIR/corpus.db"

# Copy required files
cp system_prompt.txt "$DATA_DIR/"
cp -r prompts/ "$DATA_DIR/prompts/"
cp "$HPC_ENV_FILE" "$DATA_DIR/hpc_env.sh"

echo "Data directory ready at $DATA_DIR"
echo "Contents:"
ls -la "$DATA_DIR"
