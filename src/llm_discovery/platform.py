"""Platform configuration and validation for HPC deployment."""

import hashlib
import io
import subprocess
from pathlib import Path

import yaml
from fabric import Connection
from pydantic import BaseModel
from rich.console import Console
from rich.panel import Panel
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
    with config_path.open() as f:
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
        return [
            (platform.checks[0].name if platform.checks else "SSH", False, str(exc))
        ]

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
                results.append(
                    (
                        check.name,
                        False,
                        result.stderr.strip()[:80] if result.stderr else "failed",
                    )
                )
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


def rsync_to_remote(platform: PlatformConfig, local_dir: Path, project: str) -> None:
    """Rsync code to remote HPC. No --delete to protect model cache."""
    if platform.ssh_host is None:
        raise RuntimeError(
            f"Platform {platform.display_name} has no SSH host — cannot rsync"
        )
    remote_path = resolve_remote_path(platform, project)
    subprocess.run(
        [
            "rsync",
            "-avz",
            "--exclude=.venv/",
            "--exclude=__pycache__/",
            "--exclude=*.db",
            "--exclude=*.pyc",
            "--exclude=.git/",
            "--exclude=input/",
            "--exclude=out/",
            "--exclude=*.log",
            str(local_dir) + "/",
            f"{platform.ssh_host}:{remote_path}/",
        ],
        check=True,
    )


def stage_container_image(
    platform: PlatformConfig,
    project: str,
    local_sif: Path,
) -> str:
    """Stage container .sif image to remote HPC. Returns remote path.

    Raises FileNotFoundError if local .sif doesn't exist.
    Raises RuntimeError if remote SHA256 doesn't match local after transfer.
    """
    if not local_sif.exists():
        raise FileNotFoundError(
            f"Container image not found: {local_sif}\n"
            "Build it first: sudo apptainer build pipeline.sif container/pipeline.def"
        )

    # Compute local SHA256
    sha256 = hashlib.sha256()
    with local_sif.open("rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    local_hash = sha256.hexdigest()

    # Create remote directory and transfer
    containers_dir = f"/scratch/{project}/containers"
    remote_sif = f"{containers_dir}/{local_sif.name}"

    conn = Connection(platform.ssh_host)
    conn.run(f"mkdir -p {containers_dir}")

    subprocess.run(
        [
            "rsync",
            "-avz",
            "--checksum",
            "--partial",
            str(local_sif),
            f"{platform.ssh_host}:{remote_sif}",
        ],
        check=True,
    )

    # Verify remote checksum
    result = conn.run(f"sha256sum {remote_sif}", hide=True)
    remote_hash = result.stdout.strip().split()[0]
    if remote_hash != local_hash:
        raise RuntimeError(
            f"SHA256 mismatch after transfer!\n"
            f"  Local:  {local_hash}\n"
            f"  Remote: {remote_hash}"
        )

    return remote_sif


def generate_hpc_env(gpu_queue: str) -> str:
    """Generate hpc_env.sh content for the given GPU queue.

    Returns the shell script content as a string.
    Raises ValueError for unknown queue names.
    """
    configs = {
        "gpuhopper": {
            "VLLM_MODEL": "openai/gpt-oss-120b",
            "VLLM_TP": "4",
            "VLLM_GPU_MEM": "0.92",
            "VLLM_MAX_SEQS": "384",
        },
        "gpuvolta": {
            "VLLM_MODEL": "google/gemma-4-31B-it",
            "VLLM_TP": "4",
            "VLLM_GPU_MEM": "0.90",
            "VLLM_MAX_SEQS": "64",
        },
    }

    if gpu_queue not in configs:
        raise ValueError(
            f"Unknown GPU queue: {gpu_queue}. "
            f"Valid queues: {', '.join(sorted(configs))}"
        )

    env = configs[gpu_queue]
    lines = [
        "#!/usr/bin/env bash",
        f"# Generated by llm-discovery deploy for {gpu_queue}",
    ]
    for key, value in env.items():
        lines.append(f'export {key}="{value}"')

    return "\n".join(lines) + "\n"


def submit_gadi_job(
    platform: PlatformConfig,
    project: str,
    gpu_queue: str = "gpuhopper",
    container_path: str = "",
) -> str:
    """Submit PBS job to Gadi. Returns job ID."""
    template_path = Path("hpc/gadi.pbs.template")
    if not template_path.exists():
        raise FileNotFoundError(f"PBS template not found: {template_path}")

    template = template_path.read_text()
    pbs_script = (
        template.replace("{{GPU_QUEUE}}", gpu_queue)
        .replace("{{NCI_PROJECT}}", project)
        .replace("{{CONTAINER_PATH}}", container_path)
    )

    remote_path = resolve_remote_path(platform, project)
    conn = Connection(platform.ssh_host)

    # Upload the concrete PBS script
    conn.put(io.StringIO(pbs_script), f"{remote_path}/gadi.pbs")

    # Submit
    result = conn.run(f"cd {remote_path} && qsub gadi.pbs", hide=True)
    job_id = result.stdout.strip()
    return job_id


def submit_ucloud_job(_platform: PlatformConfig) -> str | None:
    """Submit UCloud job. Returns None (manual submission required)."""
    console.print(
        Panel(
            "[bold]UCloud automated submission not available.[/bold]\n\n"
            "Manual steps:\n"
            "1. Open UCloud web portal at [link]https://cloud.sdu.dk[/link]\n"
            "2. Create a new Terminal App job\n"
            "3. Select GPU: H100, 2 GPUs\n"
            "4. Mount /work/llm-discovery\n"
            "5. In terminal, run: [bold]bash scripts/process_corpus.sh[/bold]",
            title="UCloud Manual Submission",
            border_style="yellow",
        )
    )
    return None


def retrieve_results(platform: PlatformConfig, local_path: Path, project: str) -> Path:
    """Rsync corpus.db from remote to local."""
    if platform.ssh_host is None:
        raise RuntimeError(
            f"Platform {platform.display_name} has no SSH host — cannot retrieve"
        )
    remote_path = resolve_remote_path(platform, project)
    subprocess.run(
        [
            "rsync",
            "-avz",
            f"{platform.ssh_host}:{remote_path}/corpus.db",
            str(local_path),
        ],
        check=True,
    )
    return local_path


def check_job_status(
    platform: PlatformConfig, job_id: str, _project: str | None = None
) -> str:
    """Check job status on HPC. Returns status string."""
    if platform.ssh_host is None:
        return "unknown (no SSH)"
    conn = Connection(platform.ssh_host)
    result = conn.run(f"qstat {job_id}", warn=True, hide=True)
    if not result.ok:
        return "completed or not found"
    # Parse qstat output for status column
    for line in result.stdout.strip().split("\n"):
        if job_id.split(".", maxsplit=1)[0] in line:
            parts = line.split()
            if len(parts) >= 5:
                status_code = parts[-2]
                status_map = {
                    "Q": "queued",
                    "R": "running",
                    "F": "finished",
                    "E": "exiting",
                }
                return status_map.get(status_code, status_code)
    return "unknown"
