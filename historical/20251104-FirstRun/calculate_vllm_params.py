#!/usr/bin/env python3
"""
Calculate optimal vLLM parameters based on model size and GPU configuration.

Usage:
    python calculate_vllm_params.py <model_name> [--gpus N]

Output:
    Shell-compatible variable assignments for use in scripts
"""

import argparse
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class ModelConfig:
    """Model configuration with memory requirements."""
    name: str
    params_billion: float
    bytes_per_param: float = 0.5  # FP4 quantization (mxfp4) ≈ 4 bits per param

    @property
    def model_size_gb(self) -> float:
        """Estimated model weight size in GB."""
        return self.params_billion * self.bytes_per_param

    @property
    def min_tensor_parallel(self) -> int:
        """Minimum tensor parallel size needed to fit model on GPUs."""
        # Each H100 has ~70GB usable memory (80GB - overhead)
        # Need to fit model + 20% overhead for activations
        usable_per_gpu = 70
        total_needed = self.model_size_gb * 1.2

        # Find smallest power of 2 >= needed GPUs
        tp_size = 1
        while (usable_per_gpu * tp_size) < total_needed:
            tp_size *= 2

        return tp_size


# Model registry
MODELS = {
    "openai/gpt-oss-20b": ModelConfig("openai/gpt-oss-20b", 20.0),
    "openai/gpt-oss-120b": ModelConfig("openai/gpt-oss-120b", 120.0),
    "openai/gpt-oss-safeguard-20b": ModelConfig("openai/gpt-oss-safeguard-20b", 20.0),
}


def detect_gpu_count() -> int:
    """Detect number of available GPUs."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True
        )
        return len([line for line in result.stdout.strip().split('\n') if line])
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 1


def get_gpu_memory_gb() -> float:
    """Get total GPU memory in GB."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True
        )
        # Get first GPU memory in MB, convert to GB
        memory_mb = float(result.stdout.strip().split('\n')[0])
        return memory_mb / 1024
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 80.0  # Default to H100


def calculate_parallelism(
    model_config: ModelConfig,
    available_gpus: int
) -> tuple[int, int, int]:
    """
    Calculate optimal parallelism configuration.

    Returns:
        (tensor_parallel_size, data_parallel_size, pipeline_parallel_size)

    Strategy:
    1. Use minimum tensor parallelism needed to fit model
    2. Use remaining GPUs for data parallelism (throughput)
    3. Pipeline parallelism = 1 (single node)
    """
    # Minimum tensor parallel needed
    min_tp = model_config.min_tensor_parallel

    if min_tp > available_gpus:
        # Not enough GPUs
        return (available_gpus, 1, 1)

    # Use minimum tensor parallel, rest for data parallel
    tensor_parallel_size = min_tp
    data_parallel_size = available_gpus // tensor_parallel_size
    pipeline_parallel_size = 1  # Single node

    return (tensor_parallel_size, data_parallel_size, pipeline_parallel_size)


def calculate_max_num_seqs(
    model_config: ModelConfig,
    tensor_parallel_size: int,
    gpu_memory_gb: float,
    gpu_memory_utilization: float = 0.95
) -> int:
    """
    Calculate max_num_seqs based on available KV cache memory.

    This is an estimate only. vLLM will apply its own defaults:
    - H100/H200 (≥70GB): default 1024
    - Other GPUs: default 256

    Formula:
    - Model memory per GPU = model_size / tensor_parallel_size
    - Model overhead = 20% for activations, loading
    - Available for KV cache = (total - model - overhead) * utilization
    - KV cache per sequence ≈ 0.5 GB (conservative estimate for typical documents)
    - max_num_seqs = available_kv_cache / kv_cache_per_seq

    Returns:
        Estimated max sequences based on memory. No artificial cap applied.
        vLLM will use its own defaults if this value is not explicitly set.
    """
    # Model memory distributed across tensor parallel GPUs
    model_memory_per_gpu = model_config.model_size_gb / tensor_parallel_size

    # Add 20% overhead for activations, graph capture, etc.
    model_overhead = model_memory_per_gpu * 0.2

    # Available memory for KV cache
    available_memory = (gpu_memory_gb - model_memory_per_gpu - model_overhead) * gpu_memory_utilization

    # Conservative estimate: 0.5 GB per sequence for KV cache
    # This is workload-dependent. Tune empirically based on actual sequence lengths.
    kv_cache_per_seq_gb = 0.5

    max_seqs = int(available_memory / kv_cache_per_seq_gb)

    # Only ensure it's at least 1. No upper cap - let vLLM decide.
    return max(1, max_seqs)


