"""Identifier objects in an event payload become canonical strings at the one row boundary.

`session_events.payload` is `jsonb`, and the pure domain legitimately puts `UUID` *objects* in a
payload: `app.domain.world.apply` emits `RESOURCE_STATUS_CHANGED.resource_id` as a `ResourceId` and
derives the notification and radio ids with `uuid5` (D2/D7 — a pure domain may not draw `uuid4`).
§10.13 types those keys `"uuid"`, which at rest is a JSON string.

The conversion therefore belongs to `app.infrastructure.persistence.mappers` — the single
`DomainEvent` -> row boundary every producer shares — and not to any one use case. What this file
pins is that the four things a caller can observe are the *same* JSON-safe payload:

1. the `SessionEvent` the event store returns from `append`;
2. the `SessionEvent` a later `read()` rebuilds from the row;
3. the raw `jsonb` column;
4. the envelope the Unit of Work publishes after the commit (§20.8, §40.6).

A payload is nested on purpose: a top-level id, one inside a dict and one inside a list, because a
shallow conversion would pass 1-2 and fail 3.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from app.application.testing.fakes import InMemoryEventPublisher
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId
from app.domain.enums import ActorType
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

TOP_LEVEL = UUID("11111111-1111-4111-8111-111111111111")
NESTED = UUID("22222222-2222-4222-8222-222222222222")
IN_LIST = UUID("33333333-3333-4333-8333-333333333333")

EXPECTED = {
    "resource_id": str(TOP_LEVEL),
    "detail": {"assignment_id": str(NESTED), "reason": "breakdown"},
    "selected_resource_ids": [str(IN_LIST), "not-a-uuid"],
    "at_offset_ms": 1234,
    "nothing": None,
}
"""Exactly the payload below, with every `UUID` rendered and everything else left alone."""


def _event() -> DomainEvent:
    return DomainEvent(
        event_type=EventType.RESOURCE_STATUS_CHANGED,
        actor=ActorRef(actor_type=ActorType.SIMULATION),
        monotonic_offset_ms=1234,
        correlation_id=uuid4(),
        payload={
            "resource_id": TOP_LEVEL,
            "detail": {"assignment_id": NESTED, "reason": "breakdown"},
            "selected_resource_ids": [IN_LIST, "not-a-uuid"],
            "at_offset_ms": 1234,
            "nothing": None,
        },
    )


async def test_uuids_in_a_payload_round_trip_as_canonical_strings(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
    publisher: InMemoryEventPublisher,
    migrated_engine: AsyncEngine,
) -> None:
    async with unit_of_work() as uow:
        appended = await uow.events.append(session_id, [_event()])
        await uow.commit()

    # 1. what `append` handed back
    assert len(appended) == 1
    assert dict(appended[0].payload) == EXPECTED

    # 2. what a later read rebuilds from the row
    async with unit_of_work() as uow:
        read_back = await uow.events.read(session_id)
        await uow.commit()
    assert [dict(event.payload) for event in read_back] == [EXPECTED]

    # 3. the raw jsonb column — nothing here was ever a Python object
    async with migrated_engine.connect() as connection:
        row = await connection.execute(
            text("SELECT payload FROM session_events WHERE session_id = :sid"),
            {"sid": UUID(str(session_id))},
        )
        stored = row.scalar_one()
    assert stored == EXPECTED
    assert json.loads(json.dumps(stored)) == EXPECTED  # genuinely JSON, not merely dict-shaped

    # 4. the envelope published after the commit (§40.6)
    envelopes = publisher.envelopes_for(session_id)
    assert len(envelopes) == 1
    assert dict(envelopes[0].payload) == EXPECTED
    # The envelope is serialised to JSON on the wire; a stray UUID would raise here.
    assert json.loads(envelopes[0].model_dump_json())["payload"] == EXPECTED


async def test_a_payload_without_identifiers_is_passed_through_unchanged(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork], session_id: SessionId
) -> None:
    """The normalisation must not disturb an ordinary payload (scalars, lists, nested objects)."""
    payload = {"changes": [{"fact_id": "address.house", "new_value": "27"}], "revision": 3}
    event = DomainEvent(
        event_type=EventType.WORLD_TRUTH_MUTATED,
        actor=ActorRef(actor_type=ActorType.SIMULATION),
        monotonic_offset_ms=0,
        payload=payload,
    )
    async with unit_of_work() as uow:
        appended = await uow.events.append(session_id, [event])
        await uow.commit()
    assert dict(appended[0].payload) == payload
