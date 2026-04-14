"""Platform configuration and validation for HPC deployment."""

import hashlib
import io
import os
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
    container_image: str = "pipeline.sif"


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
            elif platform.submission == "apptainer":
                # Local container platform — run checks locally
                try:
                    result = subprocess.run(
                        check.command, shell=True, capture_output=True,  # noqa: S602
                        text=True, check=False,
                    )
                    if result.returncode == 0:
                        output = result.stdout.strip()[:80] if result.stdout else ""
                        results.append((check.name, True, output))
                    else:
                        results.append((check.name, False, result.stderr.strip()[:80]))
                except Exception as exc:
                    results.append((check.name, False, str(exc)))
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
            "--exclude=*.sif",
            "--exclude=container/",
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

    with Connection(platform.ssh_host) as conn:
        conn.run(f"mkdir -p {containers_dir}")

        subprocess.run(
            [
                "rsync",
                "-av",
                "--partial",
                "--progress",
                "--timeout=300",
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


_GPU_QUEUE_CONFIGS: dict[str, dict[str, str]] = {
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
    "gpuvolta-e4b": {
        "VLLM_MODEL": "google/gemma-4-E4B-it",
        "VLLM_TP": "1",
        "VLLM_DP": "4",
        "VLLM_GPU_MEM": "0.85",
        "VLLM_MAX_SEQS": "128",
        "PBS_QUEUE": "gpuvolta",
    },
    "gpuvolta-oss20b": {
        "VLLM_MODEL": "openai/gpt-oss-20b",
        "VLLM_TP": "1",
        "VLLM_DP": "4",
        "VLLM_GPU_MEM": "0.90",
        "VLLM_MAX_SEQS": "128",
        "PBS_QUEUE": "gpuvolta",
    },
    "RTX4090-e4b": {
        "VLLM_MODEL": "google/gemma-4-E4B-it",
        "VLLM_TP": "1",
        "VLLM_GPU_MEM": "0.85",
        "VLLM_MAX_SEQS": "16",
        "VLLM_MAX_MODEL_LEN": "131072",
    },
    "RTX4090-oss20b": {
        "VLLM_MODEL": "openai/gpt-oss-20b",
        "VLLM_TP": "1",
        "VLLM_GPU_MEM": "0.90",
        "VLLM_MAX_SEQS": "16",
    },
}


def get_gpu_queue_config(gpu_queue: str) -> dict[str, str]:
    """Return GPU queue configuration dict.

    Raises ValueError for unknown queues.
    """
    if gpu_queue not in _GPU_QUEUE_CONFIGS:
        raise ValueError(
            f"Unknown GPU queue: {gpu_queue}. "
            f"Valid queues: {', '.join(sorted(_GPU_QUEUE_CONFIGS))}"
        )
    return _GPU_QUEUE_CONFIGS[gpu_queue]


def resolve_pbs_queue(gpu_queue: str) -> str:
    """Return the actual PBS queue name for a gpu_queue config key.

    Config entries may include a PBS_QUEUE override (e.g. gpuvolta-e4b
    submits to the gpuvolta PBS queue). Falls back to the key itself.
    """
    config = get_gpu_queue_config(gpu_queue)
    return config.get("PBS_QUEUE", gpu_queue)


def generate_hpc_env(gpu_queue: str) -> str:
    """Generate hpc_env.sh content for the given GPU queue.

    Returns the shell script content as a string.
    Raises ValueError for unknown queue names.
    """
    env = get_gpu_queue_config(gpu_queue)
    lines = [
        "#!/usr/bin/env bash",
        f"# Generated by llm-discovery deploy for {gpu_queue}",
    ]
    for key, value in env.items():
        if key == "PBS_QUEUE":
            continue
        lines.append(f'export {key}="{value}"')

    return "\n".join(lines) + "\n"


def upload_hpc_env(platform: PlatformConfig, project: str, gpu_queue: str) -> None:
    """Generate hpc_env.sh and upload to remote data directory."""
    env_content = generate_hpc_env(gpu_queue)
    remote_path = resolve_remote_path(platform, project)
    with Connection(platform.ssh_host) as conn:
        conn.run(f"mkdir -p {remote_path}/data")
        conn.put(io.StringIO(env_content), f"{remote_path}/data/hpc_env.sh")


def _resolve_hf_cache() -> Path:
    """Resolve local HuggingFace hub cache directory.

    Checks $HF_HUB_CACHE, $HF_HOME/hub, ~/.cache/huggingface/hub in order.
    Returns the first that exists.
    Raises FileNotFoundError if none exist.
    """
    candidates = []

    hf_hub_cache = os.environ.get("HF_HUB_CACHE")
    if hf_hub_cache:
        candidates.append(Path(hf_hub_cache))

    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        candidates.append(Path(hf_home) / "hub")

    candidates.append(Path.home() / ".cache" / "huggingface" / "hub")

    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    searched = "\n  ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        f"No HuggingFace cache directory found. Searched:\n  {searched}\n"
        "Download model weights first: huggingface-cli download <model-name>"
    )


def _model_cache_dir_name(model_name: str) -> str:
    """Convert HF model name to cache directory name.

    e.g. 'google/gemma-4-31B-it' -> 'models--google--gemma-4-31B-it'
    """
    return f"models--{model_name.replace('/', '--')}"


def upload_model_cache(
    platform: PlatformConfig,
    project: str,
    gpu_queue: str,
) -> None:
    """Rsync locally-cached model weights to remote HPC.

    Resolves model name from get_gpu_queue_config() for the given queue.
    Raises FileNotFoundError if local cache or model directory not found.
    """
    cache_dir = _resolve_hf_cache()
    model_name = get_gpu_queue_config(gpu_queue)["VLLM_MODEL"]

    model_dir_name = _model_cache_dir_name(model_name)
    local_model_dir = cache_dir / model_dir_name

    if not local_model_dir.is_dir():
        raise FileNotFoundError(
            f"Model weights not found: {local_model_dir}\n"
            f"Download first: huggingface-cli download {model_name}"
        )

    remote_hf_cache = f"/scratch/{project}/hf_cache/hub/"
    subprocess.run(
        [
            "rsync",
            "-avz",
            "--partial",
            str(local_model_dir),
            f"{platform.ssh_host}:{remote_hf_cache}",
        ],
        check=True,
    )


def download_model_on_remote(
    platform: PlatformConfig,
    project: str,
    gpu_queue: str,
    container_path: str,
) -> None:
    """Download model weights directly on remote HPC using the staged container.

    Runs huggingface-cli download inside the container on a login node.
    Requires HF_TOKEN to be set on the remote (checked by validate).
    """
    model_name = get_gpu_queue_config(gpu_queue)["VLLM_MODEL"]
    hf_cache = f"/scratch/{project}/hf_cache"

    with Connection(platform.ssh_host) as conn:
        conn.run(f"mkdir -p {hf_cache}", hide=True)
        # Run download inside the container so we get the right Python/HF version
        cmd = (
            f"module load singularity && "
            f"singularity exec "
            f"--bind {hf_cache}:/model_cache --env HF_HOME=/model_cache "
            f"{container_path} "
            f"huggingface-cli download {model_name}"
        )
        console.print(f"[dim]Running: {cmd}[/dim]")
        conn.run(cmd)


def upload_data_dir(
    platform: PlatformConfig,
    project: str,
    data_dir: Path,
) -> None:
    """Rsync local data directory to remote HPC.

    Validates corpus.db, system_prompt.txt, and prompts/ exist.
    Excludes hpc_env.sh (managed by upload_hpc_env).
    Raises FileNotFoundError if required files are missing.
    """
    required_files = ["corpus.db", "system_prompt.txt"]
    required_dirs = ["prompts"]
    missing = []

    for f in required_files:
        if not (data_dir / f).exists():
            missing.append(f)
    for d in required_dirs:
        if not (data_dir / d).is_dir():
            missing.append(f"{d}/")

    if missing:
        raise FileNotFoundError(
            f"Required files missing from {data_dir}:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    remote_path = resolve_remote_path(platform, project)
    subprocess.run(
        [
            "rsync",
            "-avz",
            "--exclude=hpc_env.sh",
            str(data_dir) + "/",
            f"{platform.ssh_host}:{remote_path}/data/",
        ],
        check=True,
    )


def submit_ping_job(
    platform: PlatformConfig,
    project: str,
    gpu_queue: str,
    container_path: str,
) -> str:
    """Submit a vLLM ping/smoke-test PBS job to Gadi. Returns job ID."""
    template_path = Path("hpc/gadi.ping.template")
    if not template_path.exists():
        raise FileNotFoundError(f"Ping template not found: {template_path}")

    template = template_path.read_text()
    pbs_script = (
        template.replace("{{GPU_QUEUE}}", resolve_pbs_queue(gpu_queue))
        .replace("{{NCI_PROJECT}}", project)
        .replace("{{CONTAINER_PATH}}", container_path)
    )

    remote_path = resolve_remote_path(platform, project)
    with Connection(platform.ssh_host) as conn:
        conn.put(io.StringIO(pbs_script), f"{remote_path}/gadi.ping.pbs")
        result = conn.run(f"cd {remote_path} && qsub gadi.ping.pbs", hide=True)
    return result.stdout.strip()


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
        template.replace("{{GPU_QUEUE}}", resolve_pbs_queue(gpu_queue))
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
            f"{platform.ssh_host}:{remote_path}/data/corpus.db",
            str(local_path),
        ],
        check=True,
    )
    return local_path


