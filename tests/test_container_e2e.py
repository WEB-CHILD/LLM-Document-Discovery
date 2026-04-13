"""End-to-end integration tests for the Apptainer container.

These tests require a pre-built pipeline.sif (~13GB) and the apptainer CLI.
They are skipped automatically when the .sif file does not exist, making them
safe to run on developer machines and in CI without a built image.

Run only these tests:
    uv run pytest tests/test_container_e2e.py -v

Select/exclude via marker:
    uv run pytest -m container
    uv run pytest -m 'not container'
"""

import os
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
