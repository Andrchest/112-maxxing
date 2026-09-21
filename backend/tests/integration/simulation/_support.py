"""Shared setup for the simulation integration tests and for INV 7 / INV 13.

Nothing here invents product data: the scenario is the committed demo
(`scenarios/examples/apartment-fire/v1.yaml`), imported by the real importer, and the session is
created and started by the real E5 use cases. A test then drives simulated time by advancing the
`FakeClock` and calling `TickSession` directly — never by sleeping and waiting for a runner.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.application.ports.resource_repository import StoredResource
from app.application.scenarios.import_scenarios import ImportScenarios
from app.application.sessions import CreateSession, StartSession
from app.application.sessions.create_session import CreateSessionCommand
from app.application.simulation import TickSession
from app.application.testing.fakes import (
    FakeClock,
    FakeInferenceReadiness,
    InMemoryEventPublisher,
    SequentialIdGenerator,
)
from app.db.session import create_session_factory
from app.domain.common.actors import ActorRef
from app.domain.common.ids import IncidentId, ResourceId, SessionId, UserId
from app.domain.enums import ActorType, ResourceStatus, SessionMode
from app.domain.events.session_event import DomainEvent
from app.infrastructure.ids import Uuid4Generator
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from app.tools.import_scenarios import YamlScenarioSource
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLES_DIR = REPO_ROOT / "scenarios" / "examples"
DEMO_SLUG = "apartment-fire"

#: Truncating these two reference tables reaches every other table through `CASCADE` and, unlike
#: DELETE, does not fire the `BEFORE DELETE` append-only triggers of §20.9.
TRUNCATE = text("TRUNCATE TABLE users, scenarios RESTART IDENTITY CASCADE")


async def truncate_all(engine: AsyncEngine) -> None:
    """Leave the schema empty."""
    async with engine.begin() as connection:
        await connection.execute(TRUNCATE)


@dataclass(frozen=True)
class SimHarness:
    """One committed, `ACTIVE` demo session plus everything needed to tick it."""

    engine: AsyncEngine
    clock: FakeClock
    publisher: InMemoryEventPublisher
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork]
    tick: TickSession
    session_id: SessionId
    incident_id: IncidentId
    actor: ActorRef

    async def advance_and_tick(self, milliseconds: int) -> Any:
        """Move the clock forward and run exactly one tick."""
        self.clock.advance_ms(milliseconds)
        return await self.tick(self.session_id)

    async def resources(self) -> dict[str, StoredResource]:
        """The session's board, keyed by `scenario_resource_id`."""
        async with self.unit_of_work() as uow:
            stored = await uow.resources.list_for_session(self.session_id)
            await uow.commit()
        return {entry.scenario_resource_id: entry for entry in stored}

    async def set_resource_status(
        self, scenario_resource_id: str, status: ResourceStatus, at_offset_ms: int = 0
    ) -> ResourceId:
        """Park one resource in `status` through the repository (no use case exists yet)."""
        board = await self.resources()
        stored = board[scenario_resource_id]
        moved = stored.resource.model_copy(
            update={"current_status": status, "status_changed_at_offset_ms": at_offset_ms}
        )
        async with self.unit_of_work() as uow:
            await uow.resources.save(self.session_id, moved)
            await uow.commit()
        return moved.resource_id

    async def append(self, event: DomainEvent) -> None:
        """Append one action event to the log, as a command use case would."""
        async with self.unit_of_work() as uow:
            await uow.events.append(self.session_id, [event])
            await uow.commit()

    async def events(self) -> list[Any]:
        """Every persisted event of the session, in `seq_no` order."""
        async with self.unit_of_work() as uow:
            found = await uow.events.read(self.session_id)
            await uow.commit()
        return found


async def build_session(
    engine: AsyncEngine,
    *,
    namespace: int = 0,
    session_seed: str | None = None,
    clock: FakeClock | None = None,
    time_scale: float = 1.0,
    import_scenario: bool = True,
) -> SimHarness:
    """Import the demo scenario, create a session, start it, and return a ready harness.

    `namespace` keeps two sessions in one database apart: `SequentialIdGenerator` is deterministic
    on purpose, so two harnesses built with the same namespace would allocate the same UUIDs.
    """
    clock = clock if clock is not None else FakeClock()
    session_factory = create_session_factory(engine)
    publisher = InMemoryEventPublisher()

    def unit_of_work() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, clock, publisher)

    if import_scenario:
        await ImportScenarios(unit_of_work, YamlScenarioSource())(EXAMPLES_DIR)

    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug(DEMO_SLUG)
        assert stored is not None
        version = await uow.scenarios.find_version(stored.scenario_id, 1)
        assert version is not None
        scenario_version_id = version.scenario_version_id
        await uow.commit()

    instructor_id = await create_user(engine, f"instructor{namespace}-{uuid4().hex[:8]}")
    trainee_id = await create_user(engine, f"trainee{namespace}-{uuid4().hex[:8]}")
    actor = ActorRef(actor_type=ActorType.INSTRUCTOR, actor_id=instructor_id)

    ids = SequentialIdGenerator(namespace=namespace)
    session = await CreateSession(unit_of_work, ids)(
        CreateSessionCommand(
            scenario_version_id=scenario_version_id,
            session_mode=SessionMode.FULL_CYCLE_SINGLE_TRAINEE,
            actor=actor,
            participants=((trainee_id, None),),
            session_seed=session_seed,
            time_scale=time_scale,
        )
    )
    await StartSession(
        unit_of_work,
        clock,
        FakeInferenceReadiness(ready=True),
        Uuid4Generator(),
        require_inference_ready=False,
    )(session.id, actor)

    return SimHarness(
        engine=engine,
        clock=clock,
        publisher=publisher,
        unit_of_work=unit_of_work,
        tick=TickSession(unit_of_work, clock),
        session_id=session.id,
        incident_id=session.incident.incident_id,
        actor=actor,
    )


async def create_user(engine: AsyncEngine, username: str) -> UserId:
    """One committed `users` row (every actor id is a real row)."""
    async with engine.begin() as connection:
        result = await connection.execute(
            text(
                "INSERT INTO users (username, password_hash, display_name_ru)"
                " VALUES (:username, 'x', 'Инструктор') RETURNING id"
            ),
            {"username": username},
        )
        return UserId(UUID(str(result.scalar_one())))


async def scalar(engine: AsyncEngine, statement: str, **params: Any) -> Any:
    """One committed scalar value."""
    async with engine.connect() as connection:
        result = await connection.execute(text(statement), params)
        return result.scalar_one()


async def count(engine: AsyncEngine, table: str, **where: Any) -> int:
    """`SELECT count(*) FROM <table> [WHERE ...]` on committed state only."""
    clause = " AND ".join(f"{column} = :{column}" for column in where)
    statement = f"SELECT count(*) FROM {table}" + (f" WHERE {clause}" if clause else "")
    async with engine.connect() as connection:
        result = await connection.execute(text(statement), where)
        return int(result.scalar_one())
