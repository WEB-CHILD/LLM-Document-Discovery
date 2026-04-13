"""Typer CLI for LLM Document Discovery pipeline."""

import io
from pathlib import Path

import typer
from rich import print as rprint

from llm_discovery.fetch import DEFAULT_DEMO_URLS, fetch_single
from llm_discovery.import_results import run_import
from llm_discovery.preflight_check import run_preflight
from llm_discovery.prep_db import run_prep_db
from llm_discovery.unified_processor import run_processor

app = typer.Typer(
    name="llm-discovery",
    help="Reproducible pipeline for classifying historical web documents using LLMs.",
)


@app.command()
def fetch(
    urls: list[str] = typer.Argument(
        None, help="Internet Archive URLs to fetch (defaults to 5 demo URLs)"
    ),
    output_dir: Path = typer.Option(
        "input/demo_corpus", help="Directory to write markdown files to"
    ),
) -> None:
    """Download pages from the Internet Archive and convert to markdown."""
    url_list = urls if urls else DEFAULT_DEMO_URLS
    rprint(f"[bold]Fetching {len(url_list)} documents from Internet Archive...[/bold]")
    output_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    failed = 0
    for url in url_list:
        try:
            result = fetch_single(url, output_dir)
            if result is not None:
                rprint(f"  [green]fetched[/green] {result.name}")
                written += 1
            else:
                rprint(f"  [dim]skipped[/dim] {url} (already exists)")
                skipped += 1
        except Exception as exc:
            rprint(f"  [red]error[/red] {url}: {exc}")
            failed += 1

    rprint(
        f"[green]Done.[/green] Fetched {written}, skipped {skipped}, failed {failed}."
    )
    if failed:
        raise typer.Exit(1)


