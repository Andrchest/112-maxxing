"""`CreateSession` against real PostgreSQL (E5, §20.3, §20.4, D3, D4, D5, D6).

Two things are under test and they are not the same thing: what one successful creation *writes*
(the aggregate, the three layer rows, the version lock, the event), and what a rejected creation
*leaves behind* — which must be nothing at all, the scenario version included.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from app.application.sessions import (
    CreateSession,
    CreateSessionCommand,
    ScenarioVersionNotFoundError,
)
from app.application.testing.fakes import InMemoryEventPublisher, SequentialIdGenerator
from app.domain.common.actors import ActorRef
from app.domain.common.errors import (
    InvalidTransitionError,
    PrefabHandoffRequiredError,
    RoleChainLengthError,
)
from app.domain.common.ids import ScenarioVersionId, UserId
from app.domain.enums import RoleType, SessionMode, SessionState
from app.domain.events.types import EventType
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.sessions.conftest import count, locked_at, scalar

pytestmark = pytest.mark.integration


def command(
    scenario_version_id: ScenarioVersionId,
    instructor: ActorRef,
    trainee_id: UserId,
    *,
    session_mode: SessionMode = SessionMode.FULL_CYCLE_SINGLE_TRAINEE,
    time_scale: float = 1.0,
) -> CreateSessionCommand:
    """One trainee playing every stage of the demo scenario's `[OPERATOR_112, DDS]` chain."""
    return CreateSessionCommand(
        scenario_version_id=scenario_version_id,
        session_mode=session_mode,
        actor=instructor,
        participants=((trainee_id, None),),
        time_scale=time_scale,
    )


# ---------------------------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------------------------


async def test_creation_writes_the_aggregate_the_three_layers_and_one_event(
    create_session: CreateSession,
    demo_version_id: ScenarioVersionId,
    instructor: ActorRef,
    users: dict[str, UserId],
    migrated_engine: AsyncEngine,
    publisher: InMemoryEventPublisher,
) -> None:
    session = await create_session(command(demo_version_id, instructor, users["trainee1"]))
    session_key = UUID(str(session.id))
    incident_key = UUID(str(session.incident.incident_id))

    assert session.state is SessionState.READY
    assert len(session.stages) == 2

    assert await count(migrated_engine, "simulation_sessions", id=session_key) == 1
    assert await count(migrated_engine, "incidents", session_id=session_key) == 1
    assert await count(migrated_engine, "role_stages", session_id=session_key) == 2
    assert await count(migrated_engine, "session_participants", session_id=session_key) == 1
    assert await count(migrated_engine, "incident_world_states", incident_id=incident_key) == 1
    assert await count(migrated_engine, "incident_caller_beliefs", incident_id=incident_key) == 1
    assert await count(migrated_engine, "incident_cards", incident_id=incident_key) == 1
    assert await count(migrated_engine, "handoff_snapshots", incident_id=incident_key) == 0

    # The scenario version is locked by this creation, in the same transaction (D4).
    assert await locked_at(migrated_engine, demo_version_id) is not None

    rows = await _events(migrated_engine, session_key)
    assert [(row["seq_no"], row["event_type"]) for row in rows] == [(1, "SESSION_CREATED")]
    assert [envelope.event_type for envelope in publisher.envelopes_for(session.id)] == [
        EventType.SESSION_CREATED
    ]


async def test_time_scale_is_persisted_and_recorded_in_the_payload(
    create_session: CreateSession,
    demo_version_id: ScenarioVersionId,
    instructor: ActorRef,
    users: dict[str, UserId],
    migrated_engine: AsyncEngine,
) -> None:
    session = await create_session(
        command(demo_version_id, instructor, users["trainee1"], time_scale=2.5)
    )
    assert session.time_scale == 2.5

    stored = await scalar(
        migrated_engine,
        "SELECT time_scale FROM simulation_sessions WHERE id = :id",
        id=UUID(str(session.id)),
    )
    assert float(stored) == 2.5

    rows = await _events(migrated_engine, UUID(str(session.id)))
    assert rows[0]["payload"]["time_scale"] == 2.5


async def test_the_empty_card_and_the_two_instantiated_layers(
    create_session: CreateSession,
    demo_version_id: ScenarioVersionId,
    instructor: ActorRef,
    users: dict[str, UserId],
    migrated_engine: AsyncEngine,
) -> None:
    """D3 / SPEC §5: the world knows the fire started in the kitchen; the caller does not."""
    session = await create_session(command(demo_version_id, instructor, users["trainee1"]))
    incident_key = UUID(str(session.incident.incident_id))

    world = await scalar(
        migrated_engine,
        "SELECT facts FROM incident_world_states WHERE incident_id = :id",
        id=incident_key,
    )
    assert world["incident.fire_source"] == "KITCHEN"

    belief_row = await scalar(
        migrated_engine,
        "SELECT to_jsonb(t) FROM incident_caller_beliefs t WHERE incident_id = :id",
        id=incident_key,
    )
    assert "KITCHEN" not in json.dumps(belief_row, ensure_ascii=False)

    card_values = await scalar(
        migrated_engine,
        "SELECT values FROM incident_cards WHERE incident_id = :id",
        id=incident_key,
    )
    assert card_values == {}


async def test_round_trip_equals_the_returned_aggregate(
    create_session: CreateSession,
    unit_of_work: Callable[..., Any],
    demo_version_id: ScenarioVersionId,
    instructor: ActorRef,
    users: dict[str, UserId],
) -> None:
    created = await create_session(command(demo_version_id, instructor, users["trainee1"]))
    async with unit_of_work() as uow:
        loaded = await uow.sessions.get(created.id)
    assert loaded == created


