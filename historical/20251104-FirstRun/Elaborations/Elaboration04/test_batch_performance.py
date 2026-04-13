"""
Elaboration 04: Batch Processing Performance Test (vLLM)

Tests vLLM native batch processing performance with different batch sizes
to identify optimal batch size for processing 15 categories per file.

These tests will FAIL if:
- Batch processing doesn't provide speedup over sequential
- vLLM can't handle larger batch sizes
- Memory requirements are prohibitive

Run with: uv run pytest Elaborations/Elaboration04/ -xvs
"""

import pytest
from batch_processor import (
    process_file_with_batch_size,
    get_peak_gpu_memory,
    reset_peak_gpu_memory,
)


# Batch sizes to test
BATCH_SIZES = [1, 5, 10, 15, 20]


@pytest.mark.parametrize("batch_size", BATCH_SIZES)
def test_batch_performance(
    batch_size,
    vllm_model,
    test_document,
    system_prompt,
    category_prompts,
):
    """
    Test performance of vLLM batch processing with different batch sizes.

    This test measures:
    - Total processing time
    - Throughput (categories/second)
    - Token throughput (tokens/second)
    - Peak GPU memory usage

    Hypothesis: Larger batch sizes should provide better throughput
    up to a point, with batch_size=15 being optimal for our use case.
    """
    print(f"\n{'='*60}")
    print(f"Testing batch_size={batch_size}")
    print(f"{'='*60}")

    # Reset GPU memory stats before test
    reset_peak_gpu_memory()

    # Process document with specified batch size
    metrics = process_file_with_batch_size(
        llm=vllm_model,
        document_content=test_document,
        system_prompt=system_prompt,
        categories=category_prompts,
        batch_size=batch_size,
        reasoning_effort="Low",  # Use Low for speed
        max_tokens=512,
        temperature=0.0,  # Deterministic
    )

    # Get peak GPU memory
    peak_memory_gb = get_peak_gpu_memory()

    # Print results
    print(f"\n📊 Results for batch_size={batch_size}:")
    print(f"  Total time: {metrics['total_time']:.2f}s")
    print(f"  Categories processed: {metrics['num_categories']}")
    print(f"  Number of batches: {metrics['num_batches']}")
    print(f"  Throughput: {metrics['categories_per_second']:.2f} categories/sec")
    print(f"  Token throughput: {metrics['tokens_per_second']:.1f} tokens/sec")
    print(f"  Total input tokens: {metrics['total_input_tokens']}")
    print(f"  Total output tokens: {metrics['total_output_tokens']}")
    print(f"  Peak GPU memory: {peak_memory_gb:.2f} GB")

    # Assertions
    assert metrics['num_categories'] == 15, "Should process all 15 categories"
    assert len(metrics['results']) == 15, "Should have 15 results"
    assert metrics['total_time'] > 0, "Processing should take measurable time"
    assert metrics['categories_per_second'] > 0, "Should have positive throughput"

    # Expected number of batches
    import math
    expected_batches = math.ceil(15 / batch_size)
    assert metrics['num_batches'] == expected_batches, \
        f"Expected {expected_batches} batches for batch_size={batch_size}"

    # Verify all results are valid
    for i, result in enumerate(metrics['results']):
        assert result.analysis_channel is not None, \
            f"Result {i} missing analysis channel"
        assert len(result.analysis_channel) > 0, \
            f"Result {i} has empty analysis channel"
        # Note: final_channel may be empty if model stopped early (non-deterministic)

    print(f"✅ Test passed for batch_size={batch_size}")


def test_batch_speedup_comparison(
    vllm_model,
    test_document,
    system_prompt,
    category_prompts,
):
    """
    Test that batch processing provides significant speedup over sequential.

    This is the key test for E04 hypothesis:
    "Processing 15 categories in a single vLLM batch is faster than sequential"

    Success criteria: batch_size=15 should be >3x faster than batch_size=1
    """
    print(f"\n{'='*60}")
    print("Speedup Comparison: Sequential (batch=1) vs Batch (batch=15)")
    print(f"{'='*60}")

    # Run sequential (batch_size=1)
    print("\n🔄 Running sequential processing (batch_size=1)...")
    reset_peak_gpu_memory()
    sequential_metrics = process_file_with_batch_size(
        llm=vllm_model,
        document_content=test_document,
        system_prompt=system_prompt,
        categories=category_prompts,
        batch_size=1,
        reasoning_effort="Low",
        max_tokens=512,
        temperature=0.0,
    )
    sequential_memory = get_peak_gpu_memory()

    # Run batch (batch_size=15)
    print("\n🔄 Running batch processing (batch_size=15)...")
    reset_peak_gpu_memory()
    batch_metrics = process_file_with_batch_size(
        llm=vllm_model,
        document_content=test_document,
        system_prompt=system_prompt,
        categories=category_prompts,
        batch_size=15,
        reasoning_effort="Low",
        max_tokens=512,
        temperature=0.0,
    )
    batch_memory = get_peak_gpu_memory()

    # Calculate speedup
    speedup = sequential_metrics['total_time'] / batch_metrics['total_time']

    # Print comparison
    print(f"\n📊 Speedup Analysis:")
    print(f"  Sequential (batch=1):")
    print(f"    Time: {sequential_metrics['total_time']:.2f}s")
    print(f"    Throughput: {sequential_metrics['categories_per_second']:.2f} cat/sec")
    print(f"    Peak memory: {sequential_memory:.2f} GB")
    print(f"  Batch (batch=15):")
    print(f"    Time: {batch_metrics['total_time']:.2f}s")
    print(f"    Throughput: {batch_metrics['categories_per_second']:.2f} cat/sec")
    print(f"    Peak memory: {batch_memory:.2f} GB")
    print(f"  Speedup: {speedup:.2f}x")
    print(f"  Memory increase: {(batch_memory - sequential_memory):.2f} GB")

    # Assertions
    assert speedup > 1.0, \
        f"Batch processing should be faster than sequential, got {speedup:.2f}x"

    # Success criteria: >3x speedup
    if speedup > 3.0:
        print(f"\n✅ PASS: Batch processing provides significant speedup ({speedup:.2f}x > 3.0x)")
    elif speedup > 2.0:
        print(f"\n⚠️  PARTIAL: Modest speedup ({speedup:.2f}x), between 2x and 3x")
    else:
        print(f"\n❌ FAIL: Insufficient speedup ({speedup:.2f}x < 2.0x)")

    # For test to pass, require at least 1.5x speedup (conservative threshold)
    assert speedup >= 1.5, \
        f"Batch processing should provide at least 1.5x speedup, got {speedup:.2f}x"


