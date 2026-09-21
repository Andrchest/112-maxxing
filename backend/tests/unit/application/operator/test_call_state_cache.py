"""§40.6's `session:{id}:call_state` is a CACHE of the fold, and its loss is harmless (SPEC §31).

§40.6's invariant, stated there once: "Redis holds nothing that cannot be rebuilt from PostgreSQL,
and nothing whose loss changes a score, a card value, a stage state, a snapshot or an event."

These tests hold that to the letter for this one key: the same answer comes back whether the key
is present, expired, flushed, unreadable or served by a Redis that is not there at all.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.application.operator.views import (
    CachedCallState,
    CallPhase,
    call_state_document,
    project_call_state,
    read_cached_call_state,
    write_call_state_cache,
)
from app.application.testing.fakes import InMemoryCallStateCache
from app.domain.common.ids import EventId, SessionId
from app.domain.enums import ActorType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType

SESSION = SessionId(uuid4())
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
CALL_ID = UUID("11111111-2222-3333-4444-555555555555")
ROOM = "session-11111111-2222-3333-4444-555555555555"


def event(event_type: EventType, seq_no: int, **payload: object) -> SessionEvent:
    """One stored event, shaped as the event store returns it."""
    return SessionEvent(
        id=EventId(uuid4()),
        session_id=SESSION,
        seq_no=seq_no,
        event_type=event_type,
        actor_type=ActorType.SIMULATION,
        timestamp_utc=NOW,
        monotonic_offset_ms=seq_no * 1000,
        payload=dict(payload),
    )


def ringing_log() -> list[SessionEvent]:
    """A log whose fold is a RINGING call."""
    return [
        event(
            EventType.CALL_RINGING,
            1,
            call_id=str(CALL_ID),
            room_name=ROOM,
            caller_display_ru="Соседка",
            at_offset_ms=1000,
        )
    ]


def connected_log() -> list[SessionEvent]:
    """A log whose fold is a CONNECTED call with the caller speaking."""
    return [
        *ringing_log(),
        event(EventType.CALL_ANSWERED, 2, call_id=str(CALL_ID)),
        event(EventType.CALLER_TTS_STARTED, 3, call_id=str(CALL_ID)),
    ]


# -- the document ---------------------------------------------------------------------------------


def test_the_document_carries_exactly_the_five_keys_of_40_6() -> None:
    document = json.loads(call_state_document(project_call_state(connected_log()), NOW))

    assert set(document) == {"call_id", "room_name", "phase", "caller_speaking", "updated_at"}
    assert document["call_id"] == str(CALL_ID)
    assert document["room_name"] == ROOM
    assert document["phase"] == "CONNECTED"
    assert document["caller_speaking"] is True


# -- hit and miss give the same answer ------------------------------------------------------------


async def test_a_cache_hit_answers_from_the_key() -> None:
    cache = InMemoryCallStateCache()
    await write_call_state_cache(cache, SESSION, project_call_state(connected_log()), NOW)

    # An empty log: only the cache can be answering here.
    state = await read_cached_call_state(cache, SESSION, [], NOW)

    assert state.phase is CallPhase.CONNECTED
    assert state.room_name == ROOM
    assert state.call_id == CALL_ID


async def test_a_flushed_key_falls_back_to_the_fold_with_the_same_answer() -> None:
    cache = InMemoryCallStateCache()
    log = connected_log()
    await write_call_state_cache(cache, SESSION, project_call_state(log), NOW)
    from_cache = await read_cached_call_state(cache, SESSION, log, NOW)

    cache.forget(SESSION)  # a lapsed TTL, or a FLUSHALL against a running simulation
    from_fold = await read_cached_call_state(cache, SESSION, log, NOW)

    assert from_cache == from_fold
    assert from_fold.phase is CallPhase.CONNECTED


async def test_an_unreachable_redis_falls_back_to_the_fold() -> None:
    cache = InMemoryCallStateCache()
    log = ringing_log()
    await write_call_state_cache(cache, SESSION, project_call_state(log), NOW)

    cache.fail_reads = True  # the adapter turns any Redis error into a miss
    state = await read_cached_call_state(cache, SESSION, log, NOW)

    assert state.phase is CallPhase.RINGING
    assert state.room_name == ROOM


async def test_no_cache_at_all_still_answers() -> None:
    """A container with no Redis wired must not make the phone widget unanswerable."""
    state = await read_cached_call_state(None, SESSION, connected_log(), NOW)

    assert state.phase is CallPhase.CONNECTED
    await write_call_state_cache(None, SESSION, project_call_state([]), NOW)  # a no-op, not a crash


async def test_an_unparseable_value_is_a_miss_not_a_failure() -> None:
    cache = InMemoryCallStateCache()
    cache.values[SESSION] = "{not json"

    state = await read_cached_call_state(cache, SESSION, ringing_log(), NOW)

    assert state.phase is CallPhase.RINGING


async def test_a_foreign_document_shape_is_a_miss_not_a_failure() -> None:
    cache = InMemoryCallStateCache()
    cache.values[SESSION] = json.dumps({"something": "else"})

    state = await read_cached_call_state(cache, SESSION, ringing_log(), NOW)

    assert state.phase is CallPhase.RINGING


async def test_an_empty_log_and_no_cache_is_no_call() -> None:
    state = await read_cached_call_state(InMemoryCallStateCache(), SESSION, [], NOW)

    assert state == CachedCallState(
        call_id=None, room_name=None, phase=CallPhase.NO_CALL, caller_speaking=False, updated_at=NOW
    )
