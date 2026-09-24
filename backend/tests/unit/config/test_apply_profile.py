"""`app.config.profile.apply_profile` — the config overlay (E18-A R3).

Precedence: defaults < profile < an explicitly-set `SIM_*` var (env, `.env`, or an explicit
constructor kwarg — `pydantic-settings`' own `model_fields_set`). Also covers the
`voice_turn.*` -> `VoiceTurnConfig` path end to end, and the two start-up call sites
(`app.api.container.build_container`, `voice_agent.wiring.VoiceAgentDeps.build`) refusing to
build anything when the active profile's VRAM margin fails.
"""

from __future__ import annotations

import pytest
from app.application.voice.config import voice_turn_config_from_settings
from app.config.profile import ProfileRefused, apply_profile, load_profile
from app.config.settings import Settings

_REQUIRED_ENV = {
    "SIM_DATABASE_URL": "postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
    "SIM_REDIS_URL": "redis://localhost:56379/0",
    "SIM_JWT_SECRET": "test-only-secret-padded-32-bytes!",
    "SIM_LIVEKIT_URL": "ws://localhost:7880",
    "SIM_LIVEKIT_API_KEY": "devkey",
    "SIM_LIVEKIT_API_SECRET": "devsecret1234567890",
    "SIM_LLM_BASE_URL": "http://localhost:8080/v1",
}


def _clean_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every required `SIM_*` var set, every optional one this module cares about cleared, so a
    test's outcome depends only on what it explicitly sets — never on the ambient shell/Makefile
    environment `make test` happens to export."""
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    for key in (
        "SIM_TTS_PROVIDER",
        "SIM_ASR_DEVICE",
        "SIM_MODEL_PROFILE",
        "SIM_LLM_MODEL_NAME",
        # E20-E R11: Settings.tts_model_variant is aliased onto this name.
        "SIM_TTS_QWEN3_MODEL",
        # E20-G/G6.
        "SIM_TTS_VOICE_MAP",
        "SIM_TTS_DEFAULT_VOICE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_an_explicitly_set_env_var_survives_a_profile_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate's `SIM_TTS_PROVIDER=fake` must keep winning no matter which profile is active."""
    _clean_settings_env(monkeypatch)
    monkeypatch.setenv("SIM_TTS_PROVIDER", "fake")
    settings = Settings()  # type: ignore[call-arg]
    assert "tts_provider" in settings.model_fields_set

    profile = load_profile("DEV_3060TI")
    assert profile.tts.provider == "qwen3_tts"

    overlaid = apply_profile(settings, profile)

    assert overlaid.tts_provider == "fake"


def test_an_explicit_constructor_kwarg_also_survives_a_profile_overlay() -> None:
    """`model_fields_set` covers an explicit init kwarg the same way it covers an env var — the
    pattern every test fixture in this repo uses to build `Settings` (see `tests/conftest.py`)."""
    settings = Settings(
        database_url=_REQUIRED_ENV["SIM_DATABASE_URL"],
        redis_url=_REQUIRED_ENV["SIM_REDIS_URL"],
        jwt_secret=_REQUIRED_ENV["SIM_JWT_SECRET"],
        livekit_url=_REQUIRED_ENV["SIM_LIVEKIT_URL"],
        livekit_api_key=_REQUIRED_ENV["SIM_LIVEKIT_API_KEY"],
        livekit_api_secret=_REQUIRED_ENV["SIM_LIVEKIT_API_SECRET"],
        llm_base_url=_REQUIRED_ENV["SIM_LLM_BASE_URL"],
        tts_provider="fake",
    )

    overlaid = apply_profile(settings, load_profile("DEV_3060TI"))

    assert overlaid.tts_provider == "fake"