async def test_participants_get_a_stable_generated_id(
    create_session: CreateSession,
    demo_version_id: ScenarioVersionId,
    instructor: ActorRef,
    users: dict[str, UserId],
    ids: SequentialIdGenerator,
    migrated_engine: AsyncEngine,
) -> None:
    """E5-B ruling R3: the use case allocates `participant_id`, so every row has a stable id."""
    session = await create_session(command(demo_version_id, instructor, users["trainee1"]))
    participant = session.participants[0]
    assert participant.participant_id is not None
    assert participant.participant_id in ids.issued

    stored_id = await scalar(
        migrated_engine,
        "SELECT id FROM session_participants WHERE session_id = :id",
        id=UUID(str(session.id)),
    )
    assert UUID(str(stored_id)) == participant.participant_id


# ---------------------------------------------------------------------------------------------
# Every rejection leaves nothing behind
# ---------------------------------------------------------------------------------------------


async def _assert_nothing_written(
    engine: AsyncEngine, scenario_version_id: ScenarioVersionId | None
) -> None:
    assert await count(engine, "simulation_sessions") == 0
    assert await count(engine, "incidents") == 0
    assert await count(engine, "role_stages") == 0
    assert await count(engine, "session_participants") == 0
    assert await count(engine, "incident_world_states") == 0
    assert await count(engine, "incident_caller_beliefs") == 0
    assert await count(engine, "incident_cards") == 0
    assert await count(engine, "session_events") == 0
    if scenario_version_id is not None:
        assert await locked_at(engine, scenario_version_id) is None


async def test_unknown_scenario_version_is_a_404_and_writes_nothing(
    create_session: CreateSession,
    instructor: ActorRef,
    users: dict[str, UserId],
    migrated_engine: AsyncEngine,
) -> None:
    missing = ScenarioVersionId(UUID("00000000-0000-4000-8000-0000000000ff"))
    with pytest.raises(ScenarioVersionNotFoundError):
        await create_session(command(missing, instructor, users["trainee1"]))
    assert ScenarioVersionNotFoundError.code == "NOT_FOUND"
    await _assert_nothing_written(migrated_engine, None)


async def test_role_chain_length_rejection_writes_nothing(
    create_session: CreateSession,
    demo_version_id: ScenarioVersionId,
    instructor: ActorRef,
    users: dict[str, UserId],
    migrated_engine: AsyncEngine,
) -> None:
    """`SINGLE_ROLE` is `EXACTLY_ONE`; the demo chain has two entries (§10.10)."""
    with pytest.raises(RoleChainLengthError):
        await create_session(
            command(
                demo_version_id,
                instructor,
                users["trainee1"],
                session_mode=SessionMode.SINGLE_ROLE,
            )
        )
    await _assert_nothing_written(migrated_engine, demo_version_id)


async def test_prefab_handoff_rejection_writes_nothing(
    create_session: CreateSession,
    raw_version: Callable[..., Any],
    instructor: ActorRef,
    users: dict[str, UserId],
    migrated_engine: AsyncEngine,
) -> None:
    """`[DDS]` under `SINGLE_ROLE` with no `expected_response.prefab_handoff` (D6, §10.10)."""
    version_id = await raw_version("dds-only", role_chain=[RoleType.DDS], with_prefab_handoff=False)
    with pytest.raises(PrefabHandoffRequiredError):
        await create_session(
            command(version_id, instructor, users["trainee1"], session_mode=SessionMode.SINGLE_ROLE)
        )
    await _assert_nothing_written(migrated_engine, version_id)


async def test_edds_in_the_role_chain_is_rejected_at_session_creation(
    create_session: CreateSession,
    raw_version: Callable[..., Any],
    instructor: ActorRef,
    users: dict[str, UserId],
    migrated_engine: AsyncEngine,
) -> None:
    """D6: `EDDSModule.implemented` is False, so `validate_scenario_version` reports the chain
    invalid and `CREATED --validate--> READY` is denied. The version was inserted raw, bypassing
    the importer, so the rejection under test is this one and not an import-time one."""
    version_id = await raw_version("edds-chain", role_chain=[RoleType.OPERATOR_112, RoleType.EDDS])
    with pytest.raises(InvalidTransitionError) as excinfo:
        await create_session(
            command(
                version_id,
                instructor,
                users["trainee1"],
                session_mode=SessionMode.FULL_CYCLE_SINGLE_TRAINEE,
            )
        )
    assert excinfo.value.trigger == "validate"
    await _assert_nothing_written(migrated_engine, version_id)


async def test_an_unsatisfiable_participant_set_is_rejected_by_validate(
    create_session: CreateSession,
    demo_version_id: ScenarioVersionId,
    instructor: ActorRef,
    users: dict[str, UserId],
    migrated_engine: AsyncEngine,
) -> None:
    """`ALL_STAGES_ONE_PARTICIPANT` needs exactly one participant (§10.10)."""
    with pytest.raises(InvalidTransitionError):
        await create_session(
            CreateSessionCommand(
                scenario_version_id=demo_version_id,
                session_mode=SessionMode.FULL_CYCLE_SINGLE_TRAINEE,
                actor=instructor,
                participants=((users["trainee1"], None), (users["trainee2"], None)),
            )
        )
    await _assert_nothing_written(migrated_engine, demo_version_id)


# ---------------------------------------------------------------------------------------------


async def _events(engine: AsyncEngine, session_key: UUID) -> list[dict[str, Any]]:
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT seq_no, event_type, payload FROM session_events"
                " WHERE session_id = :id ORDER BY seq_no"
            ),
            {"id": session_key},
        )
        return [dict(row._mapping) for row in result.all()]
