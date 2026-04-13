#!/bin/bash
# Pull demo data from HPC and import results
# Usage: bash pull_demo.sh PORT
set -euo pipefail

PORT="${1:?Usage: bash pull_demo.sh PORT}"
REMOTE="ucloud@ssh.cloud.sdu.dk"
WORK="/work/20251104-FirstRun"
DB="4pct_kidlink.db"

echo "Pulling corpus_kidlink.db..."
rsync -avz -e "ssh -p $PORT" "$REMOTE:$WORK/corpus_kidlink.db" "./$DB"

echo "Pulling results.jsonl..."
mkdir -p demo_out
rsync -avz -e "ssh -p $PORT" "$REMOTE:$WORK/out/results.jsonl" ./demo_out/

echo "Importing results..."
uv run python import_results.py --db "$DB" --input-dir demo_out/

echo "Done. Run: uv run datasette $DB"
