# E05 HPC Submission Guide

Fire-and-forget workflow for testing vLLM on HPC H100.

## Quick Start

### Option 1: Via HPC Web Interface

1. Upload `hpc_job.sh` to HPC
2. Submit via web interface job submission form
3. Monitor logs in `/work/20251104-FirstRun/logs/`
4. Retrieve `RESULTS.md` after completion

### Option 2: Via CLI (if you have SSH access)

```bash
# Submit job
sbatch Elaborations/Elaboration05/hpc_job.sh

# Check job status
squeue -u $USER

# Monitor live (while running)
tail -f /work/20251104-FirstRun/logs/e05_vllm_test_*.log

# Check results after completion
cat /work/20251104-FirstRun/logs/e05_results_*.txt
```

---

## What the Job Does (No Manual Intervention Required)

1. **Sets up environment**:
   - Exports `HF_HOME=/work/.cache/huggingface`
   - Exports `VLLM_CACHE_DIR=/work/.cache/vllm`
   - Creates cache directories

2. **Clones/updates repository**:
   - Clones repo to `/work/20251104-FirstRun/`
   - Or pulls latest if already present

3. **Installs dependencies**:
   - Installs `uv` if not present
   - Runs `uv sync` to install vLLM + dependencies

4. **Runs test**:
   - Executes `test_hpc_vllm_startup.py`
   - Measures timing at each phase
   - Tests harmony integration

5. **Saves results**:
   - Creates summary in `/work/20251104-FirstRun/logs/e05_results_<JOBID>.txt`
   - Full logs in `.log` and `.err` files

---

## Customising the Test

### Test 120b Model Instead of 20b

```bash
# Before submitting, edit hpc_job.sh and add:
export TEST_MODEL="openai/gpt-oss-120b"
```

Or via CLI:

```bash
sbatch --export=ALL,TEST_MODEL=openai/gpt-oss-120b Elaborations/Elaboration05/hpc_job.sh
```

### Adjust Tensor Parallelism

```bash
# Before submitting, edit hpc_job.sh and add:
export TENSOR_PARALLEL_SIZE=1  # or 2, 4, etc.
```

### Change Resource Allocation

Edit `hpc_job.sh` SLURM directives:

```bash
#SBATCH --time=02:00:00     # Increase time limit
#SBATCH --mem=256G          # Increase memory
#SBATCH --gres=gpu:h100:4   # Request 4 GPUs instead of 2
```

---

## Interpreting Results

### Success (✅ PASS)

You'll see in the results summary:

```
Status: PASS
```

And in the logs:

```
✅ E05 Test PASSED
```

**Cold start < 10 minutes** = Ready for production

### Partial Success (⚠️ PARTIAL)

```
Status: PARTIAL
```

**Cold start 10-20 minutes** = Workable but slow, may need timeout adjustments

### Failure (❌ FAIL)

```
Status: FAIL
```

Check `.err` log for error details. Common issues:

- Model download timeout (network issues)
- GPU memory exceeded (try smaller model or more GPUs)
- CUDA compatibility issues (driver/CUDA version mismatch)

---

## Expected Timing (Estimates)

### For gpt-oss-20b

- **Model download**: 5-10 min (first run only)
- **Model loading**: 1-2 min
- **CUDA graphs**: 30-60s
- **First inference**: 5-10s
- **Total cold start**: 7-13 min
- **Total warm start**: 2-3 min

### For gpt-oss-120b (if tested)

- **Model download**: 15-25 min (first run only)
- **Model loading**: 2-4 min
- **CUDA graphs**: 1-2 min
- **First inference**: 10-20s
- **Total cold start**: 18-31 min
- **Total warm start**: 4-6 min

---

## Troubleshooting

### Job Won't Start

- Check resource availability: `sinfo` or web interface queue status
- Reduce resource requests in `hpc_job.sh` if queue is busy

### Job Fails Immediately

- Check `.err` log for SLURM errors
- Verify email address in `#SBATCH --mail-user=`
- Ensure `/work/` directory exists and is writable

### Model Download Timeout

- Check HPC network access to HuggingFace
- Pre-download model manually:
  ```bash
  export HF_HOME=/work/.cache/huggingface
  huggingface-cli download openai/gpt-oss-20b
  ```

### GPU Out of Memory

- Try smaller model (20b instead of 120b)
- Reduce `gpu_memory_utilization` to 0.7 or 0.6
- Increase `TENSOR_PARALLEL_SIZE` (spread across more GPUs)

---

## After Test Completion

### 1. Retrieve Results

Download these files from HPC:

- `/work/20251104-FirstRun/logs/e05_vllm_test_<JOBID>.log`
- `/work/20251104-FirstRun/logs/e05_results_<JOBID>.txt`

### 2. Fill in RESULTS.md

Use timing data from logs to complete [RESULTS.md](RESULTS.md) template

### 3. Update ELABORATION_PLAN.md

Mark E05 as ✅ PASS / ⚠️ PARTIAL / ❌ FAIL

### 4. Proceed to Full Refactor

If E05 passes:
- All elaborations validated (E01-E05)
- Ready for production refactor
- Use patterns from E01-E05 in implementation

---

## Important Notes

- **Cache persistence**: Models downloaded to `/work/.cache/` persist across VM restarts
- **Warm starts**: Second and subsequent runs skip model download (2-3 min total)
- **No manual intervention**: Job runs completely unattended after submission
- **Email notifications**: You'll receive email when job completes (if configured)
- **Logs are critical**: Always check logs to understand timing breakdown

---

## Questions Before Submission?

1. **Do I need to modify the repository URL in `hpc_job.sh`?**
   - Yes! Update `git clone https://github.com/YOUR_ORG/20251104-FirstRun.git`

2. **Do I need to configure email notifications?**
   - Optional: Update `#SBATCH --mail-user=YOUR_EMAIL@example.com`

3. **Can I run this locally first?**
   - Yes, but it won't test HPC-specific aspects:
     ```bash
     export HF_HOME=/tmp/cache/huggingface
     export VLLM_CACHE_DIR=/tmp/cache/vllm
     uv run python Elaborations/Elaboration05/test_hpc_vllm_startup.py
     ```

4. **How long will the job take?**
   - First run: 10-30 min (includes download)
   - Subsequent runs: 2-5 min (cached)

5. **What if the job times out?**
   - Increase `#SBATCH --time=` in `hpc_job.sh`
   - Default is 1 hour, which should be sufficient

---

## Ready to Submit!

1. ✅ Update repository URL in `hpc_job.sh`
2. ✅ Update email address (optional)
3. ✅ Review resource requests (GPUs, memory, time)
4. ✅ Submit job via web interface or CLI
5. ✅ Wait for completion (check logs)
6. ✅ Fill in RESULTS.md with findings
7. ✅ Proceed to full refactor if PASS!

Good luck! 🚀
