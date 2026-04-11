# NCI Gadi Setup

## SSH Access

1. Register at [my.nci.org.au](https://my.nci.org.au/) and join a project with GPU allocation.

2. Set up SSH keys:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/gadi
   ssh-copy-id -i ~/.ssh/gadi gadi.nci.org.au
   ```

3. Add to `~/.ssh/config`:
   ```
   Host gadi.nci.org.au
       IdentityFile ~/.ssh/gadi
       User <your-username>
   ```

4. Verify: `ssh gadi.nci.org.au hostname`

## Project Allocation

You need a project with GPU allocation on one of:
- **gpuhopper** (default) -- newer GPUs, higher throughput
- **gpuvolta** -- V100 GPUs, lower throughput but more widely available

Check your allocation: `nci_account -P <project>`

## Module Environment

The PBS job template loads these modules automatically:
```
module load cuda/12.0
module load python3/3.12
```

## /scratch Space

The pipeline uses `/scratch/<project>/llm-discovery/`. Ensure you have sufficient scratch quota:
```bash
quota -s /scratch/<project>
```

Minimum recommended: 50 GB (for model cache + working data).

## HuggingFace Token

Set `HF_TOKEN` in your remote `~/.bashrc`:
```bash
echo 'export HF_TOKEN="hf_your_token_here"' >> ~/.bashrc
```

Verify: `ssh gadi.nci.org.au 'echo $HF_TOKEN'`

## uv Installation

If `uv` is not available system-wide on Gadi:
```bash
ssh gadi.nci.org.au
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify: `ssh gadi.nci.org.au 'which uv'`

## Queue Selection

Pass `--gpu-queue` to select the queue:
```bash
llm-discovery deploy --platform gadi --project <code> --gpu-queue gpuhopper  # default
llm-discovery deploy --platform gadi --project <code> --gpu-queue gpuvolta   # V100s
```
