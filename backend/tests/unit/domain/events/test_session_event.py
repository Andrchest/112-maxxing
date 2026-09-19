"""Tests for `app.domain.events.session_event` (HLD `10-domain-model.md` §10.13, D5).

Light construction coverage: `SessionEvent` and `DomainEvent` accept the fields §10.13 lists, and
`DomainEvent.actor` is the `common/actors.py` `ActorRef` (ruling R1 — one home, not a per-module
copy).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.domain.common.actors import ActorRef
from app.domain.enums import ActorType
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType


def test_session_event_round_trips_its_fields() -> None:
    event = SessionEvent(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        seq_no=1,
        event_type=EventType.SESSION_CREATED,
        timestamp_utc=datetime.now(UTC),
        monotonic_offset_ms=0,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
        correlation_id=None,
        payload={"session_id": "x"},
    )
    assert event.event_type == EventType.SESSION_CREATED
    assert event.payload["session_id"] == "x"


def test_domain_event_carries_an_actor_ref_from_the_one_common_home() -> None:
    actor = ActorRef(actor_type=ActorType.TRAINEE, actor_id=uuid.uuid4())
    event = DomainEvent(
        event_type=EventType.CARD_FIELD_CHANGED,
        actor=actor,
        monotonic_offset_ms=100,
        correlation_id=None,
        payload={"field_path": "address.street"},
    )
    assert event.actor == actor
    assert event.actor.actor_type == ActorType.TRAINEE
