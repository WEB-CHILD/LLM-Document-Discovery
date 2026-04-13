"""
Generate vLLM batch file for testing.

This script creates an OpenAI Batch format JSONL file with 7 test requests:
- 1 file × 7 categories = 7 requests total

Format: {"custom_id": "...", "method": "POST", "url": "/v1/chat/completions", "body": {...}}
"""

import json
import os
import yaml
from pathlib import Path


def load_system_prompt(project_root: Path) -> str:
    """Load universal system prompt."""
    with open(project_root / "system_prompt.txt") as f:
        return f.read()


def load_category(project_root: Path, category_file: str) -> dict:
    """Load category YAML and return name + prompt."""
    with open(project_root / "POC-prompts" / category_file) as f:
        data = yaml.safe_load(f)
    return {
        "name": data["name"],
        "prompt": data["prompt"]
    }


def load_test_document(project_root: Path) -> str:
    """Load test document."""
    doc_path = project_root / "input" / "19961019235833_http_ds.internic.net_80_ds_dsdirofdirs.html.md"
    with open(doc_path) as f:
        return f.read()


def create_batch_request(
    custom_id: str,
    model: str,
    system_prompt: str,
    category_prompt: str,
    document_content: str
) -> dict:
    """
    Create a single batch request in OpenAI format.

    Args:
        custom_id: Unique identifier for this request
        model: Model name
        system_prompt: Universal extraction instructions
        category_prompt: Category-specific instructions
        document_content: Document to analyze

    Returns:
        Batch request dict
    """
    # Construct messages
    system_message = {
        "role": "system",
        "content": system_prompt
    }

    user_message = {
        "role": "user",
        "content": f"""# Category Instructions

{category_prompt}

# Document to Analyze

{document_content}

# Response Format

First, provide your reasoning and analysis.
Then, provide ONLY valid JSON with this structure:
{{
  "match": "yes" or "maybe" or "no",
  "blockquotes": ["quote 1", "quote 2"]
}}"""
    }

    # Create batch request
    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model,
            "messages": [system_message, user_message],
            "temperature": 0.0,
            "max_tokens": 128000,
        }
    }


def main():
    """Generate batch file with 7 test requests."""
    # Setup paths
    script_dir = Path(__file__).parent
    project_root = script_dir / ".." / ".."
    project_root = project_root.resolve()

    output_file = script_dir / "test_batch.jsonl"

    # Load common data
    system_prompt = load_system_prompt(project_root)
    document = load_test_document(project_root)
    model = "openai/gpt-oss-20b"


    # Get first 7 category files from POC-prompts directory
    prompts_dir = project_root / "POC-prompts"
    all_yamls = sorted(prompts_dir.glob("*.yaml"))
    categories = [f.name for f in all_yamls[:7]]

    if len(categories) < 7:
        print(f"Warning: Only found {len(categories)} category files")

    print(f"Using categories: {categories}")

    # Generate requests
    requests = []
    for i, category_file in enumerate(categories, 1):
        category = load_category(project_root, category_file)

        custom_id = f"file001_cat{i:02d}_{category['name']}"

        request = create_batch_request(
            custom_id=custom_id,
            model=model,
            system_prompt=system_prompt,
            category_prompt=category["prompt"],
            document_content=document
        )

        requests.append(request)

    # Write batch file
    with open(output_file, "w") as f:
        for request in requests:
            f.write(json.dumps(request) + "\n")

    print(f"✓ Generated {len(requests)} requests in {output_file}")
    print(f"  Model: {model}")
    print(f"  Categories: {len(categories)}")
    print(f"  File size: {output_file.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
