"""`PreRollBuffer` — the ring that keeps the first syllable (§4.2, SPEC §17)."""

from __future__ import annotations

import pytest
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.pre_roll import PreRollBuffer

from tests.unit.application.voice.conftest import quiet


def test_capacity_holds_at_least_the_configured_pre_roll(config: VoiceTurnConfig) -> None:
    """§4.2: `ceil(pre_roll_ms / vad_frame_ms)` — never less than the configured pre-roll."""
    buffer = PreRollBuffer(config.pre_roll_frames)
    frames = quiet(config, config.pre_roll_ms * 3, 0)
    for frame in frames:
        buffer.push(frame)

    assert len(buffer) == config.pre_roll_frames
    assert buffer.duration_ms() >= config.pre_roll_ms
    assert len(buffer.pcm()) == config.pre_roll_frames * config.frame_samples * 2


def test_oldest_frames_are_evicted_first(config: VoiceTurnConfig) -> None:
    """A ring, not a growing list: a long silence must not accumulate megabytes."""
    buffer = PreRollBuffer(config.pre_roll_frames)
    frames = quiet(config, config.pre_roll_ms * 4, 0)
    for frame in frames:
        buffer.push(frame)

    kept = list(buffer.frames())
    assert kept == frames[-config.pre_roll_frames :]


def test_clear_empties_the_buffer(config: VoiceTurnConfig) -> None:
    """`reset()` at the start of a call must not leave the previous call's audio behind."""
    buffer = PreRollBuffer(config.pre_roll_frames)
    for frame in quiet(config, 500, 0):
        buffer.push(frame)
    buffer.clear()
    assert len(buffer) == 0
    assert buffer.pcm() == b""


def test_a_zero_capacity_buffer_keeps_nothing(config: VoiceTurnConfig) -> None:
    """`pre_roll_ms` can never be 0 (§4.1 bounds it at 100) but the ring must still be total."""
    buffer = PreRollBuffer(0)
    for frame in quiet(config, 200, 0):
        buffer.push(frame)
    assert len(buffer) == 0


def test_a_negative_capacity_is_refused() -> None:
    """A programming error, refused loudly rather than turned into an unbounded deque."""
    with pytest.raises(ValueError, match="negative"):
        PreRollBuffer(-1)
