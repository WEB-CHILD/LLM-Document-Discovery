#!/bin/bash
# Sync local files to HPC via rsync
# Usage: ./sync_to_hpc.sh <port>
# Example: ./sync_to_hpc.sh 2142

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <port>"
    echo "Example: $0 2142"
    exit 1
fi

PORT="$1"
REMOTE="ucloud@ssh.cloud.sdu.dk"
REMOTE_PATH="/work/20251104-FirstRun/"

echo "Syncing to $REMOTE:$PORT -> $REMOTE_PATH"

rsync -avz --progress -e "ssh -p $PORT" \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='.pytest_cache/' \
    --exclude='*.pyc' \
    --exclude='*.sync-conflict-*' \
    ./ "$REMOTE:$REMOTE_PATH"

echo "Done."
