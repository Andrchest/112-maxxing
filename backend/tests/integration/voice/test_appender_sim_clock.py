"""`VoiceEventAppender.append` stamps `monotonic_offset_ms` from a fresh, unlocked read of the
session row (E20-E2, R11 follow-up; audit-2's "raw wall offset" finding).

Real PostgreSQL, the real appender — not the unit tests' fake store (`tests.unit.application.
voice.test_voice_events` already covers the fake-store shape of this fix; this module is the
"through the real appender against the test Postgres" half the ruling asked for). Sessions are
seeded directly by SQL, mirroring `tests.integration.persistence.test_seq_lock_order._seed_session`
— a `simulation_sessions` row plus its `incidents` row, with `started_at`/`state`/
`role_transition_started_offset_ms` set exactly, rather than driving the whole HTTP call-flow
chain just to reach one state.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from uuid import UUID

import pytest
from app.application.testing.fakes import FakeClock
from app.application.voice.events import VoiceEventAppender, user_speech_ended_event
from app.application.voice.turn_detector import DetectedTurn, TurnEndReason
from app.domain.common.ids import SessionId
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

CALL_ID = uuid.UUID("66666666-6666-4666-8666-666666666666")


def _turn() -> DetectedTurn:
    return DetectedTurn(
        turn_id=uuid.uuid4(),
        turn_index=0,
        audio=b"\x00\x00" * 1600,
        start_ms=0,
        end_ms=640,
        is_barge_in=False,
        pre_roll_ms=0,
        end_reason=TurnEndReason.ENDPOINT_SILENCE,
        discarded_short=False,
    )


async def _seed_session(
    engine: AsyncEngine,
    seeded: dict[str, UUID],
    clock: FakeClock,
    *,
    state: str,
    role_transition_started_offset_ms: int | None,
) -> SessionId:
    """One more `simulation_sessions` row (+ its `incidents` row) on the fixture's chain, with
    `started_at` pinned to the `clock` fixture's own origin so `running_ms`'s arithmetic is exact
    (mirrors `tests.integration.persistence.test_seq_lock_order._seed_session`)."""
    async with engine.begin() as connection:
        new_id = (
            await connection.execute(
                text(
                    "INSERT INTO simulation_sessions (scenario_version_id, session_mode,"
                    " session_seed, created_by_user_id, state, started_at,"
                    " role_transition_started_offset_ms)"
                    " VALUES (:scenario_version_id, 'SINGLE_ROLE', 'seed', :user_id, :state,"
                    " :started_at, :role_transition_started_offset_ms) RETURNING id"
                ),
                {
                    "scenario_version_id": seeded["scenario_version"],
                    "user_id": seeded["user"],
                    "state": state,
                    "started_at": clock.now(),
                    "role_transition_started_offset_ms": role_transition_started_offset_ms,
                },
            )
        ).scalar_one()
        await connection.execute(
            text(
                "INSERT INTO incidents (session_id, scenario_version_id)"
                " VALUES (:session_id, :scenario_version_id)"
            ),
            {"session_id": new_id, "scenario_version_id": seeded["scenario_version"]},
        )
    return SessionId(UUID(str(new_id)))


async def test_a_call_event_during_role_transition_is_stamped_with_the_frozen_running_ms(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    migrated_engine: AsyncEngine,
    seeded: dict[str, UUID],
    clock: FakeClock,
) -> None:
    """A session parked in `ROLE_TRANSITION` (offset 30 000 ms) then a call event appended 90 s
    after `started_at` -> persisted at 30 000 ms, not 90 000 ms."""
    started_at = clock.now()
    session_id = await _seed_session(
        migrated_engine,
        seeded,
        clock,
        state="ROLE_TRANSITION",
        role_transition_started_offset_ms=30_000,
    )
    clock.advance_ms(90_000)
    appender = VoiceEventAppender(
        session_id=session_id, uow_factory=unit_of_work, clock=clock, started_at=started_at
    )
    turn = _turn()
    # Built with the appender's own raw, unfrozen estimate — deliberately the wrong number, to
    # prove append() is what corrects it, not the caller.
    event = user_speech_ended_event(
        turn, call_id=CALL_ID, offset_ms=appender.offset_ms(), endpoint_silence_ms=320
    )
    assert event.monotonic_offset_ms == 90_000, "sanity: the raw estimate really is the wrong one"

    (appended,) = await appender.append([event])

    assert appended.monotonic_offset_ms == 30_000, "frozen at the offset the transition began at"


async def test_a_normal_interview_phase_event_is_stamped_with_the_unfrozen_running_ms(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    migrated_engine: AsyncEngine,
    seeded: dict[str, UUID],
    clock: FakeClock,
) -> None:
    """No open transition -> the persisted offset is the plain elapsed time, same as before this
    fix (E20-E2)."""
    started_at = clock.now()
    session_id = await _seed_session(
        migrated_engine, seeded, clock, state="ACTIVE", role_transition_started_offset_ms=None
    )
    clock.advance_ms(45_000)
    appender = VoiceEventAppender(
        session_id=session_id, uow_factory=unit_of_work, clock=clock, started_at=started_at
    )
    turn = _turn()
    event = user_speech_ended_event(
        turn, call_id=CALL_ID, offset_ms=appender.offset_ms(), endpoint_silence_ms=320
    )

    (appended,) = await appender.append([event])

    assert appended.monotonic_offset_ms == 45_000
