"""Typer CLI for LLM Document Discovery pipeline."""

from pathlib import Path

import typer
from rich import print as rprint

from llm_discovery.fetch import fetch_corpus
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
    url_list = urls if urls else None
    count = len(urls) if urls else 5
    rprint(f"[bold]Fetching {count} documents from Internet Archive...[/bold]")

    try:
        written = fetch_corpus(url_list, output_dir)
    except RuntimeError as exc:
        rprint(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    skipped = count - len(written)
    rprint(
        f"[green]Done.[/green] Fetched {len(written)}, skipped {skipped}."
    )
    if not written and skipped:
        rprint("[dim]All files already existed — nothing to do.[/dim]")


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


@app.command()
def validate(
    platform: str = typer.Option(..., help="HPC platform to validate: gadi or ucloud"),
) -> None:
    """Check remote HPC environment readiness."""
    rprint("[yellow]validate: not yet implemented[/yellow]")
    raise typer.Exit(1)


@app.command()
def deploy(
    platform: str = typer.Option(..., help="HPC platform to deploy to: gadi or ucloud"),
) -> None:
    """Sync code to HPC and submit job."""
    rprint("[yellow]deploy: not yet implemented[/yellow]")
    raise typer.Exit(1)


@app.command()
def status(
    platform: str = typer.Option(..., help="HPC platform to check: gadi or ucloud"),
) -> None:
    """Check status of running HPC job."""
    rprint("[yellow]status: not yet implemented[/yellow]")
    raise typer.Exit(1)


@app.command()
def retrieve(
    platform: str = typer.Option(..., help="HPC platform to retrieve from: gadi or ucloud"),
) -> None:
    """Pull results (corpus.db) back from HPC."""
    rprint("[yellow]retrieve: not yet implemented[/yellow]")
    raise typer.Exit(1)


@app.command()
def run(
    platform: str = typer.Option("local", help="Platform: gadi, ucloud, or local"),
) -> None:
    """Execute the complete pipeline: fetch → validate → deploy → status → retrieve."""
    rprint("[yellow]run: not yet implemented[/yellow]")
    raise typer.Exit(1)
