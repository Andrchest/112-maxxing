"""Local recording storage for the voice path (§9.1, §9.2, SPEC §41).

Recordings never leave the machine: `WavFileSink` writes under `Settings.data_dir` and the
`audio_segments` row stores a path *relative* to that directory, so moving the data directory (or
mounting it into the compose deployment) does not invalidate a single row.

TODO(E15): `python -m app.cli purge_recordings` and the `recording_purge_audit` writes of §9.2 —
the retention window belongs to the epic that owns the report and its "audio deleted (retention)"
rendering, not to the epic that writes the files.
"""

from __future__ import annotations

from app.infrastructure.recording.wav_writer import InMemoryAudioSink, WavFileSink

__all__ = ["InMemoryAudioSink", "WavFileSink"]
