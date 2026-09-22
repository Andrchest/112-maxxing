"""The D5 seq-lock protocol never deadlocks a runner tick against a voice-agent append (R14).

E19-E3's first real LiveKit run died after two turns with

```
asyncpg.exceptions.DeadlockDetectedError: deadlock detected
[SQL: SELECT next_seq_no FROM simulation_sessions WHERE id = $1 FOR UPDATE]
```

and had to be repeated with `SIM_SIM_TICK_MS=10000` — an environment workaround for a product
defect.

**The mechanism, measured against this same PostgreSQL** (see the task report for the raw probe).
Every table the voice agent writes beside its events — `audio_segments`, `transcript_segments`,
`dialogue_turns`, `inference_metrics` — carries a foreign key to `simulation_sessions.id`, and
PostgreSQL takes a `FOR KEY SHARE` lock on the **referenced** row for each such insert.
`VoiceEventAppender.append` writes those rows first and allocates the `seq_no` afterwards, so its
transaction holds `FOR KEY SHARE` on the session row at the moment §20.8 asks for the stronger
lock. Two such transactions — two overlapping appends of one call — each hold `FOR KEY SHARE` and
each ask to upgrade, and `FOR UPDATE` conflicts with `FOR KEY SHARE`: a lock-upgrade cycle,
reported against exactly the statement above. `FOR NO KEY UPDATE` is **compatible** with
`FOR KEY SHARE` and still conflicts with itself, so it serialises the allocation exactly as §20.8
requires while no upgrade cycle can form. That is the one lock mode every writer now uses, in
`SqlAlchemyEventStore` and in `SessionRepository.get_for_update` alike.

The test drives the product's own repositories, on its own session id (safe under xdist), and
asserts both that nothing raises and that the `seq_no` sequence is still contiguous — the property
§20.8's lock exists for. It bites: with `_LOCK_SESSION_ROW` and `_load(for_update=True)` restored
to `FOR UPDATE` it fails with `DeadlockDetectedError` on the first round.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from app.application.ports.transcript_segment_repository import StoredTranscriptSegment
from app.domain.common.ids import SessionId
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.persistence.conftest import make_event

pytestmark = pytest.mark.integration

#: Enough rounds to be a real soak, few enough to stay a few seconds. E19-E3's run died in two
#: turns; the forced hand-over below makes one round enough on its own.
ROUNDS = 50

#: Each agent-shaped transaction holds its `FOR KEY SHARE` this long before asking for the seq
#: lock, so both hold it when the upgrades are requested. Without the wait the two statements
#: race and the cycle only forms sometimes.
_HANDOVER_S = 0.02


async def _runner_tick(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork], session_id: SessionId
) -> None:
    """What `TickSession` does: the §20.8 row lock first, then the append."""
    async with unit_of_work() as uow:
        await uow.sessions.get_for_update(session_id)
        await uow.events.append(session_id, [make_event()])
        await uow.commit()


async def _agent_append(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
    *,
    ready: asyncio.Barrier,
) -> None:
    """What `VoiceEventAppender.append` does: the batch's child rows first, then the append."""
    async with unit_of_work() as uow:
        await uow.transcript_segments.add(
            StoredTranscriptSegment(
                id=uuid4(),
                session_id=session_id,
                speaker="CALLER",
                start_ms=0,
                end_ms=100,
                text="проверка",
            )
        )
        # The FK's `FOR KEY SHARE` is taken when the INSERT reaches the server, not when the
        # repository returns, so the barrier is only meaningful after a flush.
        await uow.session.flush()
        await ready.wait()
        await asyncio.sleep(_HANDOVER_S)
        await uow.events.append(session_id, [make_event()])
        await uow.commit()


async def _seed_session(engine: AsyncEngine, seeded: dict[str, UUID]) -> SessionId:
    """One more `simulation_sessions` row (+ its `incidents` row) on the fixture's chain.

    Its own id, so copies of this test running side by side under xdist contend only with their
    own tasks.
    """
    async with engine.begin() as connection:
        new_id = (
            await connection.execute(
                text(
                    "INSERT INTO simulation_sessions (scenario_version_id, session_mode,"
                    " session_seed, created_by_user_id, state)"
                    " VALUES (:scenario_version_id, 'SINGLE_ROLE', 'seed', :user_id, 'ACTIVE')"
                    " RETURNING id"
                ),
                {"scenario_version_id": seeded["scenario_version"], "user_id": seeded["user"]},
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


async def test_runner_tick_and_agent_appends_never_deadlock(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    migrated_engine: AsyncEngine,
    seeded: dict[str, UUID],
) -> None:
    """`ROUNDS` rounds of one runner tick against two overlapping agent appends."""
    session_id = await _seed_session(migrated_engine, seeded)

    for _ in range(ROUNDS):
        ready = asyncio.Barrier(2)
        await asyncio.gather(
            _agent_append(unit_of_work, session_id, ready=ready),
            _agent_append(unit_of_work, session_id, ready=ready),
            _runner_tick(unit_of_work, session_id),
        )

    async with unit_of_work() as uow:
        events = await uow.events.read(session_id)
    assert [event.seq_no for event in events] == list(range(1, 3 * ROUNDS + 1))
