"""Typer CLI for LLM Document Discovery pipeline."""

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
    urls: list[str] = typer.Argument(None, help="Internet Archive URLs to fetch (defaults to 5 demo URLs)"),
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

    rprint(f"[green]Done.[/green] Fetched {written}, skipped {skipped}, failed {failed}.")
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
    rprint(f"Total: {result['total']}, Valid: {result['valid']}, Problematic: {result['problematic']}")
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
    model: str = typer.Option("openai/gpt-oss-20b", help="Model name"),
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
        db_path=db, output_dir=output_dir, server_url=server_url,
        system_prompt_path=system_prompt_path, concurrency=concurrency,
        limit=limit, model=model,
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
        rprint(f"[red]Error: unknown platform '{platform_name}'. Available: {', '.join(platforms.platforms)}[/red]")
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
    gpu_queue: str = typer.Option("gpuhopper", help="Gadi GPU queue: gpuhopper or gpuvolta"),
) -> None:
    """Sync code to HPC and submit job."""
    from llm_discovery.platform import (
        load_platforms,
        rsync_to_remote,
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
        rsync_to_remote(platform_config, Path("."), project or "")

    # Submit job
    if platform == "gadi":
        if not project:
            rprint("[red]Error: --project is required for Gadi deployment[/red]")
            raise typer.Exit(1)
        rprint(f"[bold]Submitting PBS job to {gpu_queue} queue...[/bold]")
        job_id = submit_gadi_job(platform_config, project, gpu_queue)
        rprint(f"[green]Job submitted: {job_id}[/green]")
        rprint(f"[dim]Check status: llm-discovery status --platform gadi --job-id {job_id}[/dim]")
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


@app.command()
def run(
    platform: str = typer.Option("local", help="Platform: gadi, ucloud, or local"),
) -> None:
    """Execute the complete pipeline: fetch → validate → deploy → status → retrieve."""
    rprint("[yellow]run: not yet implemented[/yellow]")
    raise typer.Exit(1)
