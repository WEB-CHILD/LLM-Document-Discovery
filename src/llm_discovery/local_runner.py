"""Local mode vLLM server management and pipeline execution.

Authoritative path for --platform local CLI runs. Manages vLLM server
lifecycle via tmux, calls pipeline library functions directly (no subprocess).
"""

import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from rich.console import Console

from llm_discovery.import_results import run_import
from llm_discovery.preflight_check import run_preflight
from llm_discovery.prep_db import run_prep_db
from llm_discovery.unified_processor import run_processor

console = Console()

TMUX_SESSION = "llm-server"


def start_vllm_server(model: str, gpu_params: dict, port: int = 8000) -> None:
    """Start vLLM in tmux session."""
    tp = gpu_params.get("tensor_parallel_size", 4)
    gpu_mem = gpu_params.get("gpu_memory_utilization", 0.92)
    max_seqs = gpu_params.get("max_num_seqs", 384)
    max_model_len = gpu_params.get("max_model_len", "")

    env_parts = [
        f"VLLM_MODEL='{model}'",
        f"VLLM_TP={tp}",
        f"VLLM_GPU_MEM={gpu_mem}",
        f"VLLM_MAX_SEQS={max_seqs}",
        f"VLLM_PORT={port}",
        "VLLM_TEXT_ONLY=1",
    ]
    if max_model_len:
        env_parts.append(f"VLLM_MAX_MODEL_LEN={max_model_len}")

    cmd = " ".join(env_parts) + " bash scripts/start_server.sh"
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", TMUX_SESSION, cmd],
        check=True,
    )
    console.print(f"[dim]Started vLLM server in tmux session '{TMUX_SESSION}'[/dim]")


def wait_for_health(port: int = 8000, timeout: int = 3600) -> None:
    """Poll health endpoint until server is ready."""
    console.print(f"[bold]Waiting for vLLM server on port {port}...[/bold]")
    waited = 0
    while waited < timeout:
        try:
            req = urllib.request.Request(f"http://localhost:{port}/health")
            with urllib.request.urlopen(req, timeout=5):  # noqa: S310 -- localhost vLLM health check
                console.print("[green]vLLM server is healthy[/green]")
                return
        except (urllib.error.URLError, OSError):
            time.sleep(5)
            waited += 5
    raise RuntimeError(f"vLLM server did not start within {timeout}s")


def stop_vllm_server() -> None:
    """Kill tmux session. Safe to call even if session doesn't exist."""
    subprocess.run(
        ["tmux", "kill-session", "-t", TMUX_SESSION],
        capture_output=True,
        check=False,
    )


def run_local_pipeline(
    db_path: Path,
    input_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
    server_url: str,
    system_prompt_path: Path,
    model: str = "openai/gpt-oss-20b",
) -> None:
    """Run the full pipeline locally: prep-db -> preflight -> process -> import."""
    schema_path = Path("schema.sql")

    console.print("\n[bold]Stage 1: Prepare database[/bold]")
    run_prep_db(db_path, input_dir, prompts_dir, schema_path)

    console.print("\n[bold]Stage 2: Preflight check[/bold]")
    result = run_preflight(db_path)
    if result["problematic"] > 0:
        console.print(
            f"[yellow]Found {result['problematic']} problematic documents[/yellow]"
        )

    console.print("\n[bold]Stage 3: Process with LLM[/bold]")
    run_processor(
        db_path=db_path,
        output_dir=output_dir,
        server_url=server_url,
        system_prompt_path=system_prompt_path,
        model=model,
        prompts_dir=prompts_dir,
    )

    console.print("\n[bold]Stage 4: Import results[/bold]")
    run_import(db_path, output_dir)

    console.print(f"\n[green]Pipeline complete. Results in {db_path}[/green]")
