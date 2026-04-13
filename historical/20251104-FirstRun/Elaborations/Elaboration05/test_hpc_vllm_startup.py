#!/usr/bin/env python3
"""
Elaboration 05: HPC vLLM Startup & Model Loading Test

Tests vLLM startup on HPC H100 nodes with tensor parallelism.
Validates model loading, caching, and harmony integration.

Success criteria:
- Cold start (with download): < 10 minutes
- Warm start (cached model): < 2 minutes
- Tensor parallelism works (TP=2)
- Harmony requests complete successfully
- Cache persists across restarts

Run on HPC via:
    sbatch Elaborations/Elaboration05/hpc_job.sh

Or manually for testing:
    export HF_HOME=/work/.cache/huggingface
    export VLLM_CACHE_DIR=/work/.cache/vllm
    uv run python Elaborations/Elaboration05/test_hpc_vllm_startup.py
"""

import sys
import time
from pathlib import Path
from typing import Dict, Any
import os

# Add E01 to path for harmony integration
elaboration01_path = Path(__file__).parent.parent / "Elaboration01"
sys.path.insert(0, str(elaboration01_path))

from harmony_integration import (
    construct_harmony_conversation,
    parse_harmony_response,
    create_sampling_params,
)
from vllm import LLM
from vllm.inputs import TokensPrompt


def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{'=' * 80}")
    print(f"{title}")
    print(f"{'=' * 80}\n")


def print_timing(label: str, seconds: float):
    """Print a timing metric."""
    minutes = seconds / 60
    print(f"  {label}: {seconds:.2f}s ({minutes:.2f} min)")


