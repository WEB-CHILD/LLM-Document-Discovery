"""Tests for platform configuration and validation."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from llm_discovery.platform import (
    PlatformConfig,
    generate_hpc_env,
    load_platforms,
    resolve_remote_path,
    stage_container_image,
    submit_gadi_job,
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
        MockConnection.return_value = mock_conn

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
        MockConnection.return_value = mock_conn

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
        MockConnection.return_value = mock_conn

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
