"""`StartSession` and `AbortSession` against real PostgreSQL (E5, §10.8, D5, D8).

Every rejected command is checked twice: the exception, *and* the fact that the committed database
is exactly where it was — same state, same event count. A command that raises but leaves a row
behind would be worse than one that never ran.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from app.application.sessions import AbortSession, CreateSession, SessionNotFoundError, StartSession
from app.application.testing.fakes import (
    FakeClock,
    FakeInferenceReadiness,
    InMemoryEventPublisher,
)
from app.domain.common.actors import ActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import ScenarioVersionId, SessionId, UserId
from app.domain.enums import SessionState
from app.domain.session.session import SimulationSession
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.sessions.conftest import count, scalar

from .test_create_session import command

pytestmark = pytest.mark.integration


@pytest.fixture
async def ready_session(
    create_session: CreateSession,
    demo_version_id: ScenarioVersionId,
    instructor: ActorRef,
    users: dict[str, UserId],
) -> SimulationSession:
    """One `READY` session over the demo scenario, one trainee on both stages."""
    return await create_session(command(demo_version_id, instructor, users["trainee1"]))


async def event_types(engine: AsyncEngine, session_id: SessionId) -> list[str]:
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT event_type FROM session_events WHERE session_id = :id ORDER BY seq_no"),
            {"id": UUID(str(session_id))},
        )
        return [str(row[0]) for row in result.all()]


async def event_offsets(engine: AsyncEngine, session_id: SessionId) -> dict[str, list[int]]:
    """`monotonic_offset_ms` per event type, in `seq_no` order (SPEC §39)."""
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT event_type, monotonic_offset_ms FROM session_events "
                "WHERE session_id = :id ORDER BY seq_no"
            ),
            {"id": UUID(str(session_id))},
        )
        offsets: dict[str, list[int]] = {}
        for event_type, offset_ms in result.all():
            offsets.setdefault(str(event_type), []).append(int(offset_ms))
        return offsets


async def stored_state(engine: AsyncEngine, session_id: SessionId) -> str:
    return str(
        await scalar(
            engine,
            "SELECT state FROM simulation_sessions WHERE id = :id",
            id=UUID(str(session_id)),
        )
    )


# ---------------------------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------------------------


async def test_start_moves_ready_to_active_and_appends_two_events(
    start_session: StartSession,
    ready_session: SimulationSession,
    instructor: ActorRef,
    clock: FakeClock,
    migrated_engine: AsyncEngine,
    publisher: InMemoryEventPublisher,
) -> None:
    started = await start_session(ready_session.id, instructor)

    assert started.state is SessionState.ACTIVE
    assert started.started_at == clock.now()
    assert started.stages[0].started_at_offset_ms == 0

    assert await stored_state(migrated_engine, ready_session.id) == "ACTIVE"
    stored_started_at = await scalar(
        migrated_engine,
        "SELECT started_at FROM simulation_sessions WHERE id = :id",
        id=UUID(str(ready_session.id)),
    )
    assert stored_started_at == clock.now()

    assert await event_types(migrated_engine, ready_session.id) == [
        "SESSION_CREATED",
        "SESSION_STARTED",
        "ROLE_STAGE_STARTED",
    ]
    assert len(publisher.envelopes_for(ready_session.id)) == 3


async def test_start_is_refused_when_inference_is_not_ready(
    unit_of_work: Callable[..., Any],
    clock: FakeClock,
    ready_session: SimulationSession,
    instructor: ActorRef,
    migrated_engine: AsyncEngine,
) -> None:
    """D8: with `REQUIRE_INFERENCE_READY` on, `guard_inference_ready` denies `start`."""
    inference = FakeInferenceReadiness(ready=False)
    use_case = StartSession(unit_of_work, clock, inference, require_inference_ready=True)

    before = await event_types(migrated_engine, ready_session.id)
    with pytest.raises(InvalidTransitionError) as excinfo:
        await use_case(ready_session.id, instructor)

    assert excinfo.value.trigger == "start"
    assert inference.calls == 1
    assert await stored_state(migrated_engine, ready_session.id) == "READY"
    assert await event_types(migrated_engine, ready_session.id) == before


async def test_the_flag_short_circuits_the_readiness_port(
    unit_of_work: Callable[..., Any],
    clock: FakeClock,
    ready_session: SimulationSession,
    instructor: ActorRef,
) -> None:
    """`require_inference_ready=False` never asks the port at all (D8)."""
    inference = FakeInferenceReadiness(ready=False)
    use_case = StartSession(unit_of_work, clock, inference, require_inference_ready=False)
    started = await use_case(ready_session.id, instructor)
    assert started.state is SessionState.ACTIVE
    assert inference.calls == 0


async def test_start_of_an_unknown_session_is_a_404(
    start_session: StartSession, instructor: ActorRef
) -> None:
    missing = SessionId(UUID("00000000-0000-4000-8000-0000000000fe"))
    with pytest.raises(SessionNotFoundError):
        await start_session(missing, instructor)
    assert SessionNotFoundError.code == "NOT_FOUND"


# ---------------------------------------------------------------------------------------------
# abort
# ---------------------------------------------------------------------------------------------


async def test_abort_from_ready(
    abort_session: AbortSession,
    ready_session: SimulationSession,
    instructor: ActorRef,
    migrated_engine: AsyncEngine,
) -> None:
    aborted = await abort_session(ready_session.id, instructor, "инструктор прервал занятие")

    assert aborted.state is SessionState.ABORTED
    assert aborted.abort_reason == "инструктор прервал занятие"
    assert await stored_state(migrated_engine, ready_session.id) == "ABORTED"
    assert (await event_types(migrated_engine, ready_session.id))[-1] == "SESSION_ABORTED"


async def test_abort_from_created(
    abort_session: AbortSession,
    ready_session: SimulationSession,
    instructor: ActorRef,
    unit_of_work: Callable[..., Any],
    migrated_engine: AsyncEngine,
) -> None:
    """`CreateSession` always validates, so it never leaves a session in `CREATED`; the state is
    pushed back through the repository because `CREATED --abort--> ABORTED` is a real §10.8 row
    that a resumed, half-created session can still need."""
    async with unit_of_work() as uow:
        await uow.sessions.save(ready_session.model_copy(update={"state": SessionState.CREATED}))
        await uow.commit()

    aborted = await abort_session(ready_session.id, instructor, "снято до старта")
    assert aborted.state is SessionState.ABORTED
    assert await stored_state(migrated_engine, ready_session.id) == "ABORTED"


async def test_abort_from_active(
    start_session: StartSession,
    abort_session: AbortSession,
    ready_session: SimulationSession,
    instructor: ActorRef,
    migrated_engine: AsyncEngine,
) -> None:
    await start_session(ready_session.id, instructor)
    aborted = await abort_session(ready_session.id, instructor, "техническая неисправность")

    assert aborted.state is SessionState.ABORTED
    assert await stored_state(migrated_engine, ready_session.id) == "ABORTED"
    # One STAGE_STATE_CHANGED per non-terminal stage, then SESSION_ABORTED (§10.8).
    types = await event_types(migrated_engine, ready_session.id)
    assert types[-1] == "SESSION_ABORTED"
    assert types.count("STAGE_STATE_CHANGED") == len(ready_session.stages)


async def test_abort_of_an_active_session_is_stamped_with_the_elapsed_offset(
    start_session: StartSession,
    abort_session: AbortSession,
    ready_session: SimulationSession,
    instructor: ActorRef,
    clock: FakeClock,
    migrated_engine: AsyncEngine,
) -> None:
    """SPEC §39, D7: the offset is `now - started_at`, not a process-monotonic reading.

    `SESSION_STARTED` is the origin (offset 0); 1.5 s later every event the abort emits — the
    `STAGE_STATE_CHANGED` per closed stage and `SESSION_ABORTED` — must carry 1500.
    """
    await start_session(ready_session.id, instructor)
    clock.advance_ms(1500)

    await abort_session(ready_session.id, instructor, "прервано через полторы секунды")

    offsets = await event_offsets(migrated_engine, ready_session.id)
    assert offsets["SESSION_STARTED"] == [0]
    assert offsets["SESSION_ABORTED"] == [1500]
    assert offsets["STAGE_STATE_CHANGED"] == [1500] * len(ready_session.stages)


async def test_abort_before_start_is_stamped_with_offset_zero(
    abort_session: AbortSession,
    ready_session: SimulationSession,
    instructor: ActorRef,
    clock: FakeClock,
    migrated_engine: AsyncEngine,
) -> None:
    """`started_at is None`: there is no origin yet, so the abort shares `SESSION_CREATED`'s 0."""
    clock.advance_ms(9000)

    await abort_session(ready_session.id, instructor, "снято до старта")

    assert (await event_offsets(migrated_engine, ready_session.id))["SESSION_ABORTED"] == [0]


