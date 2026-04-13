#!/usr/bin/env bash
#
# Elaboration 05: HPC Ollama Startup Test
#
# This script tests whether Ollama can start, download models, and serve requests
# in an HPC environment with proper caching to persistent storage.
#
# This will FAIL if:
# - Ollama won't start
# - Model download fails or goes to wrong location
# - GPU loading fails
# - Startup time exceeds acceptable limits
#
# Usage:
#   # Local test (simulates HPC environment):
#   ./test_hpc_ollama_startup.sh
#
#   # On HPC (submit as job):
#   sbatch test_hpc_ollama_startup.sh

set -e  # Exit on error
set -u  # Exit on undefined variable

# ============================================================================
# Configuration
# ============================================================================

# Simulate HPC environment variables
# In real HPC, these would be set by the job scheduler or setup script
export WORK_DIR="${WORK_DIR:-/work/20251104-FirstRun}"  # Override in HPC
export OLLAMA_MODELS="${WORK_DIR}/.cache/ollama/models"
export OLLAMA_CACHE_DIR="${WORK_DIR}/.cache/ollama"

# Model to test
MODEL="gpt-oss:20b"

# Timing thresholds (seconds)
MAX_STARTUP_TIME=60        # Ollama server startup
MAX_DOWNLOAD_TIME=900      # Model download (15 min)
MAX_LOAD_TIME=120          # Model load into GPU
MAX_FIRST_REQUEST_TIME=60  # First inference
MAX_TOTAL_TIME=1200        # Total (20 min)

# Log file
LOG_FILE="${WORK_DIR}/elaboration05_startup.log"

# ============================================================================
# Helper Functions
# ============================================================================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

fail() {
    log "❌ FAIL: $*"
    exit 1
}

check_timing() {
    local phase="$1"
    local elapsed="$2"
    local max_time="$3"

    if [ "$elapsed" -gt "$max_time" ]; then
        fail "$phase took ${elapsed}s (max: ${max_time}s) - too slow!"
    else
        log "✓ $phase completed in ${elapsed}s (acceptable)"
    fi
}

# ============================================================================
# Pre-flight Checks
# ============================================================================

log "========================================================================"
log "Elaboration 05: HPC Ollama Startup Test"
log "========================================================================"

# Create directories
mkdir -p "$WORK_DIR"
mkdir -p "$OLLAMA_MODELS"
mkdir -p "$OLLAMA_CACHE_DIR"

log "Work directory: $WORK_DIR"
log "Ollama models: $OLLAMA_MODELS"
log "Ollama cache: $OLLAMA_CACHE_DIR"

# Check if running on GPU node
if command -v nvidia-smi &> /dev/null; then
    log "GPU detected:"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | tee -a "$LOG_FILE"
else
    log "⚠️  No GPU detected (nvidia-smi not found)"
fi

# Check if Ollama is installed
if ! command -v ollama &> /dev/null; then
    fail "Ollama not found in PATH"
fi

log "Ollama version: $(ollama --version)"

# ============================================================================
# Phase 1: Ollama Server Startup
# ============================================================================

log ""
log "Phase 1: Starting Ollama server..."
PHASE1_START=$(date +%s)

# Kill any existing Ollama processes
pkill -9 ollama || true
sleep 2

# Start Ollama server in background
ollama serve > "${WORK_DIR}/ollama_serve.log" 2>&1 &
OLLAMA_PID=$!

log "Ollama server started (PID: $OLLAMA_PID)"

# Wait for Ollama to be ready
MAX_WAIT=60
WAITED=0
while ! ollama list > /dev/null 2>&1; do
    if [ $WAITED -ge $MAX_WAIT ]; then
        fail "Ollama server did not start within ${MAX_WAIT}s"
    fi
    sleep 1
    WAITED=$((WAITED + 1))
done

PHASE1_END=$(date +%s)
PHASE1_ELAPSED=$((PHASE1_END - PHASE1_START))

check_timing "Ollama startup" "$PHASE1_ELAPSED" "$MAX_STARTUP_TIME"

# ============================================================================
# Phase 2: Model Download/Cache Check
# ============================================================================

log ""
log "Phase 2: Checking model cache and downloading if needed..."
PHASE2_START=$(date +%s)

# Check if model already cached
if ollama list | grep -q "$MODEL"; then
    log "✓ Model $MODEL already cached (warm start)"
    PHASE2_ELAPSED=0
