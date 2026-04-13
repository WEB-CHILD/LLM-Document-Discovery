"""Tests for the init command (first-time HPC setup)."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from llm_discovery.cli import app

runner = CliRunner()


class TestInitCommand:
    @patch("llm_discovery.cli._ensure_validated", return_value=True)
    @patch("llm_discovery.platform.load_platforms")
    @patch("llm_discovery.platform.stage_container_image")
    @patch("llm_discovery.platform.upload_hpc_env")
    @patch("llm_discovery.platform.upload_model_cache")
    @patch("llm_discovery.platform.submit_ping_job")
    @patch("llm_discovery.platform.check_job_status", return_value="finished")
    @patch(
        "llm_discovery.platform.fetch_remote_file",
        return_value="PASS: vLLM responded to PING",
    )
    def test_init_success(
        self, _mock_fetch, _mock_status, mock_ping, mock_model, mock_env,
        mock_stage, mock_platforms, _mock_validate, tmp_path, monkeypatch
    ):
        """AC2.1: init stages .sif and calls all platform functions in order."""
        monkeypatch.chdir(tmp_path)
        sif = tmp_path / "pipeline.sif"
        sif.write_bytes(b"fake")
        # Create config file so existence check passes (load_platforms is mocked)
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "platforms.yaml").write_text("")

        mock_config = MagicMock()
        mock_platforms.return_value.platforms = {"gadi": mock_config}
        mock_stage.return_value = "/scratch/ab12/containers/pipeline.sif"
        mock_ping.return_value = "12345.gadi-pbs"

        # Track call order via a shared list
        call_order = []

        def _track(name, rv=None):
            def _side_effect(*_a, **_k):
                call_order.append(name)
                return rv
            return _side_effect

        mock_stage.side_effect = _track(
            "stage", "/scratch/ab12/containers/pipeline.sif"
        )
        mock_env.side_effect = _track("env")
        mock_model.side_effect = _track("model")
        mock_ping.side_effect = _track("ping", "12345.gadi-pbs")

        result = runner.invoke(app, [
            "init", "--platform", "gadi", "--project", "ab12",
            "--gpu-queue", "gpuvolta", "--container-image", str(sif)
        ])

        assert result.exit_code == 0, f"Output:\n{result.output}"

        # Verify all four platform functions were called with correct args
        mock_stage.assert_called_once_with(mock_config, "ab12", sif)
        mock_env.assert_called_once_with(mock_config, "ab12", "gpuvolta")
        mock_model.assert_called_once_with(mock_config, "ab12", "gpuvolta")
        mock_ping.assert_called_once_with(
            mock_config, "ab12", "gpuvolta", "/scratch/ab12/containers/pipeline.sif"
        )

        # Verify call order: stage -> env -> model -> ping
        assert call_order == ["stage", "env", "model", "ping"]

        assert "12345.gadi-pbs" in result.output

    @patch("llm_discovery.cli._ensure_validated", return_value=True)
    def test_init_sif_not_found(self, _mock_validate, tmp_path, monkeypatch):
        """AC2.5: init fails with clear error if .sif doesn't exist."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, [
            "init", "--platform", "gadi", "--project", "ab12",
            "--container-image", "nonexistent.sif"
        ])

        assert result.exit_code == 1
        flat_output = result.output.replace("\n", " ").lower()
        assert "container image not found" in flat_output
        assert "build it first" in flat_output

    @patch("llm_discovery.cli._ensure_validated", return_value=False)
    def test_init_validation_fails(self, _mock_validate, tmp_path, monkeypatch):
        """Init exits if platform validation fails."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, [
            "init", "--platform", "gadi", "--project", "ab12"
        ])

        assert result.exit_code == 1
        assert "validation failed" in result.output.lower()