def main():
    parser = argparse.ArgumentParser(description="Calculate optimal vLLM parameters")
    parser.add_argument("model", help="Model name (e.g., openai/gpt-oss-20b)")
    parser.add_argument("--gpus", type=int, help="Override GPU count (default: auto-detect)")
    parser.add_argument("--gpu-memory", type=float, help="GPU memory in GB (default: auto-detect)")
    parser.add_argument("--format", choices=["shell", "json"], default="shell",
                       help="Output format (default: shell)")

    args = parser.parse_args()

    # Get model config
    if args.model not in MODELS:
        print(f"Error: Unknown model {args.model}", file=sys.stderr)
        print(f"Known models: {', '.join(MODELS.keys())}", file=sys.stderr)
        sys.exit(1)

    model_config = MODELS[args.model]

    # Detect or use provided GPU info
    available_gpus = args.gpus if args.gpus else detect_gpu_count()
    gpu_memory_gb = args.gpu_memory if args.gpu_memory else get_gpu_memory_gb()

    # Calculate parallelism
    tensor_parallel_size, data_parallel_size, pipeline_parallel_size = calculate_parallelism(
        model_config,
        available_gpus
    )

    # Calculate max sequences per replica
    max_num_seqs = calculate_max_num_seqs(
        model_config,
        tensor_parallel_size,
        gpu_memory_gb
    )

    # Total effective parallelism
    total_concurrent_seqs = max_num_seqs * data_parallel_size

    # Output based on format
    if args.format == "json":
        import json
        output = {
            "model": model_config.name,
            "model_size_gb": model_config.model_size_gb,
            "available_gpus": available_gpus,
            "gpu_memory_gb": gpu_memory_gb,
            "tensor_parallel_size": tensor_parallel_size,
            "data_parallel_size": data_parallel_size,
            "pipeline_parallel_size": pipeline_parallel_size,
            "max_num_seqs": max_num_seqs,
            "total_concurrent_seqs": total_concurrent_seqs,
            "gpu_memory_utilization": 0.95
        }
        print(json.dumps(output, indent=2))
    else:
        # Shell format (default)
        print(f"# Model: {model_config.name}")
        print(f"# Model size: {model_config.model_size_gb:.1f} GB")
        print(f"# Available GPUs: {available_gpus}")
        print(f"# GPU memory: {gpu_memory_gb:.1f} GB per GPU")
        print(f"# Min tensor parallel: {model_config.min_tensor_parallel}")
        print(f"# Total concurrent sequences: {total_concurrent_seqs}")
        print()
        print(f"export TENSOR_PARALLEL_SIZE={tensor_parallel_size}")
        print(f"export DATA_PARALLEL_SIZE={data_parallel_size}")
        print(f"export PIPELINE_PARALLEL_SIZE={pipeline_parallel_size}")
        print(f"export MAX_NUM_SEQS={max_num_seqs}")
        print(f"export GPU_MEMORY_UTILIZATION=0.95")

        # Warnings
        if tensor_parallel_size > available_gpus:
            print(f"# WARNING: Model requires {tensor_parallel_size} GPUs but only {available_gpus} available",
                  file=sys.stderr)
        elif data_parallel_size > 1:
            print(f"# NOTE: Using {data_parallel_size}x data parallelism for {data_parallel_size}x throughput")


if __name__ == "__main__":
    main()