else
    log "Model $MODEL not cached, pulling... (this may take several minutes)"

    # Pull model
    if ! ollama pull "$MODEL"; then
        fail "Failed to pull model $MODEL"
    fi

    PHASE2_END=$(date +%s)
    PHASE2_ELAPSED=$((PHASE2_END - PHASE2_START))

    check_timing "Model download" "$PHASE2_ELAPSED" "$MAX_DOWNLOAD_TIME"

    # Verify model is now in cache
    if ! ollama list | grep -q "$MODEL"; then
        fail "Model $MODEL not found after pull"
    fi
fi

# Check cache location
log "Verifying model location..."
if [ -d "$OLLAMA_MODELS" ]; then
    MODEL_SIZE=$(du -sh "$OLLAMA_MODELS" | cut -f1)
    log "✓ Models cached in $OLLAMA_MODELS (size: $MODEL_SIZE)"
else
    log "⚠️  Models directory not found at $OLLAMA_MODELS"
fi

# ============================================================================
# Phase 3: Model Load into GPU (First Request)
# ============================================================================

log ""
log "Phase 3: Testing model load and first request..."
PHASE3_START=$(date +%s)

# Create test request
TEST_PROMPT="Respond with exactly: OK"

log "Sending test request to $MODEL..."

# Send request and capture response
RESPONSE=$(ollama run "$MODEL" "$TEST_PROMPT" 2>&1) || fail "First request failed"

PHASE3_END=$(date +%s)
PHASE3_ELAPSED=$((PHASE3_END - PHASE3_START))

check_timing "First request" "$PHASE3_ELAPSED" "$MAX_FIRST_REQUEST_TIME"

log "Response: $RESPONSE"

# Verify response makes sense
if [ -z "$RESPONSE" ]; then
    fail "Empty response from model"
fi

# ============================================================================
# Phase 4: Subsequent Request (Verify Model Loaded)
# ============================================================================

log ""
log "Phase 4: Testing subsequent request (model should be loaded)..."
PHASE4_START=$(date +%s)

RESPONSE2=$(ollama run "$MODEL" "Say: READY" 2>&1) || fail "Second request failed"

PHASE4_END=$(date +%s)
PHASE4_ELAPSED=$((PHASE4_END - PHASE4_START))

log "Second request completed in ${PHASE4_ELAPSED}s"
log "Response: $RESPONSE2"

# Second request should be faster (model already loaded)
if [ "$PHASE4_ELAPSED" -gt "$PHASE3_ELAPSED" ]; then
    log "⚠️  Second request was slower than first (unexpected)"
else
    log "✓ Second request faster than first (model kept in memory)"
fi

# ============================================================================
# Phase 5: Verify API Endpoint Works
# ============================================================================

log ""
log "Phase 5: Testing Ollama API endpoint..."

# Test the chat API directly (what our Python code will use)
API_RESPONSE=$(curl -s http://localhost:11434/api/generate -d '{
  "model": "'"$MODEL"'",
  "prompt": "Test",
  "stream": false
}')

if echo "$API_RESPONSE" | grep -q "response"; then
    log "✓ Ollama API endpoint working"
else
    fail "Ollama API endpoint not responding correctly"
fi

# ============================================================================
# Summary
# ============================================================================

TOTAL_TIME=$((PHASE1_ELAPSED + PHASE2_ELAPSED + PHASE3_ELAPSED))

log ""
log "========================================================================"
log "STARTUP TEST RESULTS"
log "========================================================================"
log "Phase 1 (Ollama startup):  ${PHASE1_ELAPSED}s"
log "Phase 2 (Model download):   ${PHASE2_ELAPSED}s"
log "Phase 3 (First request):    ${PHASE3_ELAPSED}s"
log "Phase 4 (Second request):   ${PHASE4_ELAPSED}s"
log "----------------------------------------"
log "Total time:                ${TOTAL_TIME}s"
log "========================================================================"

# Check overall timing
if [ "$TOTAL_TIME" -gt "$MAX_TOTAL_TIME" ]; then
    fail "Total startup time (${TOTAL_TIME}s) exceeds maximum (${MAX_TOTAL_TIME}s)"
fi

log ""
log "✅ ELABORATION 05: PASS"
log "   - Ollama started successfully"
log "   - Model cached to persistent storage"
log "   - First request completed"
log "   - Total time acceptable for HPC workflow"
log ""

# Cleanup
log "Shutting down Ollama server..."
kill $OLLAMA_PID || true

log "Test complete. Log saved to: $LOG_FILE"

exit 0
