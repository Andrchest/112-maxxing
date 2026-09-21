"""The materialized views every Operator 112 command returns (D8, `openapi.yaml`).

D8: "commands return the new materialized view". These are the *application* shapes of
`openapi.yaml`'s `OperatorStageView`, `OperatorCardView`, `CardRevisionView`, `CallStateView` and
`ServiceSelectionView`; `app.api.schemas.operator` maps each to its pydantic wire model, so the
wire shape and the application shape can move independently (D2).

They are pydantic models rather than dataclasses for one concrete reason: `SetCardField`'s
idempotency note (§40.6) stores "the first response body of that command", and a model that
round-trips through `model_dump_json()` / `model_validate_json()` makes that storage honest
instead of a hand-written serialiser that can drift from the view.

**Call state has no table.** `project_call_state` is a pure fold over the session's event log —
the audit source (SPEC §8, §31) — and nothing else. §40.6's `session:{id}:call_state` key is a
*cache* of that fold and never an authority: `CachedCallState` below carries exactly the five keys
§40.6 lists, `call_state_document` is what a call use case writes after its commit, and
`read_cached_call_state` answers from the key when it is there and **from the fold when it is
not**. Losing the key — a lapsed TTL, a `FLUSHALL`, an unreachable Redis — therefore costs one
PostgreSQL read and changes no answer, which is §40.6's stated invariant.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from app.application.ports.call_state_cache import CallStateCache
from app.domain.common.ids import SessionId
from app.domain.enums import Operator112StageState, ServiceType, SessionState, ValueType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.layers.operator_card import CARD_FIELDS, CardRevision, OperatorCard
from app.domain.roles.module import ActionDescriptor
from app.domain.roles.registry import ROLE_MODULES
from app.domain.session.session import RoleStage, SimulationSession

__all__ = [
    "ActionView",
    "ActorRefView",
    "CachedCallState",
    "CallPhase",
    "CallStateView",
    "CardFieldSpecView",
    "CardRevisionView",
    "OperatorCardView",
    "OperatorStageView",
    "ServiceSelectionView",
    "action_views",
    "call_state_document",
    "card_view",
    "operator_stage_view",
    "project_call_state",
    "read_cached_call_state",
    "revision_view",
    "write_call_state_cache",
]

logger = logging.getLogger(__name__)


class CallPhase(str, Enum):
    """`openapi.yaml`'s `CallStateView.phase`, exact."""

    NO_CALL = "NO_CALL"
    RINGING = "RINGING"
    CONNECTED = "CONNECTED"
    ENDED = "ENDED"


class ApplicationView(BaseModel):
    """Base for the views below: frozen, and no extra keys on the way back in."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ActorRefView(ApplicationView):
    """`openapi.yaml`'s `ActorRef` — who did it (SPEC §8)."""

    actor_type: str
    actor_id: UUID | None


class CardFieldSpecView(ApplicationView):
    """`openapi.yaml`'s `CardFieldSpec` — one `CARD_FIELDS` entry (§10.6)."""

    field_path: str
    value_type: ValueType
    enum_name: str | None
    label_ru: str
    scoring_relevant: bool
    required_for_handoff: bool


class OperatorCardView(ApplicationView):
    """`openapi.yaml`'s `OperatorCardView` (SPEC §9)."""

    card_id: UUID
    incident_id: UUID
    values: dict[str, str | int | float | bool | list[str] | None]
    revision_counter: int
    field_specs: tuple[CardFieldSpecView, ...]


class CardRevisionView(ApplicationView):
    """`openapi.yaml`'s `CardRevisionView` — one `incident_card_revisions` row (SPEC §9)."""

    revision_id: UUID
    card_id: UUID
    revision_no: int
    field_path: str
    previous_value: str | int | float | bool | list[str] | None
    new_value: str | int | float | bool | list[str] | None
    actor: ActorRefView
    at_offset_ms: int


class CallStateView(ApplicationView):
    """`openapi.yaml`'s `CallStateView` — the phone widget's state (D12)."""

    call_id: UUID | None
    room_name: str | None
    phase: CallPhase
    caller_display_ru: str | None
    started_at_offset_ms: int | None
    answered_at_offset_ms: int | None
    ended_at_offset_ms: int | None
    duration_ms: int | None
    caller_speaking: bool


class ActionView(ApplicationView):
    """`openapi.yaml`'s `ActionDescriptor` — one `available_actions` entry (§10.9, D12)."""

    action_id: str
    label_ru: str
    permission: str
    trigger: str | None


