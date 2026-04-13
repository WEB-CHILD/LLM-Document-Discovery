MODEL="openai/gpt-oss-safeguard-20b" bash start_server_hpc.sh --tp 2 256
MODEL="openai/gpt-oss-safeguard-20b" CONCURRENCY=270 DB_PATH=corpus-safeguard-20b.db bash runner.sh

# 120b

export MODEL="openai/gpt-oss-120b"
export VLLM_BASE="/tmp/scratch"
export HF_HOME="$VLLM_BASE"
export HUGGINGFACE_HUB_CACHE="$VLLM_BASE/hub"
export VLLM_CACHE_ROOT="$VLLM_BASE/cache"
export UV_TORCH_BACKEND=auto
export UV_LINK_MODE=copy
MODEL="openai/gpt-oss-120b" bash start_server_hpc.sh --tp 2 64

MODEL="openai/gpt-oss-120b" CONCURRENCY=66 LIMIT=200 DB_PATH=corpus-120b.db bash runner.sh
