"""Local recording storage for the voice path (§9.1, §9.2, SPEC §41).

Recordings never leave the machine: `WavFileSink` writes under `Settings.data_dir` and the
`audio_segments` row stores a path *relative* to that directory, so moving the data directory (or
mounting it into the compose deployment) does not invalidate a single row.

The write path lives here (`WavFileSink`/`InMemoryAudioSink`, below); the delete path (`python -m
app.cli purge_recordings` and the `recording_purge_audit` writes of §9.2) is one layer up, in
`app.application.recording.purge_recordings.PurgeRecordings` (E18, resolved) — it needs no
infrastructure module of its own here because it deletes files through the same relative-path,
`Settings.data_dir`-rooted convention this module's writer already establishes, with the same
containment check `app.application.reports.serve_audio_segment.ServeAudioSegment` uses to read one
back (SPEC §41: nothing outside `DATA_DIR/recordings` is ever touched, in either direction).

`LameMp3Encoder` (I5 E40, Q-E16-3 variant b) is a read-path adapter, not a recording-storage one —
it lives here anyway because it is the one other module that touches LAME/`lameenc`, the same
reason the WAV writer lives here rather than beside `SessionRecorder`.
"""

from __future__ import annotations

from app.infrastructure.recording.mp3_encoder import LameMp3Encoder
from app.infrastructure.recording.wav_writer import InMemoryAudioSink, WavFileSink

__all__ = ["InMemoryAudioSink", "LameMp3Encoder", "WavFileSink"]
