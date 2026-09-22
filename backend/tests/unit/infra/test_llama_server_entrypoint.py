"""`infra/scripts/llama-server-entrypoint.sh` (E18-E, docs/hld/60-inference-ops.md §8).

Runs the real script with `--print` (no server started, no GPU, no llama-server binary needed —
`SIM_LLAMA_SERVER_BIN` is just a string this test controls) and checks the emitted flag line
against the two profiles' documented `llm.*` blocks (HLD 60 §2.2/§2.3), including the ratified
`--ctx-size = n_ctx * parallel_slots` decision (§8).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[4] / "infra" / "scripts" / "llama-server-entrypoint.sh"

DEV_3060TI_ENV = {
    "SIM_LLAMA_MODEL_PATH": "/models/llm/Qwen3-4B-Q4_K_M.gguf",
    "SIM_LLAMA_ALIAS": "Qwen3-4B",
    "SIM_LLAMA_N_CTX": "4096",
    "SIM_LLAMA_PARALLEL": "2",
    "SIM_LLAMA_N_GPU_LAYERS": "20",
    "SIM_LLAMA_N_BATCH": "512",
    "SIM_LLAMA_N_UBATCH": "256",
    "SIM_LLAMA_FLASH_ATTENTION": "on",
    "SIM_LLAMA_KV_CACHE_TYPE": "q8_0",
}

FINAL_3080TI_12GB_ENV = {
    "SIM_LLAMA_MODEL_PATH": "/models/llm/Qwen3-8B-Q4_K_M.gguf",
    "SIM_LLAMA_ALIAS": "Qwen3-8B",
    "SIM_LLAMA_N_CTX": "4096",
    "SIM_LLAMA_PARALLEL": "2",
    "SIM_LLAMA_N_GPU_LAYERS": "-1",
    "SIM_LLAMA_N_BATCH": "1024",
    "SIM_LLAMA_N_UBATCH": "512",
    "SIM_LLAMA_FLASH_ATTENTION": "on",
    "SIM_LLAMA_KV_CACHE_TYPE": "f16",
}


def _run_print(env_overrides: dict[str, str]) -> str:
    env = {"PATH": "/usr/bin:/bin", **env_overrides}
    result = subprocess.run(
        [str(SCRIPT), "--print"],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_dev_3060ti_flag_line_matches_hld_60_section_8() -> None:
    line = _run_print(DEV_3060TI_ENV)

    assert line.startswith("llama-server ")
    assert "--model /models/llm/Qwen3-4B-Q4_K_M.gguf" in line
    assert "--alias Qwen3-4B" in line
    # HLD 60 §8's ratified decision: --ctx-size = n_ctx * parallel_slots = 4096 * 2.
    assert "--ctx-size 8192" in line
    assert "--parallel 2" in line
    assert "--n-gpu-layers 20" in line
    assert "--batch-size 512 --ubatch-size 256" in line
    assert "--flash-attn on" in line
    assert "--cache-type-k q8_0 --cache-type-v q8_0" in line
    assert "--jinja" in line
    assert '--chat-template-kwargs {"enable_thinking": false}' in line
    assert "--host 0.0.0.0 --port 8080" in line


def test_final_3080ti_12gb_flag_line_matches_hld_60_section_8() -> None:
    line = _run_print(FINAL_3080TI_12GB_ENV)

    assert "--model /models/llm/Qwen3-8B-Q4_K_M.gguf" in line
    assert "--alias Qwen3-8B" in line
    assert "--ctx-size 8192" in line
    assert "--n-gpu-layers -1" in line
    assert "--batch-size 1024 --ubatch-size 512" in line
    assert "--cache-type-k f16 --cache-type-v f16" in line


def test_missing_required_var_fails_loudly_rather_than_guessing() -> None:
    # PATH only (so the shebang's `/usr/bin/env bash` can resolve) — none of the SIM_LLAMA_* vars.
    result = subprocess.run(
        [str(SCRIPT), "--print"],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "SIM_LLAMA_MODEL_PATH" in result.stderr


def test_host_run_overrides_land_on_a_loopback_non_forbidden_port() -> None:
    env = dict(DEV_3060TI_ENV)
    env["SIM_LLAMA_HOST"] = "127.0.0.1"
    env["SIM_LLAMA_PORT"] = "8180"
    env["SIM_LLAMA_SERVER_BIN"] = "/home/example/llama.cpp/build/bin/llama-server"

    line = _run_print(env)

    assert line.startswith("/home/example/llama.cpp/build/bin/llama-server ")
    assert "--host 127.0.0.1 --port 8180" in line
    for forbidden in ("8000", "8001", "8011", "8012", "8016"):
        assert f"--port {forbidden}" not in line