def fetch_remote_file(platform: PlatformConfig, remote_path: str) -> str | None:
    """Fetch a text file from the remote HPC. Returns content or None."""
    if platform.ssh_host is None:
        return None
    with Connection(platform.ssh_host) as conn:
        result = conn.run(f"cat {remote_path}", warn=True, hide=True)
        if result.ok:
            return result.stdout
    return None


def _parse_qstat_attrs(output: str) -> dict[str, str]:
    """Parse qstat -f output into a dict, handling PBS continuation lines."""
    attrs: dict[str, str] = {}
    current_key = ""
    current_val = ""
    for raw_line in output.split("\n"):
        if " = " in raw_line and not raw_line.startswith("\t"):
            # New key = value pair; save previous
            if current_key:
                attrs[current_key] = current_val
            stripped = raw_line.strip()
            key, _, value = stripped.partition(" = ")
            current_key = key.strip()
            current_val = value.strip()
        elif raw_line.startswith("\t") and current_key:
            # Continuation line
            current_val += raw_line.strip()
    if current_key:
        attrs[current_key] = current_val
    return attrs


def get_job_output_paths(
    platform: PlatformConfig, job_id: str
) -> tuple[str | None, str | None]:
    """Get Output_Path and Error_Path for a PBS job. Returns (out, err)."""
    if platform.ssh_host is None:
        return None, None
    with Connection(platform.ssh_host) as conn:
        result = conn.run(f"qstat -f {job_id}", warn=True, hide=True)
        if not result.ok:
            return None, None
        attrs = _parse_qstat_attrs(result.stdout)
        out_path = attrs.get("Output_Path")
        err_path = attrs.get("Error_Path")
        # Strip host: prefix (format is host:/path/to/file)
        if out_path and ":" in out_path:
            out_path = out_path.split(":", maxsplit=1)[-1]
        if err_path and ":" in err_path:
            err_path = err_path.split(":", maxsplit=1)[-1]
        return out_path, err_path