class OperatorStageView(ApplicationView):
    """`openapi.yaml`'s `OperatorStageView` — what every Operator 112 command returns (D8)."""

    role_stage_id: UUID
    stage_state: Operator112StageState
    available_actions: tuple[ActionView, ...]
    card: OperatorCardView
    call_state: CallStateView
    session_state: SessionState
    last_seq_no: int


class ServiceSelectionView(ApplicationView):
    """`openapi.yaml`'s `ServiceSelectionView` — the answer of select/deselect."""

    card_id: UUID
    selected_services: tuple[ServiceType, ...]
    available_services: tuple[ServiceType, ...]
    card: OperatorCardView


# ---------------------------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------------------------

_FIELD_SPEC_VIEWS: tuple[CardFieldSpecView, ...] = tuple(
    CardFieldSpecView(
        field_path=spec.field_path,
        value_type=spec.value_type,
        enum_name=spec.enum_name,
        label_ru=spec.label_ru,
        scoring_relevant=spec.scoring_relevant,
        required_for_handoff=spec.required_for_handoff,
    )
    for spec in CARD_FIELDS
)
"""`CARD_FIELDS`, once: "the UI renders the form from this, never from a hard-coded list"."""


def card_view(card: OperatorCard) -> OperatorCardView:
    """`OperatorCard` -> `OperatorCardView`; only the paths the trainee set are present."""
    return OperatorCardView(
        card_id=UUID(str(card.card_id)),
        incident_id=UUID(str(card.incident_id)),
        values=dict(card.values),
        revision_counter=card.revision_counter,
        field_specs=_FIELD_SPEC_VIEWS,
    )


def revision_view(revision: CardRevision) -> CardRevisionView:
    """`CardRevision` -> `CardRevisionView`."""
    return CardRevisionView(
        revision_id=UUID(str(revision.revision_id)),
        card_id=UUID(str(revision.card_id)),
        revision_no=revision.revision_no,
        field_path=revision.field_path,
        previous_value=revision.previous_value,
        new_value=revision.new_value,
        actor=ActorRefView(
            actor_type=revision.actor.actor_type.value,
            actor_id=(
                None if revision.actor.actor_id is None else UUID(str(revision.actor.actor_id))
            ),
        ),
        at_offset_ms=revision.at_offset_ms,
    )


def action_views(actions: Sequence[ActionDescriptor]) -> tuple[ActionView, ...]:
    """`RoleModule.available_actions(...)` -> the wire-shaped descriptors (§10.9)."""
    return tuple(
        ActionView(
            action_id=action.action_id,
            label_ru=action.label_ru,
            permission=action.permission.value,
            trigger=action.trigger,
        )
        for action in actions
    )


def project_call_state(events: Sequence[SessionEvent]) -> CallStateView:
    """Fold the session's log into the phone widget's state — the only source (D5, SPEC §8).

    `CALL_RINGING` opens a call and carries its `call_id`, `room_name` and `caller_display_ru`;
    `CALL_ANSWERED` connects it; `CALL_ENDED` closes it. `CALLER_TTS_STARTED` /
    `CALLER_TTS_ENDED` drive `caller_speaking`, and `CALLER_UTTERANCE_INTERRUPTED` stops it too —
    a barge-in cancels the audio that is playing (SPEC §42 test 12), so the level meter must not
    keep claiming the caller is speaking.

    A later `CALL_RINGING` (a re-dial) replaces the whole call: the fold starts that call over
    rather than mixing two calls' offsets.
    """
    call_id: UUID | None = None
    room_name: str | None = None
    caller_display_ru: str | None = None
    phase = CallPhase.NO_CALL
    started: int | None = None
    answered: int | None = None
    ended: int | None = None
    speaking = False

    for event in events:
        event_type = event.event_type
        if event_type is EventType.CALL_RINGING:
            call_id = _uuid_or_none(event.payload.get("call_id"))
            room_name = _str_or_none(event.payload.get("room_name"))
            caller_display_ru = _str_or_none(event.payload.get("caller_display_ru"))
            phase = CallPhase.RINGING
            started = event.monotonic_offset_ms
            answered = None
            ended = None
            speaking = False
        elif event_type is EventType.CALL_ANSWERED:
            phase = CallPhase.CONNECTED
            answered = event.monotonic_offset_ms
        elif event_type is EventType.CALL_ENDED:
            phase = CallPhase.ENDED
            ended = event.monotonic_offset_ms
            speaking = False
        elif event_type is EventType.CALLER_TTS_STARTED:
            speaking = True
        elif event_type in _TTS_STOPPED:
            speaking = False

    return CallStateView(
        call_id=call_id,
        room_name=room_name,
        phase=phase,
        caller_display_ru=caller_display_ru,
        started_at_offset_ms=started,
        answered_at_offset_ms=answered,
        ended_at_offset_ms=ended,
        duration_ms=_duration_ms(started, answered, ended),
        caller_speaking=speaking,
    )