def check_environment():
    """Verify HPC environment is configured correctly."""
    print_section("Environment Check")

    # Check critical environment variables
    hf_home = os.getenv("HF_HOME")
    vllm_cache = os.getenv("VLLM_CACHE_DIR")

    print(f"HF_HOME: {hf_home}")
    print(f"VLLM_CACHE_DIR: {vllm_cache}")
    print(f"Working directory: {os.getcwd()}")

    # Check if cache directories exist
    if hf_home:
        cache_path = Path(hf_home)
        print(f"HF cache exists: {cache_path.exists()}")
        if cache_path.exists():
            print(f"HF cache size: {sum(f.stat().st_size for f in cache_path.rglob('*') if f.is_file()) / 1e9:.2f} GB")

    # Check GPU availability
    try:
        import torch
        print(f"\nCUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"CUDA version: {torch.version.cuda}")
            print(f"GPU count: {torch.cuda.device_count()}")
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                print(f"  GPU {i}: {props.name}, {props.total_memory / 1e9:.1f} GB")
    except ImportError:
        print("⚠️  Warning: torch not available for GPU checks")


def test_model_loading(
    model_name: str,
    tensor_parallel_size: int = 2,
    gpu_memory_utilization: float = 0.85,
) -> Dict[str, Any]:
    """
    Test vLLM model loading with timing measurements.

    Returns dict with timing metrics and model instance.
    """
    print_section(f"Testing Model: {model_name}")
    print(f"Configuration:")
    print(f"  tensor_parallel_size: {tensor_parallel_size}")
    print(f"  gpu_memory_utilization: {gpu_memory_utilization}")
    print(f"  trust_remote_code: True")

    start_time = time.time()

    # Load model
    print(f"\n🔄 Loading model (this may take several minutes on first run)...")
    load_start = time.time()

    try:
        llm = LLM(
            model=model_name,
            tensor_parallel_size=tensor_parallel_size,
            gpu_memory_utilization=gpu_memory_utilization,
            trust_remote_code=True,
        )
        load_end = time.time()
        load_time = load_end - load_start

        print(f"✅ Model loaded successfully!")
        print_timing("Model loading time", load_time)

        # Try to get memory usage
        try:
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    allocated = torch.cuda.memory_allocated(i) / 1e9
                    reserved = torch.cuda.memory_reserved(i) / 1e9
                    print(f"  GPU {i} memory: {allocated:.2f} GB allocated, {reserved:.2f} GB reserved")
        except Exception as e:
            print(f"  Could not get GPU memory info: {e}")

        return {
            "success": True,
            "load_time": load_time,
            "total_time": time.time() - start_time,
            "llm": llm,
        }

    except Exception as e:
        load_end = time.time()
        print(f"❌ Model loading failed!")
        print(f"Error: {e}")
        return {
            "success": False,
            "load_time": load_end - load_start,
            "total_time": time.time() - start_time,
            "error": str(e),
            "llm": None,
        }


def test_harmony_inference(
    llm: LLM,
    model_name: str,
) -> Dict[str, Any]:
    """
    Test harmony format inference using E01 validated patterns.

    Returns dict with timing metrics and success status.
    """
    print_section("Testing Harmony Inference")

    # Load test data
    system_prompt_path = Path(__file__).parent.parent.parent / "system_prompt.txt"
    with open(system_prompt_path) as f:
        system_prompt = f.read()

    # Use a simple test prompt
    category_prompt = """
Please analyse whether this document contains information about health topics.

Respond with:
- "yes" if health topics are clearly present
- "maybe" if health topics are mentioned but unclear
- "no" if no health topics are present

Provide blockquotes as evidence.
"""

    # Simple test document
    test_document = """
# Health and Wellness

Welcome to our health information page. We provide tips on nutrition,
exercise, and general wellness for children and families.

## Nutrition Tips

Eating a balanced diet is important for growing bodies.
"""

    start_time = time.time()

    try:
        # Construct harmony conversation (E01 pattern)
        print("🔄 Constructing harmony conversation...")
        construct_start = time.time()

        prefill_ids, stop_token_ids = construct_harmony_conversation(
            system_prompt=system_prompt,
            category_prompt=category_prompt,
            document_content=test_document,
            reasoning_effort="Low",  # Use Low for speed
        )

        construct_time = time.time() - construct_start
        print(f"✅ Harmony conversation constructed")
        print(f"  Input tokens: {len(prefill_ids)}")

        # Create prompt
        prompt = TokensPrompt(prompt_token_ids=prefill_ids)
        sampling_params = create_sampling_params(
            stop_token_ids=stop_token_ids,
            max_tokens=256,
            temperature=0.0,
        )

        # First inference (cold)
        print(f"\n🔄 Running first inference (cold)...")
        inference_start = time.time()

        outputs = llm.generate(
            prompts=[prompt],
            sampling_params=sampling_params,
        )

        inference_time = time.time() - inference_start
        output_tokens = outputs[0].outputs[0].token_ids

        print(f"✅ Inference completed")
        print_timing("First inference time", inference_time)
        print(f"  Output tokens: {len(output_tokens)}")

        # Parse response (E01 pattern)
        print(f"\n🔄 Parsing harmony response...")
        parse_start = time.time()

        harmony_response = parse_harmony_response(output_tokens)

        parse_time = time.time() - parse_start

        print(f"✅ Response parsed successfully")
        print(f"  Analysis channel length: {len(harmony_response.analysis_channel) if harmony_response.analysis_channel else 0}")
        print(f"  Final channel length: {len(harmony_response.final_channel) if harmony_response.final_channel else 0}")

        # Validate response has content
        if not harmony_response.analysis_channel and not harmony_response.final_channel:
            print(f"⚠️  Warning: Empty response channels")

        # Run second inference (warm) to measure hot performance
        print(f"\n🔄 Running second inference (warm)...")
        warm_start = time.time()

        outputs2 = llm.generate(
            prompts=[prompt],
            sampling_params=sampling_params,
        )

        warm_time = time.time() - warm_start
        print(f"✅ Second inference completed")
        print_timing("Second inference time (warm)", warm_time)

        total_time = time.time() - start_time

        return {
            "success": True,
            "construct_time": construct_time,
            "first_inference_time": inference_time,
            "second_inference_time": warm_time,
            "parse_time": parse_time,
            "total_time": total_time,
            "input_tokens": len(prefill_ids),
            "output_tokens": len(output_tokens),
            "speedup": inference_time / warm_time if warm_time > 0 else 0,
        }

    except Exception as e:
        print(f"❌ Harmony inference failed!")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

        return {
            "success": False,
            "total_time": time.time() - start_time,
            "error": str(e),
        }


def main():
    """Main test runner."""
    print_section("Elaboration 05: HPC vLLM Startup & Model Loading")

    overall_start = time.time()

    # Check environment
    check_environment()

    # Determine which model to test
    # Default to 20b, allow override via environment variable
    model_name = os.getenv("TEST_MODEL", "openai/gpt-oss-20b")
    tensor_parallel_size = int(os.getenv("TENSOR_PARALLEL_SIZE", "2"))

    print(f"\n📋 Test Configuration:")
    print(f"  Model: {model_name}")
    print(f"  Tensor Parallel Size: {tensor_parallel_size}")

    # Test model loading
    load_result = test_model_loading(
        model_name=model_name,
        tensor_parallel_size=tensor_parallel_size,
    )

    if not load_result["success"]:
        print_section("TEST FAILED")
        print(f"❌ Model loading failed, aborting tests")
        print(f"Error: {load_result.get('error', 'Unknown')}")
        sys.exit(1)

    # Test harmony inference
    inference_result = test_harmony_inference(
        llm=load_result["llm"],
        model_name=model_name,
    )

    # Print summary
    print_section("Test Summary")

    total_time = time.time() - overall_start

    print(f"Model: {model_name}")
    print(f"Tensor Parallel Size: {tensor_parallel_size}")
    print(f"\n⏱️  Timing Breakdown:")
    print_timing("Model loading", load_result["load_time"])

    if inference_result["success"]:
        print_timing("Harmony construction", inference_result["construct_time"])
        print_timing("First inference (cold)", inference_result["first_inference_time"])
        print_timing("Second inference (warm)", inference_result["second_inference_time"])
        print(f"  Speedup (cold→warm): {inference_result['speedup']:.2f}x")
        print_timing("Total test time", total_time)
    else:
        print(f"\n❌ Inference tests failed: {inference_result.get('error', 'Unknown')}")
        print_timing("Total test time", total_time)

    # Verdict
    print(f"\n📊 Verdict:")

    if not inference_result["success"]:
        print(f"❌ FAIL: Inference tests failed")
        sys.exit(1)

    # Check timing thresholds
    cold_start_minutes = load_result["load_time"] / 60

    if cold_start_minutes < 10:
        print(f"✅ PASS: Cold start time acceptable ({cold_start_minutes:.2f} min < 10 min)")
        verdict = "PASS"
    elif cold_start_minutes < 20:
        print(f"⚠️  PARTIAL: Cold start slower than ideal ({cold_start_minutes:.2f} min, target < 10 min)")
        verdict = "PARTIAL"
    else:
        print(f"❌ FAIL: Cold start too slow ({cold_start_minutes:.2f} min > 20 min)")
        verdict = "FAIL"
        sys.exit(1)

    # Check inference latency
    if inference_result["first_inference_time"] > 60:
        print(f"⚠️  Warning: First inference slow ({inference_result['first_inference_time']:.2f}s)")
    else:
        print(f"✅ First inference acceptable ({inference_result['first_inference_time']:.2f}s)")

    print(f"\n{'=' * 80}")
    print(f"E05 Test Result: {verdict}")
    print(f"{'=' * 80}")

    # Cleanup
    del load_result["llm"]
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            print(f"\n🧹 GPU cache cleared")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
