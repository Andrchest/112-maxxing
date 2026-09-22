"""`app.config.profile_env._emit_lines` (E18-E: the llama-server env emitter).

Exercises `_emit_lines` against a small stub object, not against `app.config.profile.ModelProfile`
directly — this test must keep passing regardless of the exact landing order between this task
(E18-E) and E18-A's `app.config.profile` module, since both were assigned to run in the same
working tree in parallel (see this task's brief, CONCURRENCY).
"""

from __future__ import annotations

from pathlib import Path
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
    tts = SimpleNamespace(provider="piper", model_variant=None)
    return SimpleNamespace(profile_name="DEV_3060TI", llm=llm, tts=tts)


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


# -- E20-G/G8: --models-root ----------------------------------------------------------------------


def test_the_default_models_root_leaves_a_container_path_untouched() -> None:
    """Under compose `/models` IS the mount point, so the mapping is the identity."""
    assert "SIM_LLAMA_MODEL_PATH=/models/llm/Qwen3-4B-Q4_K_M.gguf" in _emit_lines(_stub_profile())


def test_a_host_models_root_rewrites_the_model_path(tmp_path: Path) -> None:
    """`make run-llama-server` passes the host's `./models`; nothing is at `/models` there.

    E20-C's `make up` attempt died on exactly this: `gguf_init_from_file: failed to open GGUF file
    '/models/llm/Qwen3.5-2B-Q4_K_M.gguf' (No such file or directory)`, and its host run had to
    export `SIM_LLAMA_MODEL_PATH` by hand.
    """
    gguf = tmp_path / "llm" / "Qwen3-4B-Q4_K_M.gguf"
    gguf.parent.mkdir(parents=True)
    gguf.write_bytes(b"fake")

    lines = _emit_lines(_stub_profile(), str(tmp_path))

    assert f"SIM_LLAMA_MODEL_PATH={gguf}" in lines
    # Everything else is untouched.
    assert "SIM_LLAMA_ALIAS=Qwen3-4B" in lines


def test_an_absolute_non_container_model_path_is_left_alone(tmp_path: Path) -> None:
    """An operator may point a profile straight at a host file (the owner's read-only GGUFs)."""
    absolute = "/opt/models/custom.gguf"
    lines = _emit_lines(_stub_profile(model_path=absolute), str(tmp_path))
    assert f"SIM_LLAMA_MODEL_PATH={absolute}" in lines


# -- E20: the Qwen3-TTS worker's variant travels through the same file -------------------------


def test_a_qwen3_tts_profile_with_a_variant_emits_sim_tts_qwen3_model() -> None:
    profile = _stub_profile()
    profile.tts = SimpleNamespace(provider="qwen3_tts", model_variant="0.6B")
    assert _emit_lines(profile)[-1] == "SIM_TTS_QWEN3_MODEL=0.6B"


def test_no_variant_or_another_provider_emits_nothing_for_tts() -> None:
    no_variant = _stub_profile()
    no_variant.tts = SimpleNamespace(provider="qwen3_tts", model_variant=None)
    piper = _stub_profile()
    piper.tts = SimpleNamespace(provider="piper", model_variant="0.6B")
    for profile in (no_variant, piper):
        assert not any(line.startswith("SIM_TTS_") for line in _emit_lines(profile))


def test_the_shipped_dev_profile_hands_the_worker_the_measured_0_6b() -> None:
    """DEV_3060TI's measured peak (5560 MB) is the 0.6B; 1.7B peaks at 7448 MB > budget (E20-I)."""
    from app.config.profile import load_profile

    assert "SIM_TTS_QWEN3_MODEL=0.6B" in _emit_lines(load_profile("DEV_3060TI"))
