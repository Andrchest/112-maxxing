"""§40.4 — per-event-type visibility and payload redaction, in exactly one place (D3, D8).

`40-realtime-protocol.md` §40.4 "How redaction is applied": "Redaction happens in exactly one
place, `DataVisibilityPolicy` plus a per-event-type key whitelist in
`backend/app/application/realtime/redaction.py`, applied to the envelope **before** it reaches the
socket writer. […] The same function serves `GET /api/v1/sessions/{id}/events` and the report
timeline, so the three read paths cannot drift." `redact` is that function; `list_events.py` and
`event_stream.py` are its only two callers today, and a third read path adds a caller, never a
second copy of the table.

Three gates, applied in this order:

1. **Visibility** — `DataVisibilityPolicy.visible_event_types` of the role's `RoleModule` (§10.9,
   the whitelist §40.4's columns are copied into). An `INSTRUCTOR` connection sees every type. A
   type outside the set returns `None`: the push loop never serialises it for that connection, so
   `WORLD_TRUTH_MUTATED` is not "hidden in the UI", it is absent from the socket.
2. **Delivery filters** — the three `▲` rows whose delivery depends on a payload key rather than
   on the type: `STAGE_STATE_CHANGED.role_type`, `NOTIFICATION_CREATED.audience_role` and
   `RADIO_MESSAGE_CREATED.to_role` must equal the connection's role. `ASR_PARTIAL` is §40.4's one
   `◆` row and obeys `SessionPolicy.show_asr_partials` (false in `ASSESSMENT`, §10.10).
3. **Key whitelist** — never a blacklist (D3). The keys a trainee role may see are an explicit
   tuple per event type, defaulting to the event's `EVENT_PAYLOAD_CATALOG` keys. A payload key
   that nobody has whitelisted — a key added to the catalog later, or a key a buggy producer
   invented — is therefore removed for a trainee and named in `redacted_keys`, and is visible to
   the instructor. Hiding by default is the only failure mode D3 tolerates.

`redacted_keys` is always `[]` for `INSTRUCTOR` (§40.2).

HLD gap (reported): §40.4 row 38 says `NOTIFICATION_ACKNOWLEDGED` is "pushed only to the
notification's `audience_role`", but neither §10.13's catalog entry for it nor `openapi.yaml`
carries an audience key in that payload — the discriminator the filter needs does not exist in the
event. The reading closest to the catalog ("one fact expressed twice") is applied: the event is
pushed to both trainee roles, which is its static `visible_to` set, and no payload of another
role's notification is disclosed by it (it carries a `notification_id`, two offsets and the
acknowledging user's id).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.application.ports.event_publisher import EventEnvelope
from app.application.realtime.effective_role import EffectiveRole
from app.domain.enums import ActorType, RoleType
from app.domain.events.catalog import EVENT_PAYLOAD_CATALOG
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.roles.registry import ROLE_MODULES
from app.domain.session.policy import SessionPolicy

__all__ = [
    "PAYLOAD_KEY_WHITELIST",
    "RealtimeEnvelope",
    "SourceEvent",
    "redact",
    "source_of_envelope",
    "source_of_row",
    "visible_event_types",
]


class RealtimeEnvelope(BaseModel):
    """`openapi.yaml`'s `SessionEventEnvelope` and §40.2's `event` frame minus its `type`.

    One schema, two delivery mechanisms (§40.2): `listSessionEvents` returns exactly this object
    and the WebSocket writes `{"type": "event", **this}`. Building both from one model is what
    makes them byte-identical rather than merely similar.
    """

    model_config = ConfigDict(frozen=True)

    seq_no: int
    event_type: EventType
    timestamp_utc: datetime
    monotonic_offset_ms: int
    payload: Mapping[str, Any]
    actor_type: ActorType
    correlation_id: UUID | None = None
    redacted_keys: tuple[str, ...] = ()


class SourceEvent(BaseModel):
    """The unredacted input of `redact`, common to both read paths.

    The replay reads `SessionEvent` rows from PostgreSQL and the tail reads `EventEnvelope`s off
    Redis; §40.3's "Replay equals live" guarantee is that both become the *same* envelope through
    the *same* filter, so both are projected onto this one shape first (`of_event` / `of_row`).
    """

    model_config = ConfigDict(frozen=True)

    seq_no: int
    event_type: EventType
    timestamp_utc: datetime
    monotonic_offset_ms: int
    actor_type: ActorType
    correlation_id: UUID | None = None
    payload: Mapping[str, Any]


def source_of_row(event: SessionEvent) -> SourceEvent:
    """Project a persisted `session_events` row (the replay path) onto `SourceEvent`."""
    return SourceEvent(
        seq_no=event.seq_no,
        event_type=event.event_type,
        timestamp_utc=event.timestamp_utc,
        monotonic_offset_ms=event.monotonic_offset_ms,
        actor_type=event.actor_type,
        correlation_id=event.correlation_id,
        payload=event.payload,
    )


def source_of_envelope(envelope: EventEnvelope) -> SourceEvent:
    """Project an unredacted Redis fan-out envelope (the live path) onto `SourceEvent`."""
    return SourceEvent(
        seq_no=envelope.seq_no,
        event_type=envelope.event_type,
        timestamp_utc=envelope.timestamp_utc,
        monotonic_offset_ms=envelope.monotonic_offset_ms,
        actor_type=envelope.actor_type,
        correlation_id=envelope.correlation_id,
        payload=envelope.payload,
    )


def _catalog_keys(event_type: EventType) -> frozenset[str]:
    return frozenset(EVENT_PAYLOAD_CATALOG[event_type].payload_keys)


def _without(event_type: EventType, *dropped: str) -> frozenset[str]:
    """The catalog's keys minus `dropped` — written as a *derived* whitelist, never a blacklist.

    The difference matters: the result is a frozen set of names computed at import time from the
    catalog, so a key added to the catalog later is **not** in it and is hidden from trainees
    until somebody adds it here deliberately.
    """
    keys = _catalog_keys(event_type)
    unknown = frozenset(dropped) - keys
    assert not unknown, f"{event_type}: §40.4 drops {sorted(unknown)}, absent from the catalog"
    return keys - frozenset(dropped)


#: The `▲` rows of §40.4, as the exact key set a **trainee** role receives. Every other visible
#: event type falls back to its catalog keys. The comments name the §40.4 row.
PAYLOAD_KEY_WHITELIST: Mapping[EventType, frozenset[str]] = {
    # Row 9: "drop `asr_provider`, `asr_model`, `confidence`".
    EventType.ASR_FINAL: _without(EventType.ASR_FINAL, "asr_provider", "asr_model", "confidence"),
    # Row 12: "trainee receives only `{call_id, turn_index, at_offset_ms}`".
    EventType.CALLER_TTS_STARTED: frozenset({"call_id", "turn_index", "at_offset_ms"}),
    # Row 13: "trainee receives only `{call_id, turn_index, at_offset_ms, completed}`".
    EventType.CALLER_TTS_ENDED: frozenset({"call_id", "turn_index", "at_offset_ms", "completed"}),
    # Row 14: "drop `planned_text`" — what the caller *would* have said (SPEC §21).
    EventType.CALLER_UTTERANCE_INTERRUPTED: _without(
        EventType.CALLER_UTTERANCE_INTERRUPTED, "planned_text"
    ),
    # Row 22: "DDS payload drops `source_world_event_id`".
    EventType.RESOURCE_STATUS_CHANGED: _without(
        EventType.RESOURCE_STATUS_CHANGED, "source_world_event_id"
    ),
    # Row 37: "drop `source_world_event_id` for trainees".
    EventType.NOTIFICATION_CREATED: _without(
        EventType.NOTIFICATION_CREATED, "source_world_event_id"
    ),
    # Row 39: "drop `source_world_event_id` for trainees".
    EventType.RADIO_MESSAGE_CREATED: _without(
        EventType.RADIO_MESSAGE_CREATED, "source_world_event_id"
    ),
}

#: §40.4's three delivery filters: `event_type -> the payload key that must equal the role`.
_ROLE_DISCRIMINATOR: Mapping[EventType, str] = {
    EventType.STAGE_STATE_CHANGED: "role_type",  # row 30
    EventType.NOTIFICATION_CREATED: "audience_role",  # row 37
    EventType.RADIO_MESSAGE_CREATED: "to_role",  # row 39
    # Row 38, `NOTIFICATION_ACKNOWLEDGED`, is deliberately absent — there is no key to filter on.
    # TODO(E9): add audience_role to the NOTIFICATION_ACKNOWLEDGED payload (additive, §10.13 +
    # openapi) and filter on it. E9 owns notifications; until then the event is pushed to both
    # trainee roles, which is its static `visible_to` set (see this module's docstring).
}


def visible_event_types(role: EffectiveRole) -> frozenset[EventType] | None:
    """The role's `visible_event_types`; `None` for `INSTRUCTOR`, which sees every type (§40.1).

    `None` rather than `frozenset(EventType)` so a caller passing it to
    `EventStore.last_seq_no(event_types=…)` asks for an unfiltered `MAX` instead of a 49-member
    `IN` list that means the same thing.
    """
    if not isinstance(role, RoleType):
        return None
    return ROLE_MODULES[role].visibility_policy.visible_event_types


def redact(
    event: SourceEvent, role: EffectiveRole, policy: SessionPolicy
) -> RealtimeEnvelope | None:
    """The §40.4 verdict for one event and one connection.

    `None` means "never serialised for this role" — the caller drops the event entirely and does
    not advance anything the client can see. Otherwise the returned envelope's `payload` holds
    exactly the keys this role may see and `redacted_keys` names, sorted, what was removed.
    """
    if not isinstance(role, RoleType):  # INSTRUCTOR: every type, every key, `redacted_keys == []`
        return _envelope(event, dict(event.payload), ())

    module = ROLE_MODULES[role]
    if not module.visibility_policy.may_receive(event.event_type):
        return None

    # §40.4's one `◆` row: `ASSESSMENT` sets `show_asr_partials` false (§10.10), and the *whole*
    # event is withheld then — not merely its text.
    if event.event_type is EventType.ASR_PARTIAL and not policy.show_asr_partials:
        return None

    discriminator = _ROLE_DISCRIMINATOR.get(event.event_type)
    if discriminator is not None and not _matches_role(event.payload.get(discriminator), role):
        return None

    allowed = PAYLOAD_KEY_WHITELIST.get(event.event_type, _catalog_keys(event.event_type))
    payload = {key: value for key, value in event.payload.items() if key in allowed}
    removed = tuple(sorted(key for key in event.payload if key not in allowed))
    return _envelope(event, payload, removed)


def _matches_role(value: object, role: RoleType) -> bool:
    """Does a payload's role discriminator name this connection's role?

    A missing or unparsable discriminator is **not** a match: §40.4's table is a whitelist, so an
    event that cannot prove it is addressed to this role is not pushed to it (D3).
    """
    if isinstance(value, RoleType):
        return value is role
    if isinstance(value, str):
        return value == role.value
    return False


def _envelope(
    event: SourceEvent, payload: Mapping[str, Any], redacted_keys: tuple[str, ...]
) -> RealtimeEnvelope:
    return RealtimeEnvelope(
        seq_no=event.seq_no,
        event_type=event.event_type,
        timestamp_utc=event.timestamp_utc,
        monotonic_offset_ms=event.monotonic_offset_ms,
        payload=payload,
        actor_type=event.actor_type,
        correlation_id=event.correlation_id,
        redacted_keys=redacted_keys,
    )