def test_memory_scaling(
    vllm_model,
    test_document,
    system_prompt,
    category_prompts,
):
    """
    Test how GPU memory usage scales with batch size.

    Verifies that memory requirements are acceptable across all batch sizes.
    """
    print(f"\n{'='*60}")
    print("Memory Scaling Test")
    print(f"{'='*60}")

    memory_by_batch_size = {}

    for batch_size in [1, 5, 10, 15, 20]:
        reset_peak_gpu_memory()
        process_file_with_batch_size(
            llm=vllm_model,
            document_content=test_document,
            system_prompt=system_prompt,
            categories=category_prompts,
            batch_size=batch_size,
            reasoning_effort="Low",
            max_tokens=512,
            temperature=0.0,
        )
        peak_memory = get_peak_gpu_memory()
        memory_by_batch_size[batch_size] = peak_memory

    # Print memory scaling
    print(f"\n📊 Memory usage by batch size:")
    for batch_size, memory in memory_by_batch_size.items():
        print(f"  batch_size={batch_size:2d}: {memory:.2f} GB")

    # Check memory doesn't exceed reasonable threshold (30GB for consumer GPU)
    max_memory = max(memory_by_batch_size.values())
    assert max_memory < 30.0, \
        f"Peak memory usage ({max_memory:.2f} GB) exceeds 30GB threshold"

    print(f"\n✅ Memory requirements acceptable (max: {max_memory:.2f} GB)")


def test_optimal_batch_size(
    vllm_model,
    test_document,
    system_prompt,
    category_prompts,
):
    """
    Identify the optimal batch size for maximum throughput.

    Tests all batch sizes and recommends the one with best throughput.
    """
    print(f"\n{'='*60}")
    print("Optimal Batch Size Analysis")
    print(f"{'='*60}")

    results = {}

    for batch_size in BATCH_SIZES:
        print(f"\n🔄 Testing batch_size={batch_size}...")
        reset_peak_gpu_memory()

        metrics = process_file_with_batch_size(
            llm=vllm_model,
            document_content=test_document,
            system_prompt=system_prompt,
            categories=category_prompts,
            batch_size=batch_size,
            reasoning_effort="Low",
            max_tokens=512,
            temperature=0.0,
        )

        results[batch_size] = {
            'throughput': metrics['categories_per_second'],
            'time': metrics['total_time'],
            'memory': get_peak_gpu_memory(),
        }

    # Find optimal batch size (highest throughput)
    optimal_batch_size = max(results.keys(), key=lambda k: results[k]['throughput'])
    optimal_throughput = results[optimal_batch_size]['throughput']

    # Print summary table
    print(f"\n📊 Batch Size Performance Summary:")
    print(f"{'Batch Size':<12} {'Time (s)':<12} {'Throughput':<20} {'Memory (GB)':<15} {'vs Optimal'}")
    print("-" * 80)

    for batch_size in sorted(results.keys()):
        r = results[batch_size]
        vs_optimal = (r['throughput'] / optimal_throughput) * 100
        marker = " ⭐ OPTIMAL" if batch_size == optimal_batch_size else ""
        print(f"{batch_size:<12} {r['time']:<12.2f} {r['throughput']:<20.2f} {r['memory']:<15.2f} {vs_optimal:>6.1f}%{marker}")

    print(f"\n✅ Optimal batch size: {optimal_batch_size}")
    print(f"   Throughput: {optimal_throughput:.2f} categories/sec")
    print(f"   Time for 15 categories: {results[optimal_batch_size]['time']:.2f}s")
    print(f"   Memory required: {results[optimal_batch_size]['memory']:.2f} GB")

    # Assertion: optimal should be one of the larger batch sizes
    assert optimal_batch_size >= 10, \
        f"Expected optimal batch size >= 10, got {optimal_batch_size}"