def test_a_field_left_at_its_default_is_overlaid_by_the_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`asr_device` defaults to `cuda`; `DEV_3060TI_SHARED` selects CPU ASR and nothing set the
    env var explicitly, so the profile's choice must win over the class default."""
    _clean_settings_env(monkeypatch)
    settings = Settings()  # type: ignore[call-arg]
    assert "asr_device" not in settings.model_fields_set
    assert settings.asr_device == "cuda"

    overlaid = apply_profile(settings, load_profile("DEV_3060TI_SHARED"))

    assert overlaid.asr_device == "cpu"
    assert overlaid.asr_provider == "gigaam"
    assert overlaid.tts_provider == "piper"
    assert overlaid.tts_fallback_provider == "none"


def test_llm_and_asr_selection_blocks_are_overlaid(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_settings_env(monkeypatch)
    settings = Settings()  # type: ignore[call-arg]

    overlaid = apply_profile(settings, load_profile("DEV_3060TI"))

    assert overlaid.llm_provider == "llama_cpp"
    assert overlaid.llm_model_name == "Qwen3.5-2B"
    assert overlaid.llm_interpreter_max_tokens == 138
    assert overlaid.llm_generator_max_tokens == 80
    assert overlaid.asr_model_version == "v3_e2e_ctc"
    assert overlaid.vad_provider == "silero"
    assert overlaid.vad_model_path == "/models/vad/silero_vad.onnx"
    # `llm_base_url` is a REQUIRED Settings field (`_REQUIRED_ENV` always sets it here), so it can
    # never be "left at a default" in this test file — its overlay-when-unset path is exercised by
    # the container/voice-agent integration instead; asserting it here would just restate the
    # required env value.


# -- E20-E R11: tts.device/output_sample_rate/model_variant and vad.device now have a Settings
# counterpart and are overlaid like every other field (previously read straight off ModelProfile
# only) -------------------------------------------------------------------------------------------


def test_tts_device_output_sample_rate_and_vad_device_are_overlaid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clean_settings_env(monkeypatch)
    settings = Settings()  # type: ignore[call-arg]
    assert settings.tts_device == "cuda"  # class default, pre-overlay
    assert settings.vad_device == "cpu"  # class default, pre-overlay

    profile = load_profile("DEV_3060TI")
    assert profile.tts.device == "cuda"
    assert profile.tts.output_sample_rate == 24000
    assert profile.vad.device == "cpu"

    overlaid = apply_profile(settings, profile)

    assert overlaid.tts_device == "cuda"
    assert overlaid.tts_output_sample_rate == 24000
    assert overlaid.vad_device == "cpu"


def test_dev_3060ti_shared_overlays_a_cpu_tts_device(monkeypatch: pytest.MonkeyPatch) -> None:
    """`DEV_3060TI_SHARED` runs Piper on CPU (measured RTF 0.036) — its `tts.device` differs from
    `DEV_3060TI`'s, proving the overlay reads the field, not a hard-coded default."""
    _clean_settings_env(monkeypatch)
    settings = Settings()  # type: ignore[call-arg]

    overlaid = apply_profile(settings, load_profile("DEV_3060TI_SHARED"))

    assert overlaid.tts_device == "cpu"
    assert overlaid.tts_output_sample_rate == 22050


def test_an_explicitly_set_tts_device_survives_the_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_settings_env(monkeypatch)
    monkeypatch.setenv("SIM_TTS_DEVICE", "cpu")
    settings = Settings()  # type: ignore[call-arg]

    overlaid = apply_profile(settings, load_profile("DEV_3060TI"))

    assert overlaid.tts_device == "cpu"
    # the profile's own value, proving the field really was eligible for overlay otherwise:
    assert load_profile("DEV_3060TI").tts.device != "cpu"


def test_tts_model_variant_is_aliased_onto_sim_tts_qwen3_model_and_overlaid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`Settings.tts_model_variant` reads `SIM_TTS_QWEN3_MODEL` — the SAME env var the standalone
    `workers/tts_qwen3` worker process reads directly — not the prefix-derived
    `SIM_TTS_MODEL_VARIANT`."""
    _clean_settings_env(monkeypatch)
    settings = Settings()  # type: ignore[call-arg]
    assert settings.tts_model_variant is None
    assert "tts_model_variant" not in settings.model_fields_set

    # DEV_3060TI ships the MEASURED 0.6B (E20-I: 1.7B peaks at 7448 MB > the 7168 MB budget).
    overlaid = apply_profile(settings, load_profile("DEV_3060TI"))
    assert overlaid.tts_model_variant == "0.6B"

    # An explicit SIM_TTS_QWEN3_MODEL (as the standalone worker itself would read) wins over the
    # profile, same precedence as every other field.
    monkeypatch.setenv("SIM_TTS_QWEN3_MODEL", "1.7B")
    explicit_settings = Settings()  # type: ignore[call-arg]
    assert explicit_settings.tts_model_variant == "1.7B"
    assert "tts_model_variant" in explicit_settings.model_fields_set

    explicit_overlaid = apply_profile(explicit_settings, load_profile("DEV_3060TI"))
    assert explicit_overlaid.tts_model_variant == "1.7B"


def test_dev_3060ti_shared_yields_cpu_asr_and_cpu_piper_through_the_overlay_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E18-A2: the manager's specific acceptance check — nothing but `apply_profile` is needed to
    turn a default `Settings()` into `DEV_3060TI_SHARED`'s CPU ASR + CPU Piper TTS selection."""
    _clean_settings_env(monkeypatch)
    settings = Settings()  # type: ignore[call-arg]

    overlaid = apply_profile(settings, load_profile("DEV_3060TI_SHARED"))

    assert overlaid.asr_provider == "gigaam"
    assert overlaid.asr_device == "cpu"
    assert overlaid.asr_compute_type == "float32"
    assert overlaid.tts_provider == "piper"
    assert overlaid.tts_piper_voice_path == "/models/tts/piper/ru_RU-irina-medium.onnx"
    assert overlaid.tts_voice_id == "ru_RU-irina-medium"
    assert overlaid.tts_fallback_provider == "none"


def test_llm_request_timeout_overlays_both_interpreter_and_generator_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E18-A2 R3: `llm.request_timeout_ms` has no finer interpreter/generator split of its own, so
    it overlays BOTH existing `Settings` timeout fields."""
    _clean_settings_env(monkeypatch)
    settings = Settings()  # type: ignore[call-arg]
    assert settings.llm_interpreter_timeout_ms == 2500  # class default, pre-overlay
    assert settings.llm_generator_timeout_ms == 3000  # class default, pre-overlay

    profile = load_profile("DEV_3060TI")
    assert profile.llm.request_timeout_ms == 3000

    overlaid = apply_profile(settings, profile)

    assert overlaid.llm_interpreter_timeout_ms == 3000
    assert overlaid.llm_generator_timeout_ms == 3000


def test_an_explicit_interpreter_timeout_survives_the_request_timeout_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Precedence still applies per field: an explicitly-set interpreter timeout is untouched even
    though the generator timeout (left at its default) is overlaid from the same profile key."""
    _clean_settings_env(monkeypatch)
    monkeypatch.setenv("SIM_LLM_INTERPRETER_TIMEOUT_MS", "9999")
    settings = Settings()  # type: ignore[call-arg]

    overlaid = apply_profile(settings, load_profile("DEV_3060TI"))

    assert overlaid.llm_interpreter_timeout_ms == 9999
    assert overlaid.llm_generator_timeout_ms == 3000


def test_tts_model_path_and_voice_id_follow_the_selected_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`tts.model_path`/`tts.voice_id` map to DIFFERENT `Settings` fields depending on which TTS
    provider the profile actually selects (Qwen3TTS vs. PiperTTS are keyed differently)."""
    _clean_settings_env(monkeypatch)

    qwen3_overlaid = apply_profile(Settings(), load_profile("DEV_3060TI"))  # type: ignore[call-arg]
    assert qwen3_overlaid.tts_qwen3_model_dir == "/models/tts/qwen3-tts"
    assert qwen3_overlaid.tts_qwen3_speaker == "Serena"

    piper_overlaid = apply_profile(Settings(), load_profile("DEV_3060TI_SHARED"))  # type: ignore[call-arg]
    assert piper_overlaid.tts_piper_voice_path == "/models/tts/piper/ru_RU-irina-medium.onnx"
    assert piper_overlaid.tts_voice_id == "ru_RU-irina-medium"


def test_an_explicitly_set_tts_qwen3_model_dir_survives_the_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clean_settings_env(monkeypatch)
    monkeypatch.setenv("SIM_TTS_QWEN3_MODEL_DIR", "/an/explicit/override")
    settings = Settings()  # type: ignore[call-arg]

    overlaid = apply_profile(settings, load_profile("DEV_3060TI"))

    assert overlaid.tts_qwen3_model_dir == "/an/explicit/override"
    # the profile's own value, proving the field really was eligible for overlay otherwise:
    assert load_profile("DEV_3060TI").tts.model_path != "/an/explicit/override"


def test_voice_turn_block_is_overlaid_into_voiceturnconfig(monkeypatch: pytest.MonkeyPatch) -> None:
    """`voice_turn.*` -> the `SIM_VOICE_*` fields `VoiceTurnConfig` is built from (R3), including
    the additive `reconnect_grace_s`."""
    _clean_settings_env(monkeypatch)
    settings = Settings()  # type: ignore[call-arg]

    profile = load_profile("DEV_3060TI")
    # 320: a multiple of vad_frame_ms=32 (so VoiceTurnConfig's rounding validator is a no-op here)
    # and still inside SPEC §17's 250-350 target band, so this exercises only the overlay path.
    distinctive_voice_turn = profile.voice_turn.model_copy(
        update={"endpoint_silence_ms": 320, "reconnect_grace_s": 45}
    )
    profile = profile.model_copy(update={"voice_turn": distinctive_voice_turn})

    overlaid = apply_profile(settings, profile)
    turn_config = voice_turn_config_from_settings(overlaid)

    assert turn_config.endpoint_silence_ms == 320
    assert turn_config.reconnect_grace_s == 45


def test_apply_profile_is_a_no_op_when_every_field_is_already_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No profile key has a `Settings` counterpart the caller did not already set -> the same
    `Settings` instance-equivalent values come back (nothing to overlay)."""
    _clean_settings_env(monkeypatch)
    for key in (
        "SIM_LLM_PROVIDER",
        "SIM_LLM_MODEL_NAME",
        "SIM_LLM_MODEL_PATH",
        "SIM_LLM_N_CTX",
        "SIM_LLM_INTERPRETER_MAX_TOKENS",
        "SIM_LLM_GENERATOR_MAX_TOKENS",
        "SIM_LLM_INTERPRETER_TIMEOUT_MS",
        "SIM_LLM_GENERATOR_TIMEOUT_MS",
        "SIM_TTS_QWEN3_MODEL_DIR",
        "SIM_TTS_QWEN3_SPEAKER",
        "SIM_ASR_PROVIDER",
        "SIM_ASR_MODEL_VERSION",
        "SIM_ASR_MODEL_DIR",
        "SIM_ASR_DEVICE",
        "SIM_ASR_COMPUTE_TYPE",
        "SIM_TTS_FALLBACK_PROVIDER",
        "SIM_VAD_PROVIDER",
        "SIM_VAD_MODEL_PATH",
        "SIM_VAD_DEVICE",
        "SIM_TTS_DEVICE",
        "SIM_TTS_OUTPUT_SAMPLE_RATE",
        "SIM_TTS_QWEN3_MODEL",
        "SIM_VOICE_SPEECH_START_THRESHOLD",
        "SIM_VOICE_SPEECH_END_THRESHOLD",
        "SIM_VOICE_SPEECH_START_MIN_MS",
        "SIM_VOICE_ENDPOINT_SILENCE_MS",
        "SIM_VOICE_PRE_ROLL_MS",
        "SIM_VOICE_BARGE_IN_MIN_SPEECH_MS",
        "SIM_VOICE_MAX_TURN_MS",
        "SIM_VOICE_MIN_TURN_MS",
        "SIM_VOICE_VAD_FRAME_MS",
        "SIM_VOICE_OUTBOUND_QUEUE_MS",
        "SIM_VOICE_TTS_CHUNK_MS",
        "SIM_VOICE_PARTIAL_ASR_ENABLED",
        "SIM_VOICE_PARTIAL_INTERVAL_MS",
        "SIM_VOICE_RECONNECT_GRACE_S",
        # E20-I: the Piper fallback's voice file and the three TTS guards.
        "SIM_TTS_PIPER_VOICE_PATH",
        "SIM_TTS_FIRST_CHUNK_TIMEOUT_MS",
        "SIM_TTS_TIMEOUT_MS",
        "SIM_TTS_WARMUP_TIMEOUT_MS",
    ):
        monkeypatch.setenv(
            key,
            "fake" if key.endswith(("PROVIDER", "VERSION")) else "0",
        )
    monkeypatch.setenv("SIM_TTS_PROVIDER", "fake")
    # E20-G/G6: typed, so they cannot take the "0" the loop above sets.
    monkeypatch.setenv("SIM_TTS_VOICE_MAP", "{}")
    monkeypatch.setenv("SIM_TTS_DEFAULT_VOICE", "fake")
    settings = Settings()  # type: ignore[call-arg]

    overlaid = apply_profile(settings, load_profile("DEV_3060TI"))

    assert overlaid is settings


# -- start-up refusal (DO item 5: "process start-up refusal exits non-zero") ---------------------


def test_build_container_propagates_profile_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A `ProfileRefused` raised before `Container(...)` is ever constructed propagates as an
    uncaught exception out of `build_container()` — which is what gives `uvicorn ... --factory`
    its non-zero exit code at process start-up. Never caught and downgraded to a warning.

    Imported inside the test, not at module scope: `app.api.container` pulls in the rest of the
    composition root (every health probe, every use case), which several other E18 tasks are
    editing in this same working tree right now (CONCURRENCY) — a transient breakage there must
    not take down collection of this whole module's other, unrelated tests.
    """
    from app.api.container import build_container

    _clean_settings_env(monkeypatch)
    monkeypatch.setenv("SIM_MODEL_PROFILE", "FINAL_3080TI_12GB")
    settings = Settings()  # type: ignore[call-arg]

    with pytest.raises(ProfileRefused):
        build_container(settings)


def test_voice_agent_deps_build_for_startup_propagates_profile_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`build_for_startup` is the profile-aware entry point real code should call at process
    start-up; the plain `build` stays profile-agnostic so every existing test is unaffected
    (see `VoiceAgentDeps.build`'s own docstring)."""
    from voice_agent.wiring import VoiceAgentDeps

    _clean_settings_env(monkeypatch)
    monkeypatch.setenv("SIM_MODEL_PROFILE", "FINAL_3080TI_16GB")
    settings = Settings()  # type: ignore[call-arg]

    with pytest.raises(ProfileRefused):
        VoiceAgentDeps.build_for_startup(settings, clock=None, uow_factory=None)  # type: ignore[arg-type]


# --- E20-G/G6: tts.voice_map / tts.default_voice --------------------------------------------------


def test_tts_voice_map_and_default_voice_are_overlaid_from_the_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scenario's logical `ru_female_adult_01` must reach the provider as a NATIVE voice."""
    _clean_settings_env(monkeypatch)
    settings = Settings()  # type: ignore[call-arg]

    overlaid = apply_profile(settings, load_profile("DEV_3060TI"))

    # I3 E6c (HLD 80 §80.4.1): the ДДС phone's male persona voices, verified against the
    # installed `qwen_tts` (Ryan, Aiden).
    assert overlaid.tts_voice_map == {
        "ru_female_adult_01": "Serena",
        "ru_male_adult_01": "Ryan",
        "ru_male_adult_02": "Aiden",
    }
    assert overlaid.tts_default_voice == "Serena"

    # The Piper-primary profile maps the same logical id onto ITS native voice.
    piper = apply_profile(Settings(), load_profile("DEV_3060TI_SHARED"))  # type: ignore[call-arg]
    assert piper.tts_voice_map == {"ru_female_adult_01": "ru_RU-irina-medium"}
    assert piper.tts_default_voice == "ru_RU-irina-medium"


def test_default_voice_falls_back_to_the_profiles_own_voice_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A profile that declares no `tts.default_voice` behaves exactly as it did before E20-G."""
    _clean_settings_env(monkeypatch)
    profile = load_profile("DEV_3060TI")
    stripped = profile.model_copy(
        update={"tts": profile.tts.model_copy(update={"default_voice": None})}
    )

    overlaid = apply_profile(Settings(), stripped)  # type: ignore[call-arg]

    assert overlaid.tts_default_voice == profile.tts.voice_id


def test_an_explicitly_set_voice_map_survives_the_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_settings_env(monkeypatch)
    monkeypatch.setenv("SIM_TTS_VOICE_MAP", '{"ru_female_adult_01": "Vivian"}')
    settings = Settings()  # type: ignore[call-arg]

    overlaid = apply_profile(settings, load_profile("DEV_3060TI"))

    assert overlaid.tts_voice_map == {"ru_female_adult_01": "Vivian"}
    assert load_profile("DEV_3060TI").tts.voice_map != {"ru_female_adult_01": "Vivian"}


def test_every_shipped_profile_maps_every_logical_voice_id_the_example_scenarios_use() -> None:
    """A scenario voice id with no mapping is a silent caller waiting to happen (E20-C item 3)."""
    import re
    from pathlib import Path

    logical_ids = {
        match.group(1)
        for path in Path("scenarios/examples").rglob("*.yaml")
        for match in re.finditer(r'^\s*voice_id:\s*"?([^"\s]+)"?\s*$', path.read_text(), re.M)
    }
    assert logical_ids, "no caller_profile.voice_id found in scenarios/examples"
    for name in ("DEV_3060TI", "DEV_3060TI_SHARED", "FINAL_3080TI_12GB", "FINAL_3080TI_16GB"):
        voice_map = load_profile(name).tts.voice_map
        assert logical_ids <= set(voice_map), f"{name}: unmapped {logical_ids - set(voice_map)}"


# -- E20-I: what a whole-utterance TTS primary needs from its profile ----------------------------


def test_dev_profile_sizes_the_tts_guards_from_measurement_and_wires_the_piper_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DEV_3060TI: Qwen3-TTS first audio p95 11078 ms / max 14771 ms (E19) -> 12000 / 15000; the
    warm-up gets `warmup.timeout_ms`; the Piper FALLBACK gets the profile's container path."""
    _clean_settings_env(monkeypatch)
    overlaid = apply_profile(Settings(), load_profile("DEV_3060TI"))  # type: ignore[call-arg]
    assert overlaid.tts_first_chunk_timeout_ms == 12000
    assert overlaid.tts_timeout_ms == 15000
    assert overlaid.tts_warmup_timeout_ms == 60000
    assert overlaid.tts_piper_voice_path == "/models/tts/piper/ru_RU-irina-medium.onnx"


def test_a_streaming_primary_keeps_the_default_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEV_3060TI_SHARED's primary is Piper (streams per unit, p95 405 ms): defaults stand."""
    _clean_settings_env(monkeypatch)
    overlaid = apply_profile(Settings(), load_profile("DEV_3060TI_SHARED"))  # type: ignore[call-arg]
    assert overlaid.tts_first_chunk_timeout_ms == 1500
    assert overlaid.tts_timeout_ms == 8000
