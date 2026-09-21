"""`SessionRecorder` and `WavFileSink` — the recording and its index (§9.1, SPEC §41)."""

from __future__ import annotations

import uuid
import wave
from pathlib import Path

from app.application.testing.fakes import FakeClock, sine_burst_frames
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.recorder import RecordingPaths, SessionRecorder
from app.domain.common.ids import SessionId
from app.infrastructure.recording.wav_writer import InMemoryAudioSink, WavFileSink

SESSION_ID = SessionId(uuid.UUID("22222222-2222-4222-8222-222222222222"))
CALL_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


def make_recorder(config: VoiceTurnConfig, clock: FakeClock) -> SessionRecorder:
    paths = RecordingPaths.for_call(SESSION_ID, CALL_ID)
    return SessionRecorder(
        session_id=SESSION_ID,
        call_id=CALL_ID,
        config=config,
        clock=clock,
        trainee_sink=InMemoryAudioSink(paths.trainee),
        caller_sink=InMemoryAudioSink(paths.caller),
    )


def test_paths_are_the_documented_layout_relative_to_data_dir() -> None:
    """§9.1: `DATA_DIR/recordings/{session_id}/{trainee,caller}-{call_id}.wav`."""
    paths = RecordingPaths.for_call(SESSION_ID, CALL_ID)
    assert paths.trainee == f"recordings/{SESSION_ID}/trainee-{CALL_ID}.wav"
    assert paths.caller == f"recordings/{SESSION_ID}/caller-{CALL_ID}.wav"
    assert not paths.trainee.startswith("/"), "the stored path must be relative (SPEC §41)"


def test_wav_header_is_valid_and_bytes_written_counts_payload_only(tmp_path: Path) -> None:
    """A recording must be readable by anything that reads WAV; the offsets exclude the header."""
    config = VoiceTurnConfig()
    sink = WavFileSink(
        data_dir=tmp_path, relative_path="recordings/s/trainee.wav", sample_rate=config.sample_rate
    )
    frames = sine_burst_frames(
        duration_ms=320, frame_samples=config.frame_samples, sample_rate=config.sample_rate
    )
    for frame in frames:
        sink.write(frame.pcm)
    payload = sink.bytes_written
    sink.close()
    sink.close()  # idempotent

    with wave.open(str(tmp_path / "recordings/s/trainee.wav"), "rb") as reader:
        assert reader.getnchannels() == 1
        assert reader.getsampwidth() == 2
        assert reader.getframerate() == config.sample_rate
        assert reader.getnframes() == payload // 2
    assert payload == sum(len(frame.pcm) for frame in frames)
    assert (tmp_path / "recordings/s/trainee.wav").stat().st_size == payload + 44


def test_segment_offsets_are_session_relative_and_locate_the_bytes() -> None:
    """§9.1: `start_ms`/`end_ms` are session-relative; `byte_offset`/`byte_length` are the file."""
    config = VoiceTurnConfig()
    clock = FakeClock()
    recorder = make_recorder(config, clock)
    frames = sine_burst_frames(
        duration_ms=1024,
        frame_samples=config.frame_samples,
        sample_rate=config.sample_rate,
        start_offset_ms=5_000,
    )
    for frame in frames:
        recorder.tee("TRAINEE", frame)

    segment = recorder.segment_for("TRAINEE", start_ms=5_320, end_ms=5_640)

    assert segment.session_id == SESSION_ID
    assert segment.speaker == "TRAINEE"
    assert segment.sample_rate == config.sample_rate
    assert segment.num_channels == 1
    assert segment.format == "wav"
    assert segment.purged_at is None
    assert segment.created_at == clock.now()
    # The anchor is the first frame the recorder saw (offset 5000), so 5320 ms is 320 ms in.
    assert segment.byte_offset == 320 * config.sample_rate * 2 // 1000
    assert segment.byte_length == 320 * config.sample_rate * 2 // 1000
    assert segment.byte_offset + segment.byte_length <= recorder.bytes_written("TRAINEE")


def test_a_segment_never_points_past_the_end_of_the_file() -> None:
    """A trimmed trailing silence must not produce a Range request that runs off the file."""
    config = VoiceTurnConfig()
    recorder = make_recorder(config, FakeClock())
    for frame in sine_burst_frames(
        duration_ms=320, frame_samples=config.frame_samples, sample_rate=config.sample_rate
    ):
        recorder.tee("TRAINEE", frame)

    segment = recorder.segment_for("TRAINEE", start_ms=0, end_ms=60_000)
    assert segment.byte_offset + segment.byte_length == recorder.bytes_written("TRAINEE")


def test_close_finalises_both_sinks_and_refuses_further_writes() -> None:
    """Both WAV containers are closed once; writing after the call is a bug, not a silent append."""
    config = VoiceTurnConfig()
    recorder = make_recorder(config, FakeClock())
    frame = sine_burst_frames(
        duration_ms=32, frame_samples=config.frame_samples, sample_rate=config.sample_rate
    )[0]
    recorder.tee("TRAINEE", frame)
    recorder.close()
    recorder.close()

    try:
        recorder.tee("CALLER", frame)
    except RuntimeError as exc:
        assert "closed" in str(exc)
    else:  # pragma: no cover - the guard above is the expected path
        raise AssertionError("a closed recorder must refuse writes")