@app.command(name="prep-db")
def prep_db(
    db: Path = typer.Option("corpus.db", help="Database path"),
    input_dir: Path = typer.Option("input/demo_corpus", help="Corpus directory"),
    prompts_dir: Path = typer.Option("prompts", help="Prompts directory"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress per-file output"),
) -> None:
    """Create and populate the corpus database from documents and prompts."""
    schema_path = Path("schema.sql")
    if not schema_path.exists():
        rprint("[red]Error: schema.sql not found[/red]")
        raise typer.Exit(1)
    if not prompts_dir.exists():
        rprint(f"[red]Error: prompts directory not found: {prompts_dir}[/red]")
        raise typer.Exit(1)
    if not input_dir.exists():
        rprint(f"[red]Error: input directory not found: {input_dir}[/red]")
        raise typer.Exit(1)
    run_prep_db(db, input_dir, prompts_dir, schema_path, quiet=quiet)


@app.command()
def preflight(
    db: Path = typer.Option("corpus.db", help="Database path"),
    delete: bool = typer.Option(False, help="Delete problematic documents"),
) -> None:
    """Validate documents in corpus database."""
    if not db.exists():
        rprint(f"[red]Error: database not found: {db}[/red]")
        raise typer.Exit(1)
    result = run_preflight(db, delete=delete)
    rprint(
        f"Total: {result['total']}, Valid: {result['valid']},"
        f" Problematic: {result['problematic']}"
    )
    if result["by_reason"]:
        for reason, count in sorted(result["by_reason"].items(), key=lambda x: -x[1]):
            rprint(f"  {reason}: {count}")
    if result["problematic"] and not delete:
        rprint("[dim]Run with --delete to remove problematic documents[/dim]")
        raise typer.Exit(1)


@app.command()
def process(
    db: Path = typer.Option("corpus.db", help="Database path"),
    output_dir: Path = typer.Option("out", help="JSON output directory"),
    server_url: str = typer.Option("http://localhost:8000", help="vLLM server URL"),
    concurrency: int = typer.Option(128, help="Number of concurrent workers"),
    limit: int = typer.Option(None, help="Limit number of pairs to process"),
    model: str = typer.Option("openai/gpt-oss-120b", help="Model name"),
) -> None:
    """Run LLM classification on unprocessed document-category pairs."""
    if not db.exists():
        rprint(f"[red]Error: database not found: {db}[/red]")
        raise typer.Exit(1)
    system_prompt_path = Path("system_prompt.txt")
    if not system_prompt_path.exists():
        rprint("[red]Error: system_prompt.txt not found[/red]")
        raise typer.Exit(1)
    run_processor(
        db_path=db,
        output_dir=output_dir,
        server_url=server_url,
        system_prompt_path=system_prompt_path,
        concurrency=concurrency,
        limit=limit,
        model=model,
    )


@app.command(name="import-results")
def import_results_cmd(
    db: Path = typer.Option("corpus.db", help="Database path"),
    input_dir: Path = typer.Option("out", help="JSON output directory to import from"),
) -> None:
    """Import JSON result files into corpus database."""
    if not db.exists():
        rprint(f"[red]Error: database not found: {db}[/red]")
        raise typer.Exit(1)
    if not input_dir.exists():
        rprint(f"[red]Error: input directory not found: {input_dir}[/red]")
        raise typer.Exit(1)
    run_import(db, input_dir)


def _ensure_validated(platform_name: str, project: str | None) -> bool:
    """Run validation for a platform. Returns True if all checks pass."""
    from llm_discovery.platform import (
        display_validation_results,
        load_platforms,
        validate_platform,
    )

    config_path = Path("config/platforms.yaml")
    if not config_path.exists():
        rprint("[red]Error: config/platforms.yaml not found[/red]")
        return False
    platforms = load_platforms(config_path)
    if platform_name not in platforms.platforms:
        available = ", ".join(platforms.platforms)
        rprint(
            f"[red]Error: unknown platform"
            f" '{platform_name}'. Available: {available}[/red]"
        )
        return False
    platform_config = platforms.platforms[platform_name]
    results = validate_platform(platform_config, project=project)
    return display_validation_results(platform_config.display_name, results)


@app.command()
def validate(
    platform: str = typer.Option(..., help="HPC platform: gadi or ucloud"),
    project: str = typer.Option(None, help="NCI project code (for Gadi)"),
) -> None:
    """Check remote HPC environment readiness."""
    if not _ensure_validated(platform, project):
        raise typer.Exit(1)


@app.command()
def deploy(
    platform: str = typer.Option(..., help="HPC platform: gadi or ucloud"),
    project: str = typer.Option(None, help="NCI project code (for Gadi)"),
    gpu_queue: str = typer.Option(
        "gpuhopper", help="Gadi GPU queue: gpuhopper or gpuvolta"
    ),
    container_image: str = typer.Option(
        "pipeline.sif", help="Path to local .sif container image"
    ),
) -> None:
    """Sync code to HPC and submit job."""
    from fabric import Connection

    from llm_discovery.platform import (
        generate_hpc_env,
        load_platforms,
        resolve_remote_path,
        rsync_to_remote,
        stage_container_image,
        submit_gadi_job,
        submit_ucloud_job,
    )

    if not _ensure_validated(platform, project):
        rprint("[yellow]Validation failed — fix issues before deploying[/yellow]")
        raise typer.Exit(1)

    config_path = Path("config/platforms.yaml")
    platforms = load_platforms(config_path)
    platform_config = platforms.platforms[platform]

    # Rsync code to remote (if SSH available)
    if platform_config.ssh_host:
        rprint(f"[bold]Syncing code to {platform_config.display_name}...[/bold]")
        rsync_to_remote(platform_config, Path(), project or "")

    # Stage container image
    rprint(f"[bold]Staging container image {container_image}...[/bold]")
    container_path = stage_container_image(
        platform_config, project or "", Path(container_image)
    )

    # Generate and upload hpc_env.sh
    rprint(f"[bold]Uploading GPU configuration for {gpu_queue}...[/bold]")
    env_content = generate_hpc_env(gpu_queue)
    remote_path = resolve_remote_path(platform_config, project or "")
    conn = Connection(platform_config.ssh_host)
    conn.run(f"mkdir -p {remote_path}/data")
    conn.put(io.StringIO(env_content), f"{remote_path}/data/hpc_env.sh")

    # Submit job
    if platform == "gadi":
        if not project:
            rprint("[red]Error: --project is required for Gadi deployment[/red]")
            raise typer.Exit(1)
        rprint(f"[bold]Submitting PBS job to {gpu_queue} queue...[/bold]")
        job_id = submit_gadi_job(platform_config, project, gpu_queue, container_path)
        rprint(f"[green]Job submitted: {job_id}[/green]")
        rprint(
            f"[dim]Check status: llm-discovery status"
            f" --platform gadi --job-id {job_id}[/dim]"
        )
    elif platform == "ucloud":
        submit_ucloud_job(platform_config)
    else:
        rprint(f"[red]Deploy not supported for platform: {platform}[/red]")
        raise typer.Exit(1)


@app.command()
def status(
    platform: str = typer.Option(..., help="HPC platform: gadi or ucloud"),
    job_id: str = typer.Option(None, help="Job ID to check"),
    project: str = typer.Option(None, help="NCI project code"),
) -> None:
    """Check status of running HPC job."""
    from llm_discovery.platform import check_job_status, load_platforms

    config_path = Path("config/platforms.yaml")
    platforms = load_platforms(config_path)
    if platform not in platforms.platforms:
        rprint(f"[red]Unknown platform: {platform}[/red]")
        raise typer.Exit(1)
    platform_config = platforms.platforms[platform]

    if not job_id:
        rprint("[red]Error: --job-id is required[/red]")
        raise typer.Exit(1)

    result = check_job_status(platform_config, job_id, project)
    rprint(f"Job {job_id}: [bold]{result}[/bold]")


@app.command()
def retrieve(
    platform: str = typer.Option(..., help="HPC platform: gadi or ucloud"),
    project: str = typer.Option(None, help="NCI project code"),
    output: Path = typer.Option("corpus.db", help="Local path for retrieved database"),
) -> None:
    """Pull results (corpus.db) back from HPC."""
    from llm_discovery.platform import load_platforms, retrieve_results

    config_path = Path("config/platforms.yaml")
    platforms = load_platforms(config_path)
    if platform not in platforms.platforms:
        rprint(f"[red]Unknown platform: {platform}[/red]")
        raise typer.Exit(1)
    platform_config = platforms.platforms[platform]

    if not project:
        rprint("[red]Error: --project is required for retrieval[/red]")
        raise typer.Exit(1)

    rprint(f"[bold]Retrieving corpus.db from {platform_config.display_name}...[/bold]")
    local_path = retrieve_results(platform_config, output, project)
    rprint(f"[green]Retrieved to: {local_path}[/green]")


def _run_local_pipeline(
    output_dir: Path,
    model: str | None,
    gpu_type: str | None,
) -> None:
    """Run the full pipeline locally with vLLM server management."""
    import yaml

    from llm_discovery.local_runner import (
        run_local_pipeline,
        start_vllm_server,
        stop_vllm_server,
        wait_for_health,
    )

    # Load GPU params
    config_path = Path("config/machines.yaml")
    if config_path.exists():
        with config_path.open() as f:
            machines = yaml.safe_load(f)
        gpu_type_key = gpu_type or "H100"
        gpu_types = machines.get("gpu_types", {})
        if gpu_type_key not in gpu_types:
            available = ", ".join(gpu_types.keys())
            rprint(
                f"[red]Unknown GPU type '{gpu_type_key}'. Available: {available}[/red]"
            )
            raise typer.Exit(1)
        gpu_params = gpu_types[gpu_type_key]
        # Model priority: --model flag > gpu_type config > default_model
        default_model = (
            model
            or gpu_params.get("model")
            or machines.get("default_model", "openai/gpt-oss-120b")
        )
    else:
        default_model = model or "openai/gpt-oss-120b"
        gpu_params = {
            "tensor_parallel_size": 1,
            "gpu_memory_utilization": 0.90,
            "max_num_seqs": 64,
        }

    rprint("\n[bold]===== Stage: Local Pipeline =====[/bold]")
    try:
        start_vllm_server(default_model, gpu_params)
        wait_for_health()
        run_local_pipeline(
            db_path=Path("corpus.db"),
            input_dir=output_dir,
            output_dir=Path("out"),
            prompts_dir=Path("prompts"),
            server_url="http://localhost:8000",
            system_prompt_path=Path("system_prompt.txt"),
            model=default_model,
        )
    finally:
        stop_vllm_server()


def _run_remote_pipeline(
    platform: str,
    project: str | None,
    gpu_queue: str,
    yes: bool,
) -> None:
    """Run the remote pipeline: validate, deploy, poll, retrieve."""
    from llm_discovery.platform import (
        check_job_status,
        load_platforms,
        retrieve_results,
        rsync_to_remote,
        submit_gadi_job,
        submit_ucloud_job,
    )

    rprint("\n[bold]===== Stage: Validate =====[/bold]")
    if not _ensure_validated(platform, project):
        rprint("[red]Validation failed.[/red]")
        raise typer.Exit(1)

    if not yes and not typer.confirm("Validation passed. Deploy?", default=True):
        raise typer.Exit(0)

    rprint("\n[bold]===== Stage: Deploy =====[/bold]")
    platforms_config = load_platforms(Path("config/platforms.yaml"))
    platform_config = platforms_config.platforms[platform]

    if platform_config.ssh_host:
        rsync_to_remote(platform_config, Path(), project or "")

    job_id = None
    if platform == "gadi":
        if not project:
            rprint("[red]Error: --project required for Gadi[/red]")
            raise typer.Exit(1)
        job_id = submit_gadi_job(platform_config, project, gpu_queue)
        rprint(f"[green]Job submitted: {job_id}[/green]")
    elif platform == "ucloud":
        submit_ucloud_job(platform_config)
        rprint("[dim]UCloud requires manual submission -- poll manually.[/dim]")
        raise typer.Exit(0)

    # Poll status
    if job_id:
        import time as _time

        rprint("\n[bold]===== Stage: Polling =====[/bold]")
        while True:
            status_str = check_job_status(platform_config, job_id, project)
            rprint(f"  Job {job_id}: {status_str}")
            if status_str in (
                "finished",
                "completed or not found",
            ):
                break
            _time.sleep(60)

    # Retrieve
    if not yes and not typer.confirm("Retrieve results?", default=True):
        raise typer.Exit(0)

    rprint("\n[bold]===== Stage: Retrieve =====[/bold]")
    retrieve_results(platform_config, Path("corpus.db"), project or "")
    rprint("[green]Pipeline complete. Results in corpus.db[/green]")


@app.command()
def run(
    platform: str = typer.Option("local", help="Platform: gadi, ucloud, or local"),
    project: str = typer.Option(None, help="NCI project code (for Gadi)"),
    gpu_queue: str = typer.Option(
        "gpuhopper", help="Gadi GPU queue: gpuhopper or gpuvolta"
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip interactive prompts (unattended mode)",
    ),
    urls: list[str] = typer.Argument(
        None, help="Internet Archive URLs (defaults to demo)"
    ),
    model: str = typer.Option(
        None,
        help="Override model name (e.g., google/gemma-4-E4B-it)",
    ),
    gpu_type: str = typer.Option(
        None,
        help="GPU type from machines.yaml (e.g., RTX4090, H100)",
    ),
) -> None:
    """Execute the complete pipeline."""
    from llm_discovery.fetch import DEFAULT_DEMO_URLS, fetch_single

    # Stage 1: Fetch
    rprint("\n[bold]===== Stage: Fetch =====[/bold]")
    url_list = urls if urls else DEFAULT_DEMO_URLS
    output_dir = Path("input/demo_corpus")
    output_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for url in url_list:
        try:
            result = fetch_single(url, output_dir)
            if result is not None:
                rprint(f"  [green]fetched[/green] {result.name}")
                written += 1
            else:
                rprint("  [dim]skipped[/dim] (already exists)")
        except Exception as exc:
            rprint(f"  [red]error[/red] {url}: {exc}")
    rprint(f"Fetched {written} new documents.")

    if not yes and not typer.confirm("Continue?", default=True):
        raise typer.Exit(0)

    if platform == "local":
        _run_local_pipeline(output_dir, model, gpu_type)
    else:
        _run_remote_pipeline(platform, project, gpu_queue, yes)
