"""End-to-end integration tests for the Apptainer container.

These tests require a pre-built pipeline.sif (~13GB) and the apptainer CLI.
They are skipped automatically when the .sif file does not exist, making them
safe to run on developer machines and in CI without a built image.

Run only these tests:
    uv run pytest tests/test_container_e2e.py -v

Select/exclude via marker:
    uv run pytest -m container
    uv run pytest -m 'not container'

GPU tests (Phase 2) additionally require an NVIDIA GPU and model weights:
    uv run pytest -m gpu -v
"""

import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _resolve_sif_path() -> Path:
    """Return the path to pipeline.sif from env var or default location."""
    return Path(os.environ.get("PIPELINE_SIF", _REPO_ROOT / "pipeline.sif"))


@pytest.fixture(scope="module")
def sif_path():
    """Resolve the .sif path and skip the entire module if it is absent."""
    path = _resolve_sif_path()
    if not path.exists():
        pytest.skip(f"pipeline.sif not found at {path} — skipping container tests")
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.container
class TestContainerE2E:
    """Phase 1 acceptance-criteria tests for the Apptainer container image."""

    def test_sif_exists_and_is_valid(self, sif_path):
        """AC1.1 — .sif file exists and is a plausible size (>1 GB)."""
        one_gb = 1 * 1024 * 1024 * 1024
        actual_size = sif_path.stat().st_size
        assert actual_size > one_gb, (
            f"pipeline.sif is only {actual_size / (1024**3):.2f} GB — expected >1 GB"
        )

    def test_cli_callable_inside_container(self, sif_path):
        """AC1.2 — llm-discovery CLI is callable inside the container."""
        result = subprocess.run(
            ["apptainer", "exec", str(sif_path), "llm-discovery", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"llm-discovery --help exited {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "process" in result.stdout, (
            f"'process' not found in --help output:\n{result.stdout}"
        )
        assert "import-results" in result.stdout, (
            f"'import-results' not found in --help output:\n{result.stdout}"
        )

    def test_container_fails_on_missing_env_vars(self, sif_path, tmp_path):
        """AC2.5 — entrypoint rejects launch when required env vars are unset."""
        # Create a minimal hpc_env.sh that sets nothing
        hpc_env = tmp_path / "hpc_env.sh"
        hpc_env.write_text("# empty\n")

        result = subprocess.run(
            [
                "apptainer",
                "exec",
                "--bind",
                f"{tmp_path}:/data",
                str(sif_path),
                "/opt/llm-discovery/container/entrypoint.sh",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0, (
            "entrypoint should fail when required env vars are missing"
        )
        combined_output = result.stdout + result.stderr
        expected_msg = (
            "ERROR: Required environment variable VLLM_MODEL is not set"
        )
        assert expected_msg in combined_output, (
            f"Expected VLLM_MODEL error in output:\n{combined_output}"
        )


# ---------------------------------------------------------------------------
# GPU integration tests — Phase 2
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def gpu_data_dir(tmp_path_factory, sif_path):
    """Prepare a data directory and run the full container pipeline once.

    This is class-scoped so that tests 1-3 share the same (expensive)
    container invocation.  The fixture:

    1. Builds ``corpus.db`` via ``prep-db`` + ``preflight`` on the host.
    2. Copies runtime assets (system_prompt.txt, prompts/, hpc_env.sh).
    3. Launches the container with ``--nv`` and waits up to 30 min.
    4. Returns a dict with ``data_dir``, ``result`` (CompletedProcess), and
       ``db_path`` for downstream assertions.
    """
    data_dir = tmp_path_factory.mktemp("gpu_e2e")
    db_path = data_dir / "corpus.db"

    # -- host-side DB preparation --
    subprocess.run(
        [
            "uv", "run", "llm-discovery", "prep-db",
            "--db", str(db_path),
            "--input-dir", str(_REPO_ROOT / "input" / "demo_corpus"),
            "--prompts-dir", str(_REPO_ROOT / "prompts"),
        ],
        check=True,
    )
    subprocess.run(
        ["uv", "run", "llm-discovery", "preflight", "--db", str(db_path)],
        check=True,
    )

    # -- copy runtime assets into the data dir --
    shutil.copy2(_REPO_ROOT / "system_prompt.txt", data_dir / "system_prompt.txt")
    shutil.copytree(_REPO_ROOT / "prompts", data_dir / "prompts")
    shutil.copy2(
        _REPO_ROOT / "container" / "hpc_env.rtx4090.sh",
        data_dir / "hpc_env.sh",
    )
    (data_dir / "out").mkdir(exist_ok=True)

    # -- run the container --
    result = subprocess.run(
        [
            "apptainer", "exec", "--nv",
            "--bind", f"{data_dir}:/data",
            "--bind", f"{Path.home()}/.cache/huggingface:/model_cache",
            "--env", "HF_HOME=/model_cache",
            str(sif_path),
            "/opt/llm-discovery/container/entrypoint.sh",
        ],
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )

    return {"data_dir": data_dir, "result": result, "db_path": db_path}


@pytest.mark.gpu
@pytest.mark.container
class TestContainerGPU:
    """Phase 2 acceptance-criteria tests — require GPU + pipeline.sif."""

    def test_container_processes_corpus(self, gpu_data_dir):
        """AC2.1 — container runs the full pipeline and produces result files."""
        result = gpu_data_dir["result"]
        data_dir = gpu_data_dir["data_dir"]

        assert result.returncode == 0, (
            f"Container exited with code {result.returncode}\n"
            f"stdout:\n{result.stdout[-2000:]}\n"
            f"stderr:\n{result.stderr[-2000:]}"
        )

        out_dir = data_dir / "out"
        result_files = sorted(out_dir.glob("r*_c*.json"))
        assert len(result_files) > 0, (
            f"No result JSON files (r*_c*.json) found in {out_dir}.\n"
            f"Contents: {[p.name for p in out_dir.iterdir()]}"
        )

        # At least one result file must be non-empty
        non_empty = [f for f in result_files if f.stat().st_size > 0]
        assert len(non_empty) > 0, (
            "All result JSON files are empty (0 bytes)"
        )

    def test_container_imports_results(self, gpu_data_dir):
        """AC2.2 — import-results populates result_category with reasoning."""
        db_path = gpu_data_dir["db_path"]

        conn = sqlite3.connect(str(db_path))
        try:
            row_count = conn.execute(
                "SELECT COUNT(*) FROM result_category"
            ).fetchone()[0]
            assert row_count > 0, (
                "result_category table is empty after import-results"
            )

            has_reasoning = conn.execute(
                "SELECT COUNT(*) FROM result_category "
                "WHERE reasoning_trace IS NOT NULL"
            ).fetchone()[0]
            assert has_reasoning > 0, (
                "No rows in result_category have a non-null reasoning_trace"
            )
        finally:
            conn.close()

    def test_container_exits_cleanly(self, gpu_data_dir):
        """AC2.3 — container exits 0 and leaves no orphaned vLLM processes."""
        result = gpu_data_dir["result"]
        assert result.returncode == 0, (
            f"Container exited with code {result.returncode}"
        )

        # No orphaned vLLM processes should remain
        pgrep = subprocess.run(
            ["pgrep", "-f", "vllm serve"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert pgrep.returncode != 0, (
            f"Orphaned vLLM processes found after container exit:\n"
            f"{pgrep.stdout}"
        )

    def test_container_exit_trap_on_failure(self, sif_path, tmp_path):
        """AC2.4 — corrupt DB causes non-zero exit with no orphaned processes."""
        # Prepare a data dir with a corrupt (empty) corpus.db
        data_dir = tmp_path / "corrupt_e2e"
        data_dir.mkdir()
        (data_dir / "corpus.db").write_bytes(b"")

        shutil.copy2(_REPO_ROOT / "system_prompt.txt", data_dir / "system_prompt.txt")
        shutil.copytree(_REPO_ROOT / "prompts", data_dir / "prompts")
        shutil.copy2(
            _REPO_ROOT / "container" / "hpc_env.rtx4090.sh",
            data_dir / "hpc_env.sh",
        )
        (data_dir / "out").mkdir()

        result = subprocess.run(
            [
                "apptainer", "exec", "--nv",
                "--bind", f"{data_dir}:/data",
                "--bind", f"{Path.home()}/.cache/huggingface:/model_cache",
                "--env", "HF_HOME=/model_cache",
                str(sif_path),
                "/opt/llm-discovery/container/entrypoint.sh",
            ],
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )

        assert result.returncode != 0, (
            "Container should fail with a corrupt corpus.db but exited 0"
        )

        # No orphaned vLLM processes should remain
        pgrep = subprocess.run(
            ["pgrep", "-f", "vllm serve"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert pgrep.returncode != 0, (
            f"Orphaned vLLM processes found after failed container run:\n"
            f"{pgrep.stdout}"
        )
