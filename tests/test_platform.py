"""Tests for platform configuration and validation."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from llm_discovery.platform import (
    PlatformConfig,
    generate_hpc_env,
    get_gpu_queue_config,
    load_platforms,
    resolve_remote_path,
    rsync_to_remote,
    stage_container_image,
    submit_gadi_job,
    submit_ping_job,
    upload_model_cache,
    validate_platform,
)


class TestLoadPlatforms:
    def test_loads_real_config(self):
        config_path = Path(__file__).parent.parent / "config" / "platforms.yaml"
        config = load_platforms(config_path)
        assert "gadi" in config.platforms
        assert "ucloud" in config.platforms

    def test_gadi_has_required_fields(self):
        config_path = Path(__file__).parent.parent / "config" / "platforms.yaml"
        config = load_platforms(config_path)
        gadi = config.platforms["gadi"]
        assert gadi.display_name == "NCI Gadi"
        assert gadi.ssh_host == "gadi.nci.org.au"
        assert gadi.gpu_type == "V100"
        assert len(gadi.checks) == 4

    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_platforms(tmp_path / "nonexistent.yaml")

    def test_raises_on_invalid_yaml(self, tmp_path):
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("platforms:\n  gadi:\n    display_name: 123\n")
        with pytest.raises(ValidationError):
            load_platforms(bad_yaml)


class TestResolveRemotePath:
    def test_replaces_project_placeholder(self):
        platform = PlatformConfig(
            display_name="Test",
            remote_base="/scratch/{project}/llm-discovery",
            gpu_type="V100",
            submission="pbs",
        )
        assert resolve_remote_path(platform, "ab12") == "/scratch/ab12/llm-discovery"


class TestValidatePlatform:
    def test_non_ssh_platform_skips(self):
        platform = PlatformConfig(
            display_name="UCloud",
            ssh_host=None,
            remote_base="/work/llm-discovery",
            gpu_type="H100",
            submission="api",
            checks=[{"name": "API check", "command": None}],
        )
        results = validate_platform(platform)
        assert len(results) == 1
        assert results[0][1] is True  # passed
        assert "skipped" in results[0][2]

    @patch("llm_discovery.platform.Connection")
    def test_ssh_checks_pass(self, MockConnection):
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.ok = True
        mock_result.stdout = "gadi-login-01\n"
        mock_conn.run.return_value = mock_result
        MockConnection.return_value = mock_conn

        platform = PlatformConfig(
            display_name="Test HPC",
            ssh_host="test.hpc.org",
            remote_base="/scratch/{project}/test",
            gpu_type="V100",
            submission="pbs",
            checks=[{"name": "SSH connectivity", "command": "hostname"}],
        )
        results = validate_platform(platform)
        assert len(results) == 1
        assert results[0][0] == "SSH connectivity"
        assert results[0][1] is True

    @patch("llm_discovery.platform.Connection")
    def test_ssh_checks_fail(self, MockConnection):
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.ok = False
        mock_result.stderr = "command not found"
        mock_conn.run.return_value = mock_result
        MockConnection.return_value = mock_conn

        platform = PlatformConfig(
            display_name="Test HPC",
            ssh_host="test.hpc.org",
            remote_base="/scratch/test",
            gpu_type="V100",
            submission="pbs",
            checks=[{"name": "uv available", "command": "which uv"}],
        )
        results = validate_platform(platform)
        assert len(results) == 1
        assert results[0][1] is False

    @patch("llm_discovery.platform.Connection")
    def test_project_placeholder_resolved(self, MockConnection):
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.ok = True
        mock_result.stdout = ""
        mock_conn.run.return_value = mock_result
        MockConnection.return_value = mock_conn

        platform = PlatformConfig(
            display_name="Test",
            ssh_host="test.hpc.org",
            remote_base="/scratch/{project}/test",
            gpu_type="V100",
            submission="pbs",
            checks=[{"name": "scratch check", "command": "test -d /scratch/{project}"}],
        )
        validate_platform(platform, project="ab12")
        mock_conn.run.assert_called_once_with(
            "test -d /scratch/ab12", warn=True, hide=True
        )


class TestStageContainerImage:
    def _make_platform(self):
        return PlatformConfig(
            display_name="Test HPC",
            ssh_host="gadi.nci.org.au",
            remote_base="/scratch/{project}/llm-discovery",
            gpu_type="V100",
            submission="pbs",
        )

    def _compute_sha256(self, path):
        import hashlib

        sha256 = hashlib.sha256()
        with Path(path).open("rb") as f:
            while chunk := f.read(65536):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _mock_sha_stdout(self, sha_hash):
        remote = "/scratch/ab12/containers/pipeline.sif"
        return f"{sha_hash}  {remote}\n"

    @patch("llm_discovery.platform.subprocess.run")
    @patch("llm_discovery.platform.Connection")
    def test_stages_sif_to_correct_remote_path(
        self, MockConnection, mock_subprocess, tmp_path
    ):
        sif = tmp_path / "pipeline.sif"
        sif.write_bytes(b"fake container image data")
        local_hash = self._compute_sha256(sif)

        mock_conn = MagicMock()
        mock_sha_result = MagicMock()
        mock_sha_result.stdout = self._mock_sha_stdout(local_hash)
        mock_conn.run.return_value = mock_sha_result
        MockConnection.return_value.__enter__ = MagicMock(return_value=mock_conn)

        platform = self._make_platform()
        remote = "/scratch/ab12/containers/pipeline.sif"
        result = stage_container_image(platform, "ab12", sif)

        assert result == remote
        mock_subprocess.assert_called_once()
        rsync_args = mock_subprocess.call_args[0][0]
        assert rsync_args[0] == "rsync"
        assert str(sif) in rsync_args
        assert f"gadi.nci.org.au:{remote}" in rsync_args

    def test_raises_on_missing_sif(self, tmp_path):
        platform = self._make_platform()
        with pytest.raises(FileNotFoundError, match="Container image not found"):
            stage_container_image(
                platform, "ab12", tmp_path / "nonexistent.sif"
            )

    @patch("llm_discovery.platform.subprocess.run")
    @patch("llm_discovery.platform.Connection")
    def test_raises_on_checksum_mismatch(
        self, MockConnection, _mock_subprocess, tmp_path
    ):
        sif = tmp_path / "pipeline.sif"
        sif.write_bytes(b"fake container image data")

        mock_conn = MagicMock()
        mock_sha_result = MagicMock()
        bad_hash = "0" * 64
        mock_sha_result.stdout = self._mock_sha_stdout(bad_hash)
        mock_conn.run.return_value = mock_sha_result
        MockConnection.return_value.__enter__ = MagicMock(return_value=mock_conn)

        platform = self._make_platform()
        with pytest.raises(RuntimeError, match="SHA256 mismatch"):
            stage_container_image(platform, "ab12", sif)

    @patch("llm_discovery.platform.subprocess.run")
    @patch("llm_discovery.platform.Connection")
    def test_creates_remote_directory(
        self, MockConnection, _mock_subprocess, tmp_path
    ):
        sif = tmp_path / "pipeline.sif"
        sif.write_bytes(b"fake container image data")
        local_hash = self._compute_sha256(sif)

        mock_conn = MagicMock()
        mock_sha_result = MagicMock()
        mock_sha_result.stdout = self._mock_sha_stdout(local_hash)
        mock_conn.run.return_value = mock_sha_result
        MockConnection.return_value.__enter__ = MagicMock(return_value=mock_conn)

        platform = self._make_platform()
        stage_container_image(platform, "ab12", sif)

        # First call should be mkdir -p
        first_call = mock_conn.run.call_args_list[0]
        assert first_call[0][0] == "mkdir -p /scratch/ab12/containers"


class TestGenerateHpcEnv:
    def test_gpuvolta_config(self):
        result = generate_hpc_env("gpuvolta")
        assert 'export VLLM_MODEL="google/gemma-4-31B-it"' in result
        assert 'export VLLM_TP="4"' in result
        assert 'export VLLM_GPU_MEM="0.90"' in result
        assert 'export VLLM_MAX_SEQS="64"' in result
        assert result.startswith("#!/usr/bin/env bash\n")

    def test_gpuhopper_config(self):
        result = generate_hpc_env("gpuhopper")
        assert 'export VLLM_MODEL="openai/gpt-oss-120b"' in result
        assert 'export VLLM_TP="4"' in result
        assert 'export VLLM_GPU_MEM="0.92"' in result
        assert 'export VLLM_MAX_SEQS="384"' in result

    def test_unknown_queue_raises(self):
        with pytest.raises(ValueError, match="Unknown GPU queue"):
            generate_hpc_env("nonexistent")


class TestPBSTemplate:
    def test_pbs_template_contains_singularity_exec(self):
        template_path = Path(__file__).parent.parent / "hpc" / "gadi.pbs.template"
        content = template_path.read_text()
        assert "singularity exec --nv" in content
        assert "module load singularity" in content
        assert "bash scripts/process_corpus.sh" not in content
        assert "module load python3" not in content

    @patch("llm_discovery.platform.Connection")
    def test_container_path_substituted(self, MockConnection, tmp_path):
        # Create a temporary PBS template
        template_path = tmp_path / "hpc" / "gadi.pbs.template"
        template_path.parent.mkdir(parents=True)
        real_template = Path(__file__).parent.parent / "hpc" / "gadi.pbs.template"
        template_path.write_text(real_template.read_text())

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.stdout = "12345.gadi-pbs\n"
        mock_conn.run.return_value = mock_result
        MockConnection.return_value = mock_conn

        platform = PlatformConfig(
            display_name="Test HPC",
            ssh_host="gadi.nci.org.au",
            remote_base="/scratch/{project}/llm-discovery",
            gpu_type="V100",
            submission="pbs",
        )

        import os

        old_cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            result = submit_gadi_job(
                platform, "ab12", "gpuhopper",
                container_path="/scratch/ab12/containers/pipeline.sif",
            )
        finally:
            os.chdir(old_cwd)

        assert result == "12345.gadi-pbs"
        # Check the PBS script uploaded via conn.put()
        put_call = mock_conn.put.call_args
        pbs_content = put_call[0][0].read()
        assert "{{CONTAINER_PATH}}" not in pbs_content
        assert "/scratch/ab12/containers/pipeline.sif" in pbs_content


class TestRsyncToRemote:
    @patch("llm_discovery.platform.subprocess.run")
    def test_excludes_sif_and_container(self, mock_subprocess):
        platform = PlatformConfig(
            display_name="Test HPC",
            ssh_host="gadi.nci.org.au",
            remote_base="/scratch/{project}/llm-discovery",
            gpu_type="V100",
            submission="pbs",
        )
        rsync_to_remote(platform, Path("/tmp/fake"), "ab12")

        rsync_args = mock_subprocess.call_args[0][0]
        assert "--exclude=*.sif" in rsync_args
        assert "--exclude=container/" in rsync_args


class TestDeploy:
    """Test that the deploy CLI wires staging functions together correctly."""

    @patch("llm_discovery.cli._ensure_validated", return_value=True)
    @patch("llm_discovery.platform.Connection")
    @patch("llm_discovery.platform.subprocess.run")
    def test_deploy_calls_stage_container_image(
        self,
        mock_subprocess,
        MockConnection,
        _mock_validate,
        tmp_path,
    ):
        from typer.testing import CliRunner

        from llm_discovery.cli import app

        # Create a fake .sif file and compute its SHA256
        sif = tmp_path / "pipeline.sif"
        sif.write_bytes(b"fake container image data")

        import hashlib

        sha256 = hashlib.sha256()
        with sif.open("rb") as f:
            while chunk := f.read(65536):
                sha256.update(chunk)
        local_hash = sha256.hexdigest()

        # Create platforms.yaml and PBS template in tmp_path
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "platforms.yaml").write_text(
            "platforms:\n"
            "  gadi:\n"
            "    display_name: NCI Gadi\n"
            "    ssh_host: gadi.nci.org.au\n"
            "    remote_base: /scratch/{project}/llm-discovery\n"
            "    gpu_type: V100\n"
            "    submission: pbs\n"
            "    checks: []\n"
        )
        (tmp_path / "hpc").mkdir()
        real_template = Path(__file__).parent.parent / "hpc" / "gadi.pbs.template"
        (tmp_path / "hpc" / "gadi.pbs.template").write_text(real_template.read_text())

        # Mock Connection — all platform functions use context manager now
        mock_conn = MagicMock()
        mock_sha_result = MagicMock()
        mock_sha_result.stdout = (
            f"{local_hash}  /scratch/ab12/containers/pipeline.sif\n"
        )
        mock_qsub_result = MagicMock()
        mock_qsub_result.stdout = "12345.gadi-pbs\n"
        mock_conn.run.side_effect = [
            mock_sha_result,   # mkdir -p containers (stage_container_image)
            mock_sha_result,   # sha256sum (stage_container_image)
            mock_sha_result,   # mkdir -p data (upload_hpc_env)
            mock_qsub_result,  # qsub (submit_gadi_job)
        ]
        MockConnection.return_value = mock_conn
        MockConnection.return_value.__enter__ = MagicMock(return_value=mock_conn)

        import os

        old_cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            runner = CliRunner()
            result = runner.invoke(
                app,
                [
                    "deploy",
                    "--platform", "gadi",
                    "--project", "ab12",
                    "--gpu-queue", "gpuvolta",
                    "--container-image", str(sif),
                ],
            )
        finally:
            os.chdir(old_cwd)

        assert result.exit_code == 0, f"Deploy failed:\n{result.output}"

        # Verify rsync calls: code sync + .sif staging
        rsync_calls = [
            c for c in mock_subprocess.call_args_list
            if c[0][0][0] == "rsync"
        ]
        assert len(rsync_calls) >= 2
        sif_rsync = [c for c in rsync_calls if str(sif) in str(c[0][0])]
        assert len(sif_rsync) == 1, "Expected one rsync call for .sif staging"

        # Verify hpc_env.sh uploaded
        put_calls = mock_conn.put.call_args_list
        assert len(put_calls) >= 1
        env_content = put_calls[0][0][0].read()
        assert "VLLM_MODEL" in env_content


class TestGetGpuQueueConfig:
    def test_gpuhopper_returns_config(self):
        config = get_gpu_queue_config("gpuhopper")
        assert config["VLLM_MODEL"] == "openai/gpt-oss-120b"
        assert config["VLLM_TP"] == "4"

    def test_gpuvolta_returns_config(self):
        config = get_gpu_queue_config("gpuvolta")
        assert config["VLLM_MODEL"] == "google/gemma-4-31B-it"

    def test_unknown_queue_raises(self):
        with pytest.raises(ValueError, match="Unknown GPU queue"):
            get_gpu_queue_config("nonexistent")


class TestUploadModelCache:
    @patch("llm_discovery.platform.subprocess.run")
    def test_rsync_with_hf_hub_cache(self, mock_run, tmp_path, monkeypatch):
        """AC2.2: Uses $HF_HUB_CACHE when set."""
        monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
        model_dir = tmp_path / "models--google--gemma-4-31B-it"
        model_dir.mkdir()

        platform = PlatformConfig(
            display_name="Test",
            ssh_host="gadi.nci.org.au",
            remote_base="/scratch/{project}/llm-discovery",
            gpu_type="V100",
            submission="pbs",
        )
        upload_model_cache(platform, "ab12", "gpuvolta")

        rsync_args = mock_run.call_args[0][0]
        assert "rsync" in rsync_args[0]
        assert str(model_dir) in rsync_args
        assert "gadi.nci.org.au:/scratch/ab12/hf_cache/hub/" in rsync_args

    @patch("llm_discovery.platform.subprocess.run")
    def test_rsync_with_hf_home(self, mock_run, tmp_path, monkeypatch):
        """AC2.2: Uses $HF_HOME/hub when $HF_HUB_CACHE unset."""
        monkeypatch.delenv("HF_HUB_CACHE", raising=False)
        monkeypatch.setenv("HF_HOME", str(tmp_path))
        hub_dir = tmp_path / "hub"
        hub_dir.mkdir()
        model_dir = hub_dir / "models--google--gemma-4-31B-it"
        model_dir.mkdir()

        platform = PlatformConfig(
            display_name="Test",
            ssh_host="gadi.nci.org.au",
            remote_base="/scratch/{project}/llm-discovery",
            gpu_type="V100",
            submission="pbs",
        )
        upload_model_cache(platform, "ab12", "gpuvolta")

        rsync_args = mock_run.call_args[0][0]
        assert str(model_dir) in rsync_args

    @patch("llm_discovery.platform.subprocess.run")
    def test_rsync_with_default_cache(self, mock_run, tmp_path, monkeypatch):
        """AC2.2: Uses ~/.cache/huggingface/hub when env vars unset."""
        monkeypatch.delenv("HF_HUB_CACHE", raising=False)
        monkeypatch.delenv("HF_HOME", raising=False)
        cache_dir = tmp_path / ".cache" / "huggingface" / "hub"
        cache_dir.mkdir(parents=True)
        model_dir = cache_dir / "models--google--gemma-4-31B-it"
        model_dir.mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        platform = PlatformConfig(
            display_name="Test",
            ssh_host="gadi.nci.org.au",
            remote_base="/scratch/{project}/llm-discovery",
            gpu_type="V100",
            submission="pbs",
        )
        upload_model_cache(platform, "ab12", "gpuvolta")

        rsync_args = mock_run.call_args[0][0]
        assert str(model_dir) in rsync_args

    def test_model_not_found_raises(self, tmp_path, monkeypatch):
        """AC2.4: Missing model dir raises FileNotFoundError."""
        monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
        # Cache exists but model dir doesn't

        platform = PlatformConfig(
            display_name="Test",
            ssh_host="gadi.nci.org.au",
            remote_base="/scratch/{project}/llm-discovery",
            gpu_type="V100",
            submission="pbs",
        )
        with pytest.raises(FileNotFoundError, match="Download first"):
            upload_model_cache(platform, "ab12", "gpuvolta")

    def test_no_cache_dir_raises(self, tmp_path, monkeypatch):
        """AC2.4: No HF cache at all raises FileNotFoundError."""
        monkeypatch.delenv("HF_HUB_CACHE", raising=False)
        monkeypatch.delenv("HF_HOME", raising=False)
        # Point home to a dir without .cache/huggingface/hub
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        platform = PlatformConfig(
            display_name="Test",
            ssh_host="gadi.nci.org.au",
            remote_base="/scratch/{project}/llm-discovery",
            gpu_type="V100",
            submission="pbs",
        )
        with pytest.raises(FileNotFoundError, match="No HuggingFace cache"):
            upload_model_cache(platform, "ab12", "gpuvolta")


class TestSubmitPingJob:
    @patch("llm_discovery.platform.Connection")
    def test_submits_ping_job(self, MockConnection, monkeypatch):
        """AC2.3: Reads template, substitutes placeholders, submits via qsub."""
        monkeypatch.chdir(Path(__file__).parent.parent)  # project root for template

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.stdout = "12345.gadi-pbs\n"
        mock_conn.run.return_value = mock_result
        MockConnection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        MockConnection.return_value.__exit__ = MagicMock(return_value=False)

        platform = PlatformConfig(
            display_name="Test",
            ssh_host="gadi.nci.org.au",
            remote_base="/scratch/{project}/llm-discovery",
            gpu_type="V100",
            submission="pbs",
        )
        job_id = submit_ping_job(
            platform,
            "ab12",
            "gpuvolta",
            "/scratch/ab12/containers/pipeline.sif",
        )

        assert job_id == "12345.gadi-pbs"

        # Verify template substitution via the put call
        put_call = mock_conn.put.call_args
        uploaded_content = put_call[0][0].read()
        assert "gpuvolta" in uploaded_content
        assert "ab12" in uploaded_content
        assert "/scratch/ab12/containers/pipeline.sif" in uploaded_content
        assert "{{GPU_QUEUE}}" not in uploaded_content
        assert "{{NCI_PROJECT}}" not in uploaded_content
        assert "{{CONTAINER_PATH}}" not in uploaded_content