def _count_jobs_ahead(conn: Connection, queue: str, job_id: str) -> int:
    """Count jobs queued ahead of job_id in the given PBS queue.

    PBS execution queues (e.g. gpuvolta-exec) are stripped to the routing
    queue (gpuvolta) since that's where queued jobs are listed.
    """
    routing_queue = queue.removesuffix("-exec")
    my_num = int(job_id.split(".", maxsplit=1)[0])
    result = conn.run(f"qstat {routing_queue}", warn=True, hide=True)
    if not result.ok:
        return 0
    ahead = 0
    for line in result.stdout.strip().split("\n"):
        parts = line.split()
        if len(parts) >= 5 and parts[-2] == "Q":
            try:
                other_num = int(parts[0].split(".", maxsplit=1)[0])
                if other_num < my_num:
                    ahead += 1
            except ValueError:
                continue
    return ahead


def check_job_status(
    platform: PlatformConfig, job_id: str, _project: str | None = None
) -> str:
    """Check job status on HPC. Returns status string with details."""
    if platform.ssh_host is None:
        return "unknown (no SSH)"

    status_map = {
        "Q": "queued",
        "R": "running",
        "H": "held",
        "F": "finished",
        "E": "exiting",
        "S": "suspended",
    }

    with Connection(platform.ssh_host) as conn:
        # Try qstat -f for detailed info
        result = conn.run(f"qstat -f {job_id}", warn=True, hide=True)
        if not result.ok:
            return "completed or not found"

        attrs = _parse_qstat_attrs(result.stdout)

        state = attrs.get("job_state", "?")
        status = status_map.get(state, state)

        if state == "R":
            walltime = attrs.get("resources_used.walltime")
            if walltime:
                return f"{status} (elapsed {walltime})"
        elif state == "Q":
            queue = attrs.get("queue", "")
            ahead = _count_jobs_ahead(conn, queue, job_id) if queue else 0
            if ahead > 0:
                return f"{status} ({ahead} jobs ahead)"

        return status