async def test_abort_of_an_aborted_session_is_refused_and_appends_nothing(
    abort_session: AbortSession,
    ready_session: SimulationSession,
    instructor: ActorRef,
    migrated_engine: AsyncEngine,
) -> None:
    await abort_session(ready_session.id, instructor, "первый раз")
    before = await event_types(migrated_engine, ready_session.id)

    with pytest.raises(InvalidTransitionError) as excinfo:
        await abort_session(ready_session.id, instructor, "второй раз")

    assert excinfo.value.trigger == "abort"
    assert await event_types(migrated_engine, ready_session.id) == before
    assert await stored_state(migrated_engine, ready_session.id) == "ABORTED"


async def test_abort_of_a_completed_session_is_refused(
    abort_session: AbortSession,
    ready_session: SimulationSession,
    instructor: ActorRef,
    unit_of_work: Callable[..., Any],
    migrated_engine: AsyncEngine,
) -> None:
    """`COMPLETED` has no `abort` row (§10.8). Completing is TODO(E7), so the state is set
    through the repository rather than through a use case that does not exist yet."""
    async with unit_of_work() as uow:
        await uow.sessions.save(ready_session.model_copy(update={"state": SessionState.COMPLETED}))
        await uow.commit()
    before = await event_types(migrated_engine, ready_session.id)

    with pytest.raises(InvalidTransitionError):
        await abort_session(ready_session.id, instructor, "поздно")

    assert await event_types(migrated_engine, ready_session.id) == before
    assert await stored_state(migrated_engine, ready_session.id) == "COMPLETED"


# ---------------------------------------------------------------------------------------------
# SPEC §42 invariant 5: one session, one incident — whatever happens to the session
# ---------------------------------------------------------------------------------------------


async def test_start_then_abort_leaves_exactly_one_incident(
    start_session: StartSession,
    abort_session: AbortSession,
    ready_session: SimulationSession,
    instructor: ActorRef,
    migrated_engine: AsyncEngine,
) -> None:
    await start_session(ready_session.id, instructor)
    await abort_session(ready_session.id, instructor, "проверка инварианта 5")
    assert await count(migrated_engine, "incidents", session_id=UUID(str(ready_session.id))) == 1
