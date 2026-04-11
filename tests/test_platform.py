"""Tests for platform configuration and validation."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from llm_discovery.platform import (
    PlatformConfig,
    load_platforms,
    resolve_remote_path,
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
