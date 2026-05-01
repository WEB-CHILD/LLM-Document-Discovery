"""Unit tests for container/lib_vllm_cmd.sh::build_vllm_cmd.

Exercises the CMD-assembly function used by entrypoint.sh. The function is
unit-tested in isolation (sourced into bash with controlled env) so that
new flags (reasoning-parser, language-model-only, ...) can be verified
without running the full container.
"""

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LIB = _REPO_ROOT / "container" / "lib_vllm_cmd.sh"


def _run_build(env: dict[str, str]) -> list[str]:
    """Source lib_vllm_cmd.sh, call build_vllm_cmd, return arg list."""
    script = f"source {_LIB} && build_vllm_cmd"
    result = subprocess.run(
        ["bash", "-c", script],
        env={**env, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.split("\n") if line]


_BASE_ENV = {
    "VLLM_MODEL": "google/gemma-4-31B-it",
    "VLLM_TP": "4",
    "VLLM_GPU_MEM": "0.90",
    "VLLM_MAX_SEQS": "128",
}


class TestBuildVllmCmd:
    def test_base_cmd_contains_core_flags(self):
        cmd = _run_build(_BASE_ENV)
        assert cmd[:2] == ["vllm", "serve"]
        assert "google/gemma-4-31B-it" in cmd
        assert "--tensor-parallel-size" in cmd
        tp_idx = cmd.index("--tensor-parallel-size")
        assert cmd[tp_idx + 1] == "4"
        assert "--gpu-memory-utilization" in cmd
        gpu_idx = cmd.index("--gpu-memory-utilization")
        assert cmd[gpu_idx + 1] == "0.90"
        assert "--max-num-seqs" in cmd
        seqs_idx = cmd.index("--max-num-seqs")
        assert cmd[seqs_idx + 1] == "128"
        assert "--trust-remote-code" in cmd

    def test_default_port_is_8000(self):
        cmd = _run_build(_BASE_ENV)
        port_idx = cmd.index("--port")
        assert cmd[port_idx + 1] == "8000"

    def test_custom_port_respected(self):
        cmd = _run_build({**_BASE_ENV, "VLLM_PORT": "9001"})
        port_idx = cmd.index("--port")
        assert cmd[port_idx + 1] == "9001"

    def test_max_model_len_appended_when_set(self):
        cmd = _run_build({**_BASE_ENV, "VLLM_MAX_MODEL_LEN": "131072"})
        assert "--max-model-len" in cmd
        idx = cmd.index("--max-model-len")
        assert cmd[idx + 1] == "131072"

    def test_max_model_len_omitted_when_unset(self):
        cmd = _run_build(_BASE_ENV)
        assert "--max-model-len" not in cmd

    def test_data_parallel_size_appended_when_gt_1(self):
        cmd = _run_build({**_BASE_ENV, "VLLM_DP": "4"})
        assert "--data-parallel-size" in cmd
        idx = cmd.index("--data-parallel-size")
        assert cmd[idx + 1] == "4"

    def test_data_parallel_size_omitted_when_unset(self):
        cmd = _run_build(_BASE_ENV)
        assert "--data-parallel-size" not in cmd

    def test_data_parallel_size_omitted_when_1(self):
        cmd = _run_build({**_BASE_ENV, "VLLM_DP": "1"})
        assert "--data-parallel-size" not in cmd

    def test_reasoning_parser_appended_when_set(self):
        cmd = _run_build({**_BASE_ENV, "VLLM_REASONING_PARSER": "qwen3"})
        assert "--reasoning-parser" in cmd
        idx = cmd.index("--reasoning-parser")
        assert cmd[idx + 1] == "qwen3"

    def test_reasoning_parser_omitted_when_unset(self):
        cmd = _run_build(_BASE_ENV)
        assert "--reasoning-parser" not in cmd

    def test_reasoning_parser_gemma4(self):
        cmd = _run_build({**_BASE_ENV, "VLLM_REASONING_PARSER": "gemma4"})
        idx = cmd.index("--reasoning-parser")
        assert cmd[idx + 1] == "gemma4"

    def test_reasoning_parser_openai_gptoss(self):
        cmd = _run_build({**_BASE_ENV, "VLLM_REASONING_PARSER": "openai_gptoss"})
        idx = cmd.index("--reasoning-parser")
        assert cmd[idx + 1] == "openai_gptoss"

    def test_language_model_only_appended_when_1(self):
        cmd = _run_build({**_BASE_ENV, "VLLM_LANGUAGE_MODEL_ONLY": "1"})
        assert "--language-model-only" in cmd

    def test_language_model_only_omitted_when_unset(self):
        cmd = _run_build(_BASE_ENV)
        assert "--language-model-only" not in cmd

    def test_language_model_only_omitted_when_0(self):
        cmd = _run_build({**_BASE_ENV, "VLLM_LANGUAGE_MODEL_ONLY": "0"})
        assert "--language-model-only" not in cmd
