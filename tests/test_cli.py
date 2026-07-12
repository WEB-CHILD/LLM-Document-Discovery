"""Tests for CLI helper functions (llm_discovery.cli)."""

from unittest.mock import patch

from llm_discovery.cli import _assemble_data_dir


class TestAssembleDataDir:
    def test_materialises_prompts_into_data_dir(self, tmp_path, monkeypatch):
        """Copies the project ``prompts/`` into the assembled data dir.

        Regression: ``prompts_dir`` was an undefined name (ruff F821) at the
        copy step, so ``_assemble_data_dir`` raised ``NameError`` before it
        could stage the category YAMLs for upload.

        ``prepare_corpus`` (prep-db + preflight) is a separately-tested
        collaborator that reads schema/input assets; it is stubbed here so the
        test isolates the asset-assembly behaviour under test.
        """
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system_prompt.txt").write_text("system prompt")
        # Project-root prompts/ is the source of the 21 category YAMLs.
        (tmp_path / "prompts").mkdir()
        (tmp_path / "prompts" / "category_01.yaml").write_text("id: 1\n")

        data_dir = tmp_path / "data"

        with patch("llm_discovery.local_runner.prepare_corpus"):
            _assemble_data_dir(data_dir, "gpuhopper-gemma4")

        assert (data_dir / "prompts" / "category_01.yaml").exists()
