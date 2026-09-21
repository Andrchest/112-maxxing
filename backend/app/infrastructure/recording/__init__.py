"""Local recording storage for the voice path (§9.1, §9.2, SPEC §41).

Recordings never leave the machine: `WavFileSink` writes under `Settings.data_dir` and the
`audio_segments` row stores a path *relative* to that directory, so moving the data directory (or
mounting it into the compose deployment) does not invalidate a single row.

TODO(E18): `python -m app.cli purge_recordings` and the `recording_purge_audit` writes of §9.2 —
`docs/hld/90-tbd-epics.md`'s E18 row ("Profiles, warm-up, preflight, resilience, full compose")
is the one that lists "retention purge" among its deliverables (SPEC §41 in its own SPEC-§
column), so this is that epic's slice, not the one that writes the files and not the E15
deterministic-scoring slice (re-labelled from a stale, differently-numbered marker by the E15-B
task; see that task's report).
"""

from __future__ import annotations

from app.infrastructure.recording.wav_writer import InMemoryAudioSink, WavFileSink

__all__ = ["InMemoryAudioSink", "WavFileSink"]
