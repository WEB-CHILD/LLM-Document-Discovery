"""Platform configuration and validation for HPC deployment."""

from pathlib import Path

import yaml
from fabric import Connection
from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

console = Console()


class PlatformCheck(BaseModel):
    """A single validation check to run on a platform."""
    name: str
    command: str | None = None


class PlatformConfig(BaseModel):
    """Configuration for an HPC platform."""
    display_name: str
    ssh_host: str | None = None
    remote_base: str
    gpu_type: str
    gpu_queue: str | None = None
    submission: str
    modules: list[str] = []
    checks: list[PlatformCheck] = []


class PlatformsConfig(BaseModel):
    """Top-level platforms configuration."""
    platforms: dict[str, PlatformConfig]


def load_platforms(config_path: Path | str) -> PlatformsConfig:
    """Load and validate platforms.yaml."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Platform config not found: {config_path}")
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return PlatformsConfig(**data)


def resolve_remote_path(platform: PlatformConfig, project: str) -> str:
    """Replace {project} placeholder in remote_base."""
    return platform.remote_base.replace("{project}", project)


def validate_platform(
    platform: PlatformConfig, project: str | None = None
) -> list[tuple[str, bool, str]]:
    """Run each check on the platform via SSH.

    Returns list of (check_name, passed, detail).
    """
    results: list[tuple[str, bool, str]] = []

    if platform.ssh_host is None:
        for check in platform.checks:
            if check.command is None:
                results.append((check.name, True, "skipped (no SSH)"))
            else:
                results.append((check.name, True, "skipped (container platform)"))
        return results

    try:
        conn = Connection(platform.ssh_host)
    except Exception as exc:
        return [(platform.checks[0].name if platform.checks else "SSH", False, str(exc))]

    for check in platform.checks:
        if check.command is None:
            results.append((check.name, True, "skipped"))
            continue

        command = check.command
        if project:
            command = command.replace("{project}", project)

        try:
            result = conn.run(command, warn=True, hide=True)
            if result.ok:
                output = result.stdout.strip()[:80] if result.stdout else ""
                results.append((check.name, True, output))
            else:
                results.append((check.name, False, result.stderr.strip()[:80] if result.stderr else "failed"))
        except Exception as exc:
            results.append((check.name, False, str(exc)[:80]))

    return results


def display_validation_results(
    platform_name: str, results: list[tuple[str, bool, str]]
) -> bool:
    """Display validation results as Rich table. Returns True if all passed."""
    table = Table(title=f"Validation: {platform_name}")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Detail", style="dim")

    all_passed = True
    for name, passed, detail in results:
        status = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        if not passed:
            all_passed = False
        table.add_row(name, status, detail)

    console.print(table)
    return all_passed
