"""`DialogueTurnRepository` port — the `dialogue_turns` table (HLD `20-db-schema.md` §20.6,
`10-domain-model.md` §10.13, `50-voice-pipeline.md` §9).

One row per trainee turn, keyed `(session_id, turn_index)`: the *materialized turn record*, which
§10.13 is careful to call "not a domain type" and which **scoring never reads** (D5, D11: scoring
reads `(scenario_versions.content, ordered session_events)` and nothing else). It exists so the
report can render a turn — who said what, how long the caller took to answer — without folding
the whole event log per turn.

The row is filled by three epics in three passes, which is why the writer is an **upsert of the
columns it owns** rather than a `save` of the whole row:

* **E12 (here)** — `user_speech_started_offset_ms`, `user_speech_ended_offset_ms`,
  `operator_transcript_segment_id`, `correlation_id`;
* **E13** — `interpretation`, `gate_output`, `fallback_used`;
* **E14** — `caller_transcript_segment_id`, `planned_text`, `delivered_text`, `interrupted`, and
  `speech_end_to_first_audio_ms` (SPEC §27's critical product metric, written through
  `MetricsRecorder.record_turn_latency` because that is the port every stage already has).

An `upsert` must therefore never write a column it was not given: a later epic's pass must not be
able to blank an earlier one's, and vice versa.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import RoleStageId, SessionId

__all__ = ["DialogueTurnRepository", "DialogueTurnUpsert", "StoredDialogueTurn"]


class DialogueTurnUpsert(BaseModel):
    """The columns E12 owns, plus the key and the NOT NULL columns the insert needs (§20.6)."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    """Used only when the row is inserted; an existing row keeps its own id."""

    session_id: SessionId
    role_stage_id: RoleStageId
    """`NOT NULL` in §20.6: the stage whose trainee was speaking."""

    turn_index: int
    user_speech_started_offset_ms: int
    user_speech_ended_offset_ms: int | None = None
    operator_transcript_segment_id: UUID | None = None
    correlation_id: UUID | None = None
    """The turn uuid, so an event and its turn row can be joined across processes (§3.2)."""


class StoredDialogueTurn(BaseModel):
    """One `dialogue_turns` row as it is read back (§20.6)."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    session_id: SessionId
    role_stage_id: RoleStageId
    turn_index: int
    user_speech_started_offset_ms: int
    user_speech_ended_offset_ms: int | None = None
    operator_transcript_segment_id: UUID | None = None
    caller_transcript_segment_id: UUID | None = None
    planned_text: str | None = None
    delivered_text: str | None = None
    interrupted: bool = False
    fallback_used: bool = False
    speech_end_to_first_audio_ms: int | None = None
    correlation_id: UUID | None = None


@runtime_checkable
class DialogueTurnRepository(Protocol):
    """`dialogue_turns`, bound to the caller's Unit of Work transaction."""

    async def upsert(self, turn: DialogueTurnUpsert) -> UUID:
        """Insert or update the row for `(session_id, turn_index)`; returns the row's id.

        Only the columns `DialogueTurnUpsert` carries are written. Columns E13 and E14 own keep
        whatever they already hold, and their defaults apply on insert.
        """
        ...

    async def set_speech_end_to_first_audio_ms(
        self, session_id: SessionId, turn_index: int, value: int
    ) -> None:
        """SPEC §27's critical product metric, on the turn row (§2.6).

        A turn row that does not exist yet is not created by this call: the metric describes a
        turn the pipeline has already recorded, and inventing a row for it would need a
        `role_stage_id` this port has no way to know.
        """
        ...

    async def get(self, session_id: SessionId, turn_index: int) -> StoredDialogueTurn | None:
        """One row by its natural key, or `None`."""
        ...

    async def list_for_session(self, session_id: SessionId) -> list[StoredDialogueTurn]:
        """Every turn of one session in `turn_index` order."""
        ...
