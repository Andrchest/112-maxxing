"""`app.config.profile_env._emit_lines` (E18-E: the llama-server env emitter).

Exercises `_emit_lines` against a small stub object, not against `app.config.profile.ModelProfile`
directly — this test must keep passing regardless of the exact landing order between this task
(E18-E) and E18-A's `app.config.profile` module, since both were assigned to run in the same
working tree in parallel (see this task's brief, CONCURRENCY).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.config.profile_env import _emit_lines


def _stub_profile(**llm_overrides: object) -> SimpleNamespace:
    llm = SimpleNamespace(
        model_path="/models/llm/Qwen3-4B-Q4_K_M.gguf",
        model_name="Qwen3-4B",
        n_ctx=4096,
        parallel_slots=2,
        n_gpu_layers=20,
        n_batch=512,
        n_ubatch=256,
        flash_attention="on",
        kv_cache_type="q8_0",
    )
    for key, value in llm_overrides.items():
        setattr(llm, key, value)
    return SimpleNamespace(profile_name="DEV_3060TI", llm=llm)


def test_emits_the_documented_sim_llama_keys_for_dev_3060ti() -> None:
    lines = _emit_lines(_stub_profile())

    assert lines == [
        "SIM_MODEL_PROFILE=DEV_3060TI",
        "SIM_LLAMA_MODEL_PATH=/models/llm/Qwen3-4B-Q4_K_M.gguf",
        "SIM_LLAMA_ALIAS=Qwen3-4B",
        "SIM_LLAMA_N_CTX=4096",
        "SIM_LLAMA_PARALLEL=2",
        "SIM_LLAMA_N_GPU_LAYERS=20",
        "SIM_LLAMA_N_BATCH=512",
        "SIM_LLAMA_N_UBATCH=256",
        "SIM_LLAMA_FLASH_ATTENTION=on",
        "SIM_LLAMA_KV_CACHE_TYPE=q8_0",
    ]


def test_reflects_a_different_profile_full_gpu_offload() -> None:
    profile = _stub_profile(model_path="/models/llm/Qwen3-8B-Q4_K_M.gguf", n_gpu_layers=-1)
    profile.profile_name = "FINAL_3080TI_12GB"

    lines = _emit_lines(profile)

    assert "SIM_MODEL_PROFILE=FINAL_3080TI_12GB" in lines
    assert "SIM_LLAMA_MODEL_PATH=/models/llm/Qwen3-8B-Q4_K_M.gguf" in lines
    assert "SIM_LLAMA_N_GPU_LAYERS=-1" in lines
