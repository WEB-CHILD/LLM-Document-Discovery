#!/usr/bin/env python3
"""
Manual test runner for Elaboration 04 with tqdm progress bars.

Run this instead of pytest for long-running tests where you want progress visibility.

Usage:
    uv run python Elaborations/Elaboration04/run_manual.py
"""

import sys
from pathlib import Path
import yaml
from vllm import LLM

# Add E01 to path
elaboration01_path = Path(__file__).parent.parent / "Elaboration01"
sys.path.insert(0, str(elaboration01_path))

from batch_processor import process_file_with_batch_size, reset_peak_gpu_memory, get_peak_gpu_memory


def load_system_prompt():
    """Load system prompt from root directory."""
    system_prompt_path = Path(__file__).parent.parent.parent / "system_prompt.txt"
    with open(system_prompt_path) as f:
        return f.read()


def load_category_prompts():
    """Load all 15 category prompts from POC-prompts/."""
    prompts_dir = Path(__file__).parent.parent.parent / "POC-prompts"
    yaml_files = sorted(prompts_dir.glob("*.yaml"))

    categories = []
    for yaml_file in yaml_files:
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
            categories.append({
                "name": yaml_file.stem,
                "prompt": data["prompt"],
            })

    assert len(categories) == 15, f"Expected 15 categories, found {len(categories)}"
    return categories


def select_test_files(num_files=5):
    """Select representative markdown files for testing."""
    input_dir = Path(__file__).parent.parent.parent / "input"
    all_files = list(input_dir.rglob("*.md"))

    if len(all_files) == 0:
        raise FileNotFoundError("No markdown files found in input/ directory")

    # Sort by size and select files from the middle
    files_by_size = sorted(all_files, key=lambda f: f.stat().st_size)
    middle_index = len(files_by_size) // 2
    start_index = max(0, middle_index - 2)
    selected_files = files_by_size[start_index:start_index + num_files]

    if len(selected_files) < num_files:
        selected_files = files_by_size[:num_files]

    print(f"\n📄 Selected {len(selected_files)} test files:")
    for f in selected_files:
        size_kb = f.stat().st_size / 1024
        print(f"  - {f.name}: {size_kb:.1f} KB")

    return selected_files[:num_files]


def main():
    print("=" * 80)
    print("Elaboration 04: Batch Processing Performance Test (Manual Run)")
    print("=" * 80)

    # Load model (one-time cost)
    print("\n🔄 Loading vLLM model (this takes ~20 seconds)...")
    llm = LLM(
        model="openai/gpt-oss-20b",
        gpu_memory_utilization=0.85,
        trust_remote_code=True,
    )
    print("✅ Model loaded successfully")

    # Load test data
    system_prompt = load_system_prompt()
    categories = load_category_prompts()
    test_files = select_test_files(num_files=5)

    # Load first test file
    with open(test_files[0]) as f:
        test_document = f.read()

    print(f"\n📋 Test configuration:")
    print(f"  Model: openai/gpt-oss-20b")
    print(f"  Categories: {len(categories)}")
    print(f"  Reasoning effort: Low")
    print(f"  Max tokens: 512")
    print(f"  Temperature: 0.0")

    # Run tests for each batch size
    BATCH_SIZES = [1, 5, 10, 15, 20]
    results = {}

    print(f"\n{'=' * 80}")
    print("Running batch size comparison tests...")
    print(f"{'=' * 80}")

    for batch_size in BATCH_SIZES:
        print(f"\n🔄 Testing batch_size={batch_size}...")
        reset_peak_gpu_memory()

        metrics = process_file_with_batch_size(
            llm=llm,
            document_content=test_document,
            system_prompt=system_prompt,
            categories=categories,
            batch_size=batch_size,
            reasoning_effort="Low",
            max_tokens=512,
            temperature=0.0,
            show_progress=True,  # Enable tqdm progress bar
        )

        peak_memory_gb = get_peak_gpu_memory()

        results[batch_size] = {
            'time': metrics['total_time'],
            'throughput': metrics['categories_per_second'],
            'memory': peak_memory_gb,
            'metrics': metrics,
        }

        # Print results
        print(f"\n📊 Results for batch_size={batch_size}:")
        print(f"  Total time: {metrics['total_time']:.2f}s")
        print(f"  Throughput: {metrics['categories_per_second']:.2f} categories/sec")
        print(f"  Token throughput: {metrics['tokens_per_second']:.1f} tokens/sec")
        print(f"  Peak GPU memory: {peak_memory_gb:.2f} GB")

    # Summary table
    print(f"\n{'=' * 80}")
    print("SUMMARY: Batch Size Performance Comparison")
    print(f"{'=' * 80}\n")

    # Find optimal
    optimal_batch_size = max(results.keys(), key=lambda k: results[k]['throughput'])
    optimal_throughput = results[optimal_batch_size]['throughput']

    print(f"{'Batch Size':<12} {'Time (s)':<12} {'Throughput':<20} {'Memory (GB)':<15} {'vs Optimal'}")
    print("-" * 80)

    for batch_size in sorted(results.keys()):
        r = results[batch_size]
        vs_optimal = (r['throughput'] / optimal_throughput) * 100
        marker = " ⭐ OPTIMAL" if batch_size == optimal_batch_size else ""
        print(f"{batch_size:<12} {r['time']:<12.2f} {r['throughput']:<20.2f} {r['memory']:<15.2f} {vs_optimal:>6.1f}%{marker}")

    # Speedup analysis
    baseline_time = results[1]['time']
    batch15_time = results[15]['time']
    speedup = baseline_time / batch15_time

    print(f"\n{'=' * 80}")
    print(f"SPEEDUP ANALYSIS: Sequential (batch=1) vs Batch (batch=15)")
    print(f"{'=' * 80}\n")
    print(f"  Sequential time: {baseline_time:.2f}s")
    print(f"  Batch time: {batch15_time:.2f}s")
    print(f"  Speedup: {speedup:.2f}x")

    if speedup > 3.0:
        print(f"\n✅ PASS: Batch processing provides significant speedup ({speedup:.2f}x > 3.0x)")
    elif speedup > 2.0:
        print(f"\n⚠️  PARTIAL: Modest speedup ({speedup:.2f}x), between 2x and 3x")
    else:
        print(f"\n❌ INSUFFICIENT: Speedup below 2x ({speedup:.2f}x)")

    print(f"\n{'=' * 80}")
    print("✅ Manual test run complete!")
    print(f"{'=' * 80}")

    # Cleanup
    del llm
    try:
        import torch
        torch.cuda.empty_cache()
    except ImportError:
        pass


if __name__ == "__main__":
    main()
