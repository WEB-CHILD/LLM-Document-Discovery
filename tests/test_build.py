"""Tests for the build command (Apptainer container image building)."""

import subprocess
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from llm_discovery.cli import app

runner = CliRunner()


class TestBuildCommand:
    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/apptainer")
    def test_build_success(self, _mock_which, mock_run, tmp_path, monkeypatch):
        """AC1.1: Successful build calls apptainer build and then validates."""
        monkeypatch.chdir(tmp_path)
        def_dir = tmp_path / "container"
        def_dir.mkdir()
        (def_dir / "pipeline.def").write_text("Bootstrap: docker\nFrom: ubuntu:22.04\n")

        # Both calls succeed
        mock_run.return_value = MagicMock(returncode=0)

        # Create the .sif file to pass existence check during validation
        sif_path = tmp_path / "pipeline.sif"
        with sif_path.open("wb") as f:
            f.seek(1024**3 + 1)
            f.write(b"\0")

        result = runner.invoke(app, ["build"])

        assert result.exit_code == 0, f"Unexpected output:\n{result.output}"

        # First subprocess call: apptainer build
        build_call = mock_run.call_args_list[0]
        assert build_call[0][0] == [
            "apptainer", "build", "pipeline.sif", "container/pipeline.def"
        ]
        assert build_call[1].get("check") is True

        # Second subprocess call: apptainer exec for validation
        exec_call = mock_run.call_args_list[1]
        assert exec_call[0][0][:2] == ["apptainer", "exec"]
        assert "llm-discovery" in exec_call[0][0]

    @patch("shutil.which", return_value=None)
    def test_apptainer_not_found(self, _mock_which, tmp_path, monkeypatch):
        """AC1.2: Missing apptainer exits with installation guidance."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["build"])

        assert result.exit_code == 1
        assert "apptainer.org" in result.output.lower()

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/apptainer")
    def test_build_failure_shows_sudo_hint(
        self, _mock_which, mock_run, tmp_path, monkeypatch
    ):
        """AC1.2: Build failure shows sudo hint."""
        monkeypatch.chdir(tmp_path)
        def_dir = tmp_path / "container"
        def_dir.mkdir()
        (def_dir / "pipeline.def").write_text("Bootstrap: docker\nFrom: ubuntu:22.04\n")

        mock_run.side_effect = subprocess.CalledProcessError(1, "apptainer")

        result = runner.invoke(app, ["build"])

        assert result.exit_code == 1
        assert "sudo" in result.output.lower()


class TestBuildValidate:
    @patch("subprocess.run")
    def test_validate_success(self, mock_run, tmp_path, monkeypatch):
        """AC1.3: Validate-only with valid .sif succeeds."""
        monkeypatch.chdir(tmp_path)
        sif_path = tmp_path / "big.sif"
        with sif_path.open("wb") as f:
            f.seek(1024**3 + 1)
            f.write(b"\0")

        mock_run.return_value = MagicMock(returncode=0)

        result = runner.invoke(app, ["build", "--validate", "--output", str(sif_path)])

        assert result.exit_code == 0, f"Unexpected output:\n{result.output}"
        assert "validated" in result.output.lower()

    def test_validate_missing_sif(self, tmp_path, monkeypatch):
        """AC1.4: Validate with missing .sif exits with error."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["build", "--validate", "--output", str(tmp_path / "nonexistent.sif")]
        )

        assert result.exit_code == 1
        # Rich may wrap text across lines, so check without newlines
        flat_output = result.output.replace("\n", " ").lower()
        assert "does not exist" in flat_output

    def test_validate_sif_too_small(self, tmp_path, monkeypatch):
        """AC1.4: Validate with undersized .sif exits with size error."""
        monkeypatch.chdir(tmp_path)
        sif_path = tmp_path / "small.sif"
        sif_path.write_bytes(b"tiny")

        result = runner.invoke(app, ["build", "--validate", "--output", str(sif_path)])

        assert result.exit_code == 1
        assert "gb" in result.output.lower()

    @patch("subprocess.run")
    def test_validate_cli_not_callable(self, mock_run, tmp_path, monkeypatch):
        """AC1.4: Validate with .sif where CLI fails exits with error."""
        monkeypatch.chdir(tmp_path)
        sif_path = tmp_path / "broken.sif"
        with sif_path.open("wb") as f:
            f.seek(1024**3 + 1)
            f.write(b"\0")

        mock_run.return_value = MagicMock(returncode=127)

        result = runner.invoke(app, ["build", "--validate", "--output", str(sif_path)])

        assert result.exit_code == 1
        assert "not callable" in result.output.lower()
