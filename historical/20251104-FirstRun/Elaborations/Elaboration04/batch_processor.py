"""
Batch processing helper for Elaboration 04.

Implements vLLM batch processing with configurable batch sizes.
"""

import sys
from pathlib import Path
import time
from typing import List, Dict, Any, Optional
from vllm import LLM, SamplingParams
from vllm.inputs import TokensPrompt

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

# Import harmony integration from E01
elaboration01_path = Path(__file__).parent.parent / "Elaboration01"
sys.path.insert(0, str(elaboration01_path))

from harmony_integration import (
    construct_harmony_conversation,
    parse_harmony_response,
    create_sampling_params,
)


def process_file_with_batch_size(
    llm: LLM,
    document_content: str,
    system_prompt: str,
    categories: List[Dict[str, str]],
    batch_size: int,
    reasoning_effort: str = "Low",
    max_tokens: int = 512,
    temperature: float = 0.0,
    show_progress: bool = False,
) -> Dict[str, Any]:
    """
    Process all categories for a document with specified batch size.

    Args:
        llm: vLLM LLM instance
        document_content: Markdown document text
        system_prompt: System prompt text
        categories: List of category dicts with 'name' and 'prompt' keys
        batch_size: Number of prompts to batch together (1 = sequential)
        reasoning_effort: "Low", "Medium", or "High"
        max_tokens: Maximum tokens per response
        temperature: Sampling temperature (0.0 = deterministic)

    Returns:
        Dict with metrics:
            - total_time: Total processing time in seconds
            - num_categories: Number of categories processed
            - num_batches: Number of vLLM calls made
            - results: List of parsed HarmonyResponse objects
            - categories_per_second: Throughput metric
            - total_input_tokens: Total input tokens across all prompts
            - total_output_tokens: Total output tokens across all responses
    """
    start_time = time.time()

    # Construct all harmony conversations
    all_prefills = []
    all_stop_tokens = []

    for category in categories:
        prefill_ids, stop_token_ids = construct_harmony_conversation(
            system_prompt=system_prompt,
            category_prompt=category["prompt"],
            document_content=document_content,
            reasoning_effort=reasoning_effort,
        )
        all_prefills.append(prefill_ids)
        all_stop_tokens.append(stop_token_ids)

    # Create batches
    batches = []
    for i in range(0, len(all_prefills), batch_size):
        batch_prefills = all_prefills[i:i + batch_size]
        # Assume all categories use same stop tokens (they should for harmony)
        batch_stop_tokens = all_stop_tokens[i]

        batches.append({
            "prefills": batch_prefills,
            "stop_tokens": batch_stop_tokens,
        })

    # Process each batch
    all_results = []
    total_input_tokens = 0
    total_output_tokens = 0

    # Create progress bar if requested and available
    batch_iterator = batches
    if show_progress and TQDM_AVAILABLE:
        batch_iterator = tqdm(batches, desc="Processing batches", unit="batch")

    for batch in batch_iterator:
        # Create TokensPrompt instances
        prompts = [
            TokensPrompt(prompt_token_ids=prefill_ids)
            for prefill_ids in batch["prefills"]
        ]

        # Create sampling params
        sampling_params = create_sampling_params(
            stop_token_ids=batch["stop_tokens"],
            max_tokens=max_tokens,
            temperature=temperature,
        )

        # Single vLLM call for this batch
        outputs = llm.generate(
            prompts=prompts,
            sampling_params=sampling_params,
        )

        # Parse responses
        for output, prefill_ids in zip(outputs, batch["prefills"]):
            output_tokens = output.outputs[0].token_ids
            harmony_response = parse_harmony_response(output_tokens)
            all_results.append(harmony_response)

            # Track token counts
            total_input_tokens += len(prefill_ids)
            total_output_tokens += len(output_tokens)

    end_time = time.time()
    total_time = end_time - start_time

    return {
        "total_time": total_time,
        "num_categories": len(categories),
        "num_batches": len(batches),
        "results": all_results,
        "categories_per_second": len(categories) / total_time if total_time > 0 else 0,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "tokens_per_second": (total_input_tokens + total_output_tokens) / total_time if total_time > 0 else 0,
    }


def get_gpu_memory_used() -> float:
    """
    Get current GPU memory usage in GB.

    Returns 0.0 if torch not available.
    """
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.memory_allocated() / 1e9  # Convert to GB
    except ImportError:
        pass
    return 0.0


def get_peak_gpu_memory() -> float:
    """
    Get peak GPU memory usage in GB since last reset.

    Returns 0.0 if torch not available.
    """
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.max_memory_allocated() / 1e9  # Convert to GB
    except ImportError:
        pass
    return 0.0


def reset_peak_gpu_memory():
    """Reset peak GPU memory stats."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except ImportError:
        pass
