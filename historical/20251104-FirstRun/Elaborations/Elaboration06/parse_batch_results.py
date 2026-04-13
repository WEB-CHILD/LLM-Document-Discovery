"""
Parse vLLM batch results and validate output.

This script:
1. Reads the batch results JSONL
2. Extracts reasoning and JSON from each response
3. Validates the structure
4. Reports statistics
"""

import json
import sys
from pathlib import Path
from typing import Dict, List


def extract_json_from_text(text: str) -> dict | None:
    """
    Extract JSON from text that may contain reasoning followed by JSON.

    Args:
        text: Response text

    Returns:
        Parsed JSON dict or None if parsing failed
    """
    # Look for JSON block
    if "{" not in text or "}" not in text:
        return None

    # Try to extract last JSON object
    json_start = text.rfind("{")
    json_end = text.rfind("}") + 1

    if json_start >= json_end:
        return None

    try:
        json_str = text[json_start:json_end]
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


def extract_reasoning(text: str, json_start_pos: int) -> str:
    """
    Extract reasoning text that appears before JSON.

    Args:
        text: Full response text
        json_start_pos: Position where JSON starts

    Returns:
        Reasoning text (everything before JSON)
    """
    return text[:json_start_pos].strip()


def parse_batch_result(result: dict) -> dict:
    """
    Parse a single batch result.

    Args:
        result: Batch result dict

    Returns:
        Parsed result with extracted fields
    """
    custom_id = result["custom_id"]
    response = result.get("response", {})
    error = result.get("error")

    if error:
        return {
            "custom_id": custom_id,
            "success": False,
            "error": error
        }

    # Extract response body
    body = response.get("body", {})
    choices = body.get("choices", [])

    if not choices:
        return {
            "custom_id": custom_id,
            "success": False,
            "error": "No choices in response"
        }

    # Get message content
    message = choices[0].get("message", {})
    content = message.get("content", "")

    if not content:
        return {
            "custom_id": custom_id,
            "success": False,
            "error": "Empty response content"
        }

    # Try to extract JSON
    category_result = extract_json_from_text(content)

    if category_result is None:
        return {
            "custom_id": custom_id,
            "success": False,
            "error": "Failed to parse JSON from response",
            "content_preview": content[:200]
        }

    # Extract reasoning (text before JSON)
    json_start = content.rfind("{")
    reasoning = extract_reasoning(content, json_start)

    # Validate JSON structure
    has_match = "match" in category_result
    has_blockquotes = "blockquotes" in category_result

    return {
        "custom_id": custom_id,
        "success": True,
        "match": category_result.get("match"),
        "blockquotes_count": len(category_result.get("blockquotes", [])),
        "reasoning_length": len(reasoning),
        "has_reasoning": len(reasoning) > 0,
        "valid_structure": has_match and has_blockquotes,
        "finish_reason": choices[0].get("finish_reason"),
        "usage": body.get("usage", {})
    }


def main():
    """Parse batch results and print report."""
    if len(sys.argv) < 2:
        print("Usage: python parse_batch_results.py <results.jsonl>")
        sys.exit(1)

    results_file = Path(sys.argv[1])

    if not results_file.exists():
        print(f"Error: {results_file} not found")
        sys.exit(1)

    # Parse all results
    results = []
    with open(results_file) as f:
        for line in f:
            result = json.loads(line)
            parsed = parse_batch_result(result)
            results.append(parsed)

    # Print report
    print(f"\n{'='*60}")
    print(f"Batch Results Summary")
    print(f"{'='*60}\n")

    total = len(results)
    successful = sum(1 for r in results if r["success"])
    failed = total - successful

    print(f"Total requests: {total}")
    print(f"Successful: {successful} ({successful/total*100:.1f}%)")
    print(f"Failed: {failed} ({failed/total*100:.1f}%)\n")

    if successful > 0:
        # Stats for successful results
        with_reasoning = sum(1 for r in results if r.get("has_reasoning", False))
        valid_structure = sum(1 for r in results if r.get("valid_structure", False))

        print(f"Successful results:")
        print(f"  With reasoning: {with_reasoning}/{successful} ({with_reasoning/successful*100:.1f}%)")
        print(f"  Valid structure: {valid_structure}/{successful} ({valid_structure/successful*100:.1f}%)\n")

        # Match distribution
        matches = {}
        for r in results:
            if r["success"]:
                match = r.get("match", "unknown")
                matches[match] = matches.get(match, 0) + 1

        print(f"Match distribution:")
        for match, count in sorted(matches.items()):
            print(f"  {match}: {count}")

        print()

        # Token usage
        total_prompt = sum(r.get("usage", {}).get("prompt_tokens", 0) for r in results if r["success"])
        total_completion = sum(r.get("usage", {}).get("completion_tokens", 0) for r in results if r["success"])

        print(f"Token usage:")
        print(f"  Total prompt: {total_prompt:,}")
        print(f"  Total completion: {total_completion:,}")
        print(f"  Total: {total_prompt + total_completion:,}")

    # Detailed results
    print(f"\n{'='*60}")
    print(f"Detailed Results")
    print(f"{'='*60}\n")

    for r in results:
        print(f"Request: {r['custom_id']}")
        if r["success"]:
            print(f"  ✓ Success")
            print(f"    Match: {r['match']}")
            print(f"    Blockquotes: {r['blockquotes_count']}")
            print(f"    Reasoning: {r['reasoning_length']} chars")
            print(f"    Finish: {r['finish_reason']}")
        else:
            print(f"  ✗ Failed: {r['error']}")
            if "content_preview" in r:
                print(f"    Preview: {r['content_preview']}")
        print()


if __name__ == "__main__":
    main()
