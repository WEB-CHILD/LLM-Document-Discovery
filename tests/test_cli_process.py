"""Tests for the `process` CLI surface — verifies path overrides thread through."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from llm_discovery.cli import app

runner = CliRunner()


def _make_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a tmp DB, system prompt, and prompts dir so existence checks pass."""
    db = tmp_path / "corpus.db"
    db.write_bytes(b"")
    sp = tmp_path / "system_prompt.txt"
    sp.write_text("you are a classifier")
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    return db, sp, prompts


class TestProcessSystemPromptFlag:
    """--system-prompt PATH overrides the default system_prompt.txt location."""

    @patch("llm_discovery.cli.run_processor")
    def test_custom_system_prompt_threads_through(
        self, mock_run, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        db, sp, prompts = _make_inputs(tmp_path)
        custom_sp = tmp_path / "adapter_prompt.txt"
        custom_sp.write_text("downstream adapter prompt")

        result = runner.invoke(app, [
            "process",
            "--db", str(db),
            "--concurrency", "1",
            "--system-prompt", str(custom_sp),
            "--prompts-dir", str(prompts),
        ])

        assert result.exit_code == 0, f"Output:\n{result.output}"
        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        assert kwargs["system_prompt_path"] == custom_sp

    @patch("llm_discovery.cli.run_processor")
    def test_default_system_prompt_is_system_prompt_txt(
        self, mock_run, tmp_path, monkeypatch
    ):
        """No --system-prompt flag → still loads ./system_prompt.txt (backward compat)."""
        monkeypatch.chdir(tmp_path)
        db, _sp, prompts = _make_inputs(tmp_path)

        result = runner.invoke(app, [
            "process",
            "--db", str(db),
            "--concurrency", "1",
            "--prompts-dir", str(prompts),
        ])

        assert result.exit_code == 0, f"Output:\n{result.output}"
        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        assert kwargs["system_prompt_path"] == Path("system_prompt.txt")

    def test_missing_custom_system_prompt_errors_cleanly(
        self, tmp_path, monkeypatch
    ):
        """Existence check applies to the user-supplied path, not the default."""
        monkeypatch.chdir(tmp_path)
        db, _sp, prompts = _make_inputs(tmp_path)
        missing = tmp_path / "does_not_exist.txt"

        result = runner.invoke(app, [
            "process",
            "--db", str(db),
            "--concurrency", "1",
            "--system-prompt", str(missing),
            "--prompts-dir", str(prompts),
        ])

        assert result.exit_code == 1
        assert str(missing) in result.output or "not found" in result.output.lower()


class TestProcessPromptsDirFlag:
    """--prompts-dir PATH overrides the default prompts/ location."""

    @patch("llm_discovery.cli.run_processor")
    def test_custom_prompts_dir_threads_through(
        self, mock_run, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        db, sp, _prompts = _make_inputs(tmp_path)
        custom_prompts = tmp_path / "adapter_prompts"
        custom_prompts.mkdir()

        result = runner.invoke(app, [
            "process",
            "--db", str(db),
            "--concurrency", "1",
            "--system-prompt", str(sp),
            "--prompts-dir", str(custom_prompts),
        ])

        assert result.exit_code == 0, f"Output:\n{result.output}"
        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        assert kwargs["prompts_dir"] == custom_prompts

    def test_missing_custom_prompts_dir_errors_cleanly(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        db, sp, _prompts = _make_inputs(tmp_path)
        missing = tmp_path / "no_such_dir"

        result = runner.invoke(app, [
            "process",
            "--db", str(db),
            "--concurrency", "1",
            "--system-prompt", str(sp),
            "--prompts-dir", str(missing),
        ])

        assert result.exit_code == 1
        assert str(missing) in result.output or "not found" in result.output.lower()
