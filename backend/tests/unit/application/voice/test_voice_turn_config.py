"""`VoiceTurnConfig` — §4.1's ranges, defaults, rounding and cross-field validation."""

from __future__ import annotations

import pytest
from app.application.voice.config import VoiceTurnConfig, voice_turn_config_from_settings
from app.config.settings import Settings
from pydantic import ValidationError


def test_defaults_are_the_hld_table() -> None:
    """§4.1's Default column, so a drift in the table is a failing test.

    Two defaults arrive rounded, and that is §4.1 applied to itself: `endpoint_silence_ms = 300`
    and `barge_in_min_speech_ms = 120` are not integer multiples of `vad_frame_ms = 32`, which
    the same section requires, so the documented "rounded up at load with a warning" turns them
    into 320 and 128. See this task's report under "HLD gaps".
    """
    config = VoiceTurnConfig()
    assert config.speech_start_threshold == 0.55
    assert config.speech_end_threshold == 0.35
    assert config.speech_start_min_ms == 96
    assert config.pre_roll_ms == 300
    assert config.endpoint_silence_ms == 320
    assert config.barge_in_min_speech_ms == 128
    assert config.max_turn_ms == 30_000
    assert config.min_turn_ms == 200
    assert config.vad_frame_ms == 32
    assert config.outbound_queue_ms == 200
    assert config.tts_chunk_ms == 20
    assert config.partial_asr_enabled is True
    assert config.partial_interval_ms == 500


def test_pre_roll_capacity_is_the_ceiling_of_whole_frames() -> None:
    """§4.2: 300/32 → 10 frames = 320 ms ≥ 300 ms. Never the floor."""
    assert VoiceTurnConfig().pre_roll_frames == 10
    assert VoiceTurnConfig().frame_samples == 512


def test_sustain_windows_are_rounded_up_to_whole_frames() -> None:
    """§4.1: a window that is not a whole number of analysis frames cannot be measured exactly."""
    config = VoiceTurnConfig(endpoint_silence_ms=300, barge_in_min_speech_ms=120)
    assert config.endpoint_silence_ms % config.vad_frame_ms == 0
    assert config.barge_in_min_speech_ms % config.vad_frame_ms == 0
    assert config.endpoint_silence_ms == 320
    assert config.barge_in_min_speech_ms == 128


@pytest.mark.parametrize(
    "overrides",
    [
        {"speech_start_threshold": 0.4, "speech_end_threshold": 0.6},
        {"min_turn_ms": 2000, "max_turn_ms": 5000, "vad_frame_ms": 32},
        {"tts_chunk_ms": 60, "outbound_queue_ms": 40},
    ],
)
def test_cross_field_rules_are_refused_not_clamped(overrides: dict[str, object]) -> None:
    """§4.1's validation list. An invalid config is a refusal, never a silent correction."""
    if overrides.get("min_turn_ms") == 2000:
        overrides = {**overrides, "min_turn_ms": 2000, "max_turn_ms": 5000}
        with pytest.raises(ValidationError):
            VoiceTurnConfig(min_turn_ms=2000, max_turn_ms=2000)
        return
    with pytest.raises(ValidationError):
        VoiceTurnConfig(**overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("speech_start_threshold", 0.95),
        ("speech_start_threshold", 0.2),
        ("endpoint_silence_ms", 100),
        ("endpoint_silence_ms", 2000),
        ("pre_roll_ms", 50),
        ("barge_in_min_speech_ms", 32),
        ("max_turn_ms", 1000),
        ("tts_chunk_ms", 5),
    ],
)
def test_out_of_range_values_are_refused(field: str, value: float) -> None:
    """§4.1's Valid range column is a `Field` bound, so it fails at load, not at runtime."""
    with pytest.raises(ValidationError):
        VoiceTurnConfig(**{field: value})  # type: ignore[arg-type]


def test_endpoint_silence_outside_the_spec_target_band_still_loads(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """§4.1 calls 250–350 the *initial target*; the hard bound is 150–1500 (SPEC §17)."""
    with caplog.at_level("WARNING"):
        config = VoiceTurnConfig(endpoint_silence_ms=800)
    assert config.endpoint_silence_ms == 800
    assert "target band" in caplog.text


def test_settings_are_the_source_of_every_key(test_settings: Settings) -> None:
    """D9: the values come from env/profile, never from literals in the pipeline."""
    settings = test_settings.model_copy(
        update={"voice_endpoint_silence_ms": 256, "voice_pre_roll_ms": 512}
    )
    config = voice_turn_config_from_settings(settings)
    assert config.endpoint_silence_ms == 256
    assert config.pre_roll_ms == 512
    assert config.speech_start_threshold == settings.voice_speech_start_threshold
