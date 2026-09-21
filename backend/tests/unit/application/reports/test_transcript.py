"""The transcript and audio-reference projections (SPEC §29 items 5-7, E16 R5).

Three properties: the speaker rename the contract needs, the ordering that makes click-to-seek
work, and the purged-but-kept rule D9's retention policy relies on.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.application.ports.audio_segment_repository import StoredAudioSegment
from app.application.ports.transcript_segment_repository import StoredTranscriptSegment
from app.application.reports.transcript import (
    VIEW_SPEAKER_BY_STORED,
    audio_segment_refs,
    transcript_entries,
    view_speaker,
)
from app.domain.common.ids import SessionId

from tests.unit.domain.session._builders import det_uuid

SESSION = SessionId(det_uuid("session"))
CREATED = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)


def _transcript(
    name: str, *, speaker: str, start_ms: int, audio_segment_id: object = None
) -> StoredTranscriptSegment:
    return StoredTranscriptSegment(
        id=det_uuid(name),
        session_id=SESSION,
        audio_segment_id=audio_segment_id,
        speaker=speaker,
        start_ms=start_ms,
        end_ms=start_ms + 1000,
        text=f"текст {name}",
    )


def _audio(
    name: str,
    *,
    speaker: str,
    start_ms: int,
    purged_at: datetime | None = None,
    path: str | None = "recordings/s/a.wav",
) -> StoredAudioSegment:
    return StoredAudioSegment(
        id=det_uuid(name),
        session_id=SESSION,
        speaker=speaker,
        file_path=path,
        start_ms=start_ms,
        end_ms=start_ms + 1000,
        byte_offset=0,
        byte_length=32000,
        purged_at=purged_at,
        created_at=CREATED,
    )


# -- R5: the speaker rename -------------------------------------------------------------------


def test_the_stored_speaker_enum_is_mapped_exhaustively() -> None:
    """The DB CHECK admits `TRAINEE | CALLER`; the contract's enum is `OPERATOR | CALLER`."""
    assert VIEW_SPEAKER_BY_STORED == {"TRAINEE": "OPERATOR", "CALLER": "CALLER"}


def test_trainee_becomes_operator_on_the_wire() -> None:
    assert view_speaker("TRAINEE") == "OPERATOR"
    assert view_speaker("CALLER") == "CALLER"


def test_an_unknown_stored_speaker_is_a_loud_failure() -> None:
    """Not silently passed through: a value the CHECK cannot produce means the row is corrupt."""
    with pytest.raises(ValueError, match="unknown stored speaker"):
        view_speaker("DDS")


# -- ordering and click-to-seek ---------------------------------------------------------------


def test_the_transcript_is_ordered_for_playback() -> None:
    entries = transcript_entries(
        [
            _transcript("c", speaker="CALLER", start_ms=2000),
            _transcript("a", speaker="TRAINEE", start_ms=0),
            _transcript("b", speaker="CALLER", start_ms=1000),
        ]
    )
    assert [entry.start_ms for entry in entries] == [0, 1000, 2000]
    assert [entry.speaker for entry in entries] == ["OPERATOR", "CALLER", "CALLER"]


def test_click_to_seek_needs_the_segment_id_and_the_start_offset() -> None:
    """SPEC §29 item 7 is exactly this pair, under the contract's own names."""
    segment_id = det_uuid("audio-a")
    (entry,) = transcript_entries(
        [_transcript("a", speaker="TRAINEE", start_ms=4200, audio_segment_id=segment_id)]
    )
    assert entry.audio_segment_id == segment_id
    assert entry.start_ms == 4200
    assert entry.end_ms == 5200


# -- audio references -------------------------------------------------------------------------


def test_audio_refs_are_ordered_and_renamed() -> None:
    refs = audio_segment_refs(
        [
            _audio("b", speaker="CALLER", start_ms=1000),
            _audio("a", speaker="TRAINEE", start_ms=0),
        ]
    )
    assert [ref.start_ms for ref in refs] == [0, 1000]
    assert [ref.speaker for ref in refs] == ["OPERATOR", "CALLER"]
    assert all(ref.purged is False for ref in refs)


def test_a_purged_segment_is_kept_and_flagged() -> None:
    """D9: the purge nulls `file_path` and keeps the row as an audit record; the report renders
    the transcript without playback rather than pretending the recording never existed."""
    refs = audio_segment_refs(
        [_audio("a", speaker="TRAINEE", start_ms=0, purged_at=CREATED, path=None)]
    )
    assert len(refs) == 1
    assert refs[0].purged is True


def test_a_nulled_path_alone_counts_as_purged() -> None:
    refs = audio_segment_refs([_audio("a", speaker="CALLER", start_ms=0, path=None)])
    assert refs[0].purged is True
