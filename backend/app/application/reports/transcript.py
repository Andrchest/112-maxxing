"""`SessionReport.transcript` / `.audio_segments` — SPEC §29 items 5, 6 and 7.

Item 7 ("click transcript → seek to audio") is not a UI trick: it is the pair
`(audio_segment_id, start_ms)` on every transcript row, named exactly as `openapi.yaml` names it,
so the player seeks to a session-relative millisecond and the report never has to guess where a
line lives inside a file (D9: `audio_segments.start_ms` is session-relative, `byte_offset` /
`byte_length` locate the bytes).

**Speaker label (E16 R5).** The database stores `TRAINEE | CALLER`
(`20-db-schema.md`'s `CHECK (speaker IN ('TRAINEE','CALLER'))`) and the contract's
`TranscriptSegmentView.speaker` / `AudioSegmentRef.speaker` are `OPERATOR | CALLER`. The
translation is explicit and one-way, in `VIEW_SPEAKER_BY_STORED` below, rather than an implicit
copy that a Pydantic enum would reject at the boundary. It is a rename, not a widening: voice
exists only in the Operator 112 stage (SPEC §15-§25; the DDS role's visibility policy has no
`TRANSCRIPT` source at all), so a stored `TRAINEE` row always *is* the operator's.

**Calls (I3 E6c, HLD 80 §80.6.1).** Since the ДДС phone, a session may hold more than one call:
the 112 call and ДДС calls whose turns reuse the same rows. A row is tied to its call through its
`turn_index` (the per-turn events carry both — `turn_calls`), and each entry carries the call id and
the call's party label, so the report groups the transcript by call. `OPERATOR` then reads as
"the trainee on that call" (the ДДС on a ДДС call) and `CALLER` as the AI party of it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.application.ports.audio_segment_repository import StoredAudioSegment
from app.application.ports.transcript_segment_repository import StoredTranscriptSegment
from app.domain.events.session_event import SessionEvent

__all__ = [
    "VIEW_SPEAKER_BY_STORED",
    "AudioSegmentRef",
    "TranscriptEntry",
    "ViewSpeaker",
    "audio_segment_refs",
    "transcript_entries",
    "turn_calls",
    "view_speaker",
]

#: `openapi.yaml`'s speaker enum for both views.
ViewSpeaker = Literal["OPERATOR", "CALLER"]

#: The stored label → the contract's label (R5). Exhaustive over the DB CHECK's two members.
VIEW_SPEAKER_BY_STORED: Mapping[str, ViewSpeaker] = {
    "TRAINEE": "OPERATOR",
    "CALLER": "CALLER",
}


def view_speaker(stored: str) -> ViewSpeaker:
    """`TRAINEE -> OPERATOR`, `CALLER -> CALLER` (R5); anything else is a storage bug."""
    try:
        return VIEW_SPEAKER_BY_STORED[stored]
    except KeyError:  # pragma: no cover - the DB CHECK admits only the two members
        raise ValueError(f"unknown stored speaker {stored!r}") from None


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    """`openapi.yaml`'s `TranscriptSegmentView` as application data (SPEC §19's field list)."""

    id: UUID
    speaker: ViewSpeaker
    start_ms: int
    end_ms: int
    text: str
    is_final: bool
    confidence: float | None
    asr_provider: str | None
    asr_model: str | None
    audio_segment_id: UUID | None
    turn_index: int | None
    call_id: UUID | None = None
    call_party_ru: str | None = None


def turn_calls(events: Sequence[SessionEvent]) -> Mapping[int, str]:
    """`turn_index → call_id` (lowercase) from the per-turn events that carry both (I3 E6c)."""
    calls: dict[int, str] = {}
    for event in events:
        turn_index = event.payload.get("turn_index")
        call_id = event.payload.get("call_id")
        if isinstance(turn_index, int) and call_id is not None:
            calls.setdefault(turn_index, str(call_id).lower())
    return calls


@dataclass(frozen=True, slots=True)
class AudioSegmentRef:
    """`openapi.yaml`'s `AudioSegmentRef` — what to fetch with `getAudioSegment`, and where."""

    audio_segment_id: UUID
    speaker: ViewSpeaker
    start_ms: int
    end_ms: int
    sample_rate: int
    purged: bool


def transcript_entries(
    segments: Sequence[StoredTranscriptSegment],
    *,
    calls: Mapping[int, str] | None = None,
    parties: Mapping[str, str] | None = None,
) -> tuple[TranscriptEntry, ...]:
    """The transcript in playback order — `start_ms`, then `id` for a deterministic tie-break.

    Ordering here rather than in SQL keeps the projection pure and testable, and the list is one
    session's dialogue: a few hundred rows at most. `calls` (`turn_calls`) and `parties`
    (`timeline.call_parties`) label each row with its call (I3 E6c).
    """
    ordered = sorted(segments, key=lambda segment: (segment.start_ms, str(segment.id)))
    turn_to_call = calls or {}
    party_of = parties or {}

    def _call_of(segment: StoredTranscriptSegment) -> str | None:
        return None if segment.turn_index is None else turn_to_call.get(segment.turn_index)

    return tuple(
        TranscriptEntry(
            id=segment.id,
            speaker=view_speaker(str(segment.speaker)),
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            text=segment.text,
            is_final=segment.is_final,
            confidence=segment.confidence,
            asr_provider=segment.asr_provider,
            asr_model=segment.asr_model,
            audio_segment_id=segment.audio_segment_id,
            turn_index=segment.turn_index,
            call_id=None if (call := _call_of(segment)) is None else UUID(call),
            call_party_ru=None if call is None else party_of.get(call),
        )
        for segment in ordered
    )


def audio_segment_refs(segments: Sequence[StoredAudioSegment]) -> tuple[AudioSegmentRef, ...]:
    """The playable segments, in session order.

    A purged row is **kept** and flagged rather than dropped: D9's retention purge nulls
    `file_path` and leaves the row as an audit record, and the report UI is expected to render the
    transcript without playback rather than pretend the audio never existed.
    """
    ordered = sorted(segments, key=lambda segment: (segment.start_ms, str(segment.id)))
    return tuple(
        AudioSegmentRef(
            audio_segment_id=segment.id,
            speaker=view_speaker(str(segment.speaker)),
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            sample_rate=segment.sample_rate,
            purged=segment.purged_at is not None or segment.file_path is None,
        )
        for segment in ordered
    )
