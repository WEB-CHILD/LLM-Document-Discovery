# DeiC UCloud Setup

## Account

1. Register at [cloud.sdu.dk](https://cloud.sdu.dk/) using your institutional login via DeiC.
2. Request GPU resource allocation through your institution's DeiC contact.

## Container Configuration

1. In UCloud, create a new **Terminal App** job.
2. Select resources:
   - GPU: H100, 4 GPUs
   - CPU: 48 cores (recommended)
   - Memory: 380 GB (recommended)
3. Mount `/work/llm-discovery` as the working directory.

## Code Transfer

UCloud does not support SSH-based deployment. Transfer code via:

1. **UCloud Drive**: Upload the repository to your UCloud drive, then mount it.
2. **Git**: Clone the repository inside the container terminal.

```bash
cd /work
git clone <repo-url> llm-discovery
cd llm-discovery
```

## HuggingFace Token

Set `HF_TOKEN` in the container environment:
```bash
export HF_TOKEN="hf_your_token_here"
```

For persistent configuration, add it to the job's environment variables in the UCloud web interface.

## Running the Pipeline

Inside the UCloud terminal:
```bash
cd /work/llm-discovery
bash scripts/process_corpus.sh
```

Or use the batch script:
```bash
bash hpc/ucloud_batch.sh
```

## /work Directory

- Pipeline writes to `/work/llm-discovery/corpus.db`
- Model cache stored in `~/.cache/huggingface/` (persists within the container session)
- Results in `/work/llm-discovery/out/`