_TTS_STOPPED = frozenset({EventType.CALLER_TTS_ENDED, EventType.CALLER_UTTERANCE_INTERRUPTED})
"""The caller stopped producing audio — ended normally, or cut off by a barge-in (§42 test 12)."""


def _duration_ms(started: int | None, answered: int | None, ended: int | None) -> int | None:
    """The *connected* duration: answer to hang-up. `None` until both offsets exist.

    Deliberately not "ring to hang-up": `CALL_ENDED.duration_ms` in the event catalog is the call
    the trainee actually conducted, and a call that was never answered has no such duration.
    """
    if answered is None or ended is None:
        return None
    return max(0, ended - answered)


def _uuid_or_none(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:  # pragma: no cover - the catalog types this key `uuid`
            return None
    return None


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def operator_stage_view(
    session: SimulationSession,
    stage: RoleStage,
    card: OperatorCard,
    events: Sequence[SessionEvent],
    last_seq_no: int,
) -> OperatorStageView:
    """Assemble `OperatorStageView` from the state a command has just produced (D8)."""
    module = ROLE_MODULES[stage.role_type]
    assert isinstance(stage.state, Operator112StageState)
    return OperatorStageView(
        role_stage_id=UUID(str(stage.role_stage_id)),
        stage_state=stage.state,
        available_actions=action_views(module.available_actions(stage.state)),
        card=card_view(card),
        call_state=project_call_state(events),
        session_state=session.state,
        last_seq_no=last_seq_no,
    )


# ---------------------------------------------------------------------------------------------
# §40.6's `session:{id}:call_state` — a cache of the fold above, never an authority
# ---------------------------------------------------------------------------------------------


class CachedCallState(BaseModel):
    """§40.6's `session:{id}:call_state` value: `{call_id, room_name, phase, caller_speaking,
    updated_at}`, key for key.

    It is deliberately *narrower* than `CallStateView`: §40.6 lists five keys and this carries
    exactly those five. Everything else the phone widget shows — the offsets and the duration —
    comes from the fold, which is the authority, so a reader can never mistake a stale cache for
    the call's history.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: UUID | None
    room_name: str | None
    phase: CallPhase
    caller_speaking: bool
    updated_at: datetime


def call_state_document(view: CallStateView, updated_at: datetime) -> str:
    """The JSON a call use case writes into `session:{id}:call_state` after its commit."""
    cached = CachedCallState(
        call_id=view.call_id,
        room_name=view.room_name,
        phase=view.phase,
        caller_speaking=view.caller_speaking,
        updated_at=updated_at,
    )
    return cached.model_dump_json()


async def write_call_state_cache(
    cache: CallStateCache | None,
    session_id: SessionId,
    view: CallStateView,
    updated_at: datetime,
) -> None:
    """Cache `view`'s five §40.6 keys. A `None` cache (no Redis) is a no-op, never an error."""
    if cache is None:
        return
    await cache.put(session_id, call_state_document(view, updated_at))


async def read_cached_call_state(
    cache: CallStateCache | None,
    session_id: SessionId,
    events: Sequence[SessionEvent],
    updated_at: datetime,
) -> CachedCallState:
    """The cached call state, falling back to the fold over `events` whenever the key is not there.

    "Not there" covers every documented loss: no cache wired at all, a lapsed TTL, a `FLUSHALL`, an
    unreachable Redis (the adapter answers `None`) and a value that is not the document this module
    writes. Each of those costs the caller one fold and yields the same answer, which is what makes
    §40.6's "Redis holds nothing that cannot be rebuilt from PostgreSQL" true here.
    """
    document = await cache.get(session_id) if cache is not None else None
    if document is not None:
        try:
            return CachedCallState.model_validate(json.loads(document))
        except (ValueError, ValidationError):
            # A foreign or half-written value is a miss, not a failure: the fold below is the
            # authority and answering from it is always correct.
            logger.warning("session %s: unreadable call_state cache; folding instead", session_id)
    view = project_call_state(events)
    return CachedCallState(
        call_id=view.call_id,
        room_name=view.room_name,
        phase=view.phase,
        caller_speaking=view.caller_speaking,
        updated_at=updated_at,
    )
