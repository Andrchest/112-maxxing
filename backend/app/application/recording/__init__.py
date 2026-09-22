"""Recording retention (epic E18; `docs/hld/50-voice-pipeline.md` §9.2, `20-db-schema.md` §20.6,
D9, SPEC §41).

One module, one use case: `purge_recordings.PurgeRecordings`, shared by `python -m app.cli
purge_recordings` and `POST /api/v1/admin/recordings/purge` (R8). The write-path recording
infrastructure (`WavFileSink`, `InMemoryAudioSink`) lives under `app.infrastructure.recording`;
this package is the read/delete half of the same story, one layer up.
"""

from __future__ import annotations

from app.application.recording.purge_recordings import (
    PurgeRecordings,
    PurgeRecordingsRequest,
    PurgeRecordingsResult,
)

__all__ = ["PurgeRecordings", "PurgeRecordingsRequest", "PurgeRecordingsResult"]
