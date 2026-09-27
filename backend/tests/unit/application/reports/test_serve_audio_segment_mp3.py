"""`getAudioSegmentMp3`'s encode-and-cache halves (I5 E40, Q-E16-3 variant b), with the real LAME
encoder (`LameMp3Encoder`) rather than a fake — the check this task asks for is that the *actual*
bytes LAME produces decode back to a valid MP3 frame and the right duration, not that some stub
returned the right shape.

The authorization half (identical to `getAudioSegment`'s, E16 R3/R7) is proven over real HTTP in
`tests/api/reports/test_audio_segment_mp3.py`; here `ServeAudioSegment.resolve_audio` is faked so
these tests need no database, matching `test_serve_audio_segment.py`'s own no-DB style for the
parts of that module with no database in them.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.application.ports.audio_segment_repository import StoredAudioSegment
from app.application.reports.serve_audio_segment import wav_header
from app.application.reports.serve_audio_segment_mp3 import ServeAudioSegmentMp3
from app.domain.common.ids import SessionId
from app.infrastructure.recording.mp3_encoder import LameMp3Encoder

from tests.unit.domain.session._builders import det_uuid

SESSION = SessionId(det_uuid("session"))
SEGMENT_ID = det_uuid("audio")
CREATED = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)
SAMPLE_RATE = 16000

#: Two seconds of 16-bit mono PCM — not silence (a repeating byte ramp), so LAME has something to
#: encode rather than emit its own all-zero shortcut.
_PCM = bytes(range(256)) * (SAMPLE_RATE * 2 * 2 // 256)


def _segment(*, byte_length: int) -> StoredAudioSegment:
    return StoredAudioSegment(
        id=SEGMENT_ID,
        session_id=SESSION,
        speaker="TRAINEE",
        file_path="recordings/s/trainee-1.wav",
        start_ms=0,
        end_ms=2000,
        sample_rate=SAMPLE_RATE,
        num_channels=1,
        byte_offset=0,
        byte_length=byte_length,
        created_at=CREATED,
    )


def _use_case(tmp_path: Path, *, pcm: bytes = _PCM) -> tuple[ServeAudioSegmentMp3, Path]:
    wav_path = tmp_path / "recordings" / "s" / "trainee-1.wav"
    wav_path.parent.mkdir(parents=True)
    wav_path.write_bytes(b"\x00" * 44 + pcm)  # the header's bytes are never read back here

    use_case = ServeAudioSegmentMp3(
        lambda: None,  # type: ignore[arg-type,return-value]
        recordings_dir=tmp_path / "recordings",
        encoder=LameMp3Encoder(),
    )
    segment = _segment(byte_length=len(pcm))

    async def _fake_resolve_audio(
        session_id: SessionId, audio_segment_id: Any, user: Any
    ) -> tuple[StoredAudioSegment, bytes, Path]:
        return segment, pcm, wav_path

    use_case._wav.resolve_audio = _fake_resolve_audio  # type: ignore[method-assign]
    return use_case, wav_path


def _mp3_duration_seconds(data: bytes) -> float:
    """Sums `samples-per-frame / sample-rate` over every Layer III frame found by its sync word —
    just enough of the MPEG frame format to check LAME's own output, not a general decoder."""
    _MPEG1_BITRATES = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0)
    _MPEG1_RATES = (44100, 48000, 32000, 0)
    _MPEG2_BITRATES = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0)
    _MPEG2_RATES = (22050, 24000, 16000, 0)
    _MPEG25_RATES = (11025, 12000, 8000, 0)

    i = 0
    total_samples = 0
    sample_rate: int | None = None
    n = len(data)
    while i + 4 <= n:
        b0, b1, b2 = data[i], data[i + 1], data[i + 2]
        if b0 != 0xFF or (b1 & 0xE0) != 0xE0:
            i += 1
            continue
        version = (b1 >> 3) & 0x03
        layer = (b1 >> 1) & 0x03
        if layer != 0x01:  # Layer III only — the only layer `lameenc` emits
            i += 1
            continue
        bitrate_index = (b2 >> 4) & 0x0F
        rate_index = (b2 >> 2) & 0x03
        padding = (b2 >> 1) & 0x01
        if bitrate_index in (0, 15) or rate_index == 3:
            i += 1
            continue
        if version == 0b11:  # MPEG1
            bitrates, rates, samples_per_frame, coeff = _MPEG1_BITRATES, _MPEG1_RATES, 1152, 144
        else:  # MPEG2 (0b10) or MPEG2.5 (0b00) — both Layer III at 576 samples/frame
            rates = _MPEG2_RATES if version == 0b10 else _MPEG25_RATES
            bitrates, samples_per_frame, coeff = _MPEG2_BITRATES, 576, 72
        bitrate_bps = bitrates[bitrate_index] * 1000
        rate = rates[rate_index]
        if bitrate_bps == 0 or rate == 0:
            i += 1
            continue
        sample_rate = rate
        frame_size = (coeff * bitrate_bps) // rate + padding
        if frame_size <= 0:
            i += 1
            continue
        total_samples += samples_per_frame
        i += frame_size
    assert sample_rate is not None, "no valid MPEG Layer III frame found"
    return total_samples / sample_rate


async def test_encodes_to_a_valid_mp3_within_5_percent_of_the_source_duration(
    tmp_path: Path,
) -> None:
    use_case, _ = _use_case(tmp_path)

    response = await use_case(SESSION, SEGMENT_ID, user=None)  # type: ignore[arg-type]

    assert response.media_type == "audio/mpeg"
    assert response.content[0] == 0xFF and (response.content[1] & 0xE0) == 0xE0

    source_seconds = len(_PCM) / (SAMPLE_RATE * 2)  # s16le mono
    encoded_seconds = _mp3_duration_seconds(response.content)
    assert abs(encoded_seconds - source_seconds) / source_seconds <= 0.05


async def test_the_cache_is_hit_on_a_second_call(tmp_path: Path) -> None:
    calls = 0
    use_case, wav_path = _use_case(tmp_path)
    real_encode = use_case._encoder.encode

    def _counting_encode(pcm: bytes, **kwargs: Any) -> bytes:
        nonlocal calls
        calls += 1
        return real_encode(pcm, **kwargs)

    use_case._encoder.encode = _counting_encode  # type: ignore[method-assign]

    first = await use_case(SESSION, SEGMENT_ID, user=None)  # type: ignore[arg-type]
    second = await use_case(SESSION, SEGMENT_ID, user=None)  # type: ignore[arg-type]

    assert calls == 1
    assert first.content == second.content
    cache_files = list(wav_path.parent.glob("*.mp3"))
    assert len(cache_files) == 1


async def test_the_cache_file_is_named_by_the_sha256_of_the_wav_representation(
    tmp_path: Path,
) -> None:
    use_case, wav_path = _use_case(tmp_path)

    await use_case(SESSION, SEGMENT_ID, user=None)  # type: ignore[arg-type]

    header = wav_header(sample_rate=SAMPLE_RATE, num_channels=1, data_bytes=len(_PCM))
    expected_digest = hashlib.sha256(header + _PCM).hexdigest()
    assert (wav_path.parent / f"{expected_digest}.mp3").is_file()
