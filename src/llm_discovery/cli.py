"""Typer CLI for LLM Document Discovery pipeline."""

from pathlib import Path

import typer
from rich import print as rprint

from llm_discovery.fetch import fetch_corpus

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
