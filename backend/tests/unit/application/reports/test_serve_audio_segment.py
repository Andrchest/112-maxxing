"""`getAudioSegment`'s pure halves: the WAV header, the `Range` parser and the path guard (R7).

The HTTP-level behaviour (200 / 206 / 410 / 416 through the real endpoint) lives in
`backend/tests/api/reports/`; this file pins the parts that have no database in them, including
the two that are security-relevant: an unsatisfiable range must be refused rather than clamped,
and a stored path that escapes the recordings directory must not be read (SPEC §41).
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.application.ports.audio_segment_repository import StoredAudioSegment
from app.application.reports.serve_audio_segment import (
    WAV_HEADER_BYTES,
    AudioSegmentNotFoundError,
    RangeNotSatisfiableError,
    ServeAudioSegment,
    parse_range,
    wav_header,
)
from app.domain.common.ids import SessionId

from tests.unit.domain.session._builders import det_uuid

SESSION = SessionId(det_uuid("session"))
CREATED = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)


# -- the header ---------------------------------------------------------------------------------


def test_the_header_is_the_canonical_44_byte_riff() -> None:
    header = wav_header(sample_rate=16000, num_channels=1, data_bytes=32000)
    assert len(header) == WAV_HEADER_BYTES == 44
    assert header[:4] == b"RIFF"
    assert header[8:12] == b"WAVE"
    assert header[12:16] == b"fmt "
    assert header[36:40] == b"data"
    assert struct.unpack("<I", header[40:44])[0] == 32000
    assert struct.unpack("<I", header[4:8])[0] == 36 + 32000


def test_the_header_describes_the_segment_not_the_file() -> None:
    """A segment is a *slice*: reusing the call's own header would report the wrong duration."""
    assert (
        struct.unpack("<I", wav_header(sample_rate=8000, num_channels=2, data_bytes=10)[40:44])[0]
        == 10
    )
    header = wav_header(sample_rate=8000, num_channels=2, data_bytes=10)
    assert struct.unpack("<H", header[22:24])[0] == 2  # channels
    assert struct.unpack("<I", header[24:28])[0] == 8000  # sample rate


# -- the Range parser ---------------------------------------------------------------------------


def test_no_range_header_means_the_whole_representation() -> None:
    assert parse_range(None, 1000) is None


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("bytes=0-99", (0, 99)),
        ("bytes=100-", (100, 999)),
        ("bytes=-100", (900, 999)),
        ("bytes=0-99999", (0, 999)),  # clamped to the end, which RFC 9110 requires
        ("  bytes=10-20  ", (10, 20)),
        ("BYTES=10-20", (10, 20)),
    ],
)
def test_a_single_byte_range_is_parsed(header: str, expected: tuple[int, int]) -> None:
    assert parse_range(header, 1000) == expected


@pytest.mark.parametrize("header", ["bytes=1000-1100", "bytes=1000-", "bytes=50-10", "bytes=-0"])
def test_an_unsatisfiable_range_is_refused(header: str) -> None:
    """416, not a clamp: a client asking past the end must learn that it did."""
    with pytest.raises(RangeNotSatisfiableError) as excinfo:
        parse_range(header, 1000)
    assert excinfo.value.code == "RANGE_NOT_SATISFIABLE"
    assert excinfo.value.content_range == "bytes */1000"


@pytest.mark.parametrize("header", ["items=0-10", "bytes=0-10,20-30", "bytes", "bytes=abc"])
def test_a_range_this_parser_does_not_understand_is_treated_as_absent(header: str) -> None:
    """RFC 9110 §14.2 permits ignoring a `Range` a server cannot satisfy in form; the client then
    gets the whole representation rather than an error."""
    assert parse_range(header, 1000) is None


# -- the path guard (SPEC §41) ------------------------------------------------------------------


def _segment(file_path: str | None, *, byte_length: int = 8) -> StoredAudioSegment:
    return StoredAudioSegment(
        id=det_uuid("audio"),
        session_id=SESSION,
        speaker="TRAINEE",
        file_path=file_path,
        start_ms=0,
        end_ms=1000,
        byte_offset=0,
        byte_length=byte_length,
        created_at=CREATED,
    )


def _use_case(tmp_path: Path) -> ServeAudioSegment:
    return ServeAudioSegment(lambda: None, recordings_dir=tmp_path / "recordings")  # type: ignore[arg-type,return-value]


def test_a_path_inside_the_recordings_directory_is_served(tmp_path: Path) -> None:
    target = tmp_path / "recordings" / "s" / "a.wav"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\x00" * WAV_HEADER_BYTES + b"\x01\x02\x03\x04\x05\x06\x07\x08")

    response = _use_case(tmp_path)._serve(_segment("recordings/s/a.wav"), None)

    assert response.status_code == 200
    assert response.total_bytes == WAV_HEADER_BYTES + 8
    assert response.content[WAV_HEADER_BYTES:] == b"\x01\x02\x03\x04\x05\x06\x07\x08"
    assert response.content_range is None


def test_a_range_slices_the_representation(tmp_path: Path) -> None:
    target = tmp_path / "recordings" / "s" / "a.wav"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\x00" * WAV_HEADER_BYTES + bytes(range(8)))

    response = _use_case(tmp_path)._serve(_segment("recordings/s/a.wav"), "bytes=44-47")

    assert response.status_code == 206
    assert response.content == bytes(range(4))
    assert response.content_range == f"bytes 44-47/{WAV_HEADER_BYTES + 8}"


def test_a_range_spanning_the_header_and_the_pcm(tmp_path: Path) -> None:
    target = tmp_path / "recordings" / "s" / "a.wav"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\x00" * WAV_HEADER_BYTES + bytes(range(8)))

    response = _use_case(tmp_path)._serve(_segment("recordings/s/a.wav"), "bytes=42-45")

    assert response.status_code == 206
    assert len(response.content) == 4
    assert response.content[2:] == bytes(range(2))


@pytest.mark.parametrize(
    "escaping",
    ["../secrets.wav", "../../etc/passwd", "recordings/../../outside.wav"],
)
def test_a_path_that_escapes_the_recordings_directory_is_refused(
    tmp_path: Path, escaping: str
) -> None:
    """Nothing in the request influences the path — but a tampered row must not be read either."""
    (tmp_path / "recordings").mkdir()
    (tmp_path / "secrets.wav").write_bytes(b"\x00" * 64)
    (tmp_path / "outside.wav").write_bytes(b"\x00" * 64)

    with pytest.raises(AudioSegmentNotFoundError):
        _use_case(tmp_path)._serve(_segment(escaping), None)


def test_a_missing_file_is_a_404_not_a_crash(tmp_path: Path) -> None:
    (tmp_path / "recordings").mkdir()
    with pytest.raises(AudioSegmentNotFoundError):
        _use_case(tmp_path)._serve(_segment("recordings/s/gone.wav"), None)
