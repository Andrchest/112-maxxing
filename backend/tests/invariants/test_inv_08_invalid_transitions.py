"""SPEC §42 invariant test 8: "Invalid state-machine transitions fail."

Table-driven and exhaustive: for each of the four SPEC §7 / §10.7 machines (`SESSION_TRANSITIONS`,
`OPERATOR_112_TRANSITIONS`, `DDS_TRANSITIONS`, `RESOURCE_STATUS_TRANSITIONS`) — and I3 E4a's
`LESSON_TRANSITIONS` (HLD 70 §70.3.2) and I3 E5a's `SERVICE_RESPONSE_TRANSITIONS` (HLD 70
§70.4.2) — every `(state,
trigger)` pair is tried. The set of states comes from the matching enum (`list(SessionState)`,
etc.); the set of triggers comes from the table itself (`{trigger for (_, trigger) in table}`) —
neither is retyped here. A pair present in the table must succeed (`fire` returns the row's
`target`, given an actor/role that row's `allowed_actors`/`allowed_roles` permits and a fully
permissive guard registry — guard *callables* are a later slice, see `common/state_machine.py`);
a pair absent from the table must raise `InvalidTransitionError` and leave the caller's `state`
value unchanged.

The guard registry here is deliberately permissive (every `guard_name` the table references maps
to `lambda ctx: True`): this file tests the *tables* — the row is or is not covered — not guard
*business logic*, which needs `SimulationSession`/`RoleStage`/`OperatorCard`/`DDSAssignment` data
and is covered where those guards live (`tests/unit/domain/session/test_guards.py` against
`app/domain/session/guards.py`).

A second exhaustive-adjacent test below (`test_pinned_*`) pins a handful of transitions SPEC §7 /
the HLD tables make illegal, so a future accidental widening of a table is caught even if the
full cross-product test above is ever narrowed. Per this task's brief, both were run by hand with
a row temporarily added to `SESSION_TRANSITIONS` that would legalise the first pinned case (the
pinned test failed), then removed again (the pinned test passed) — see the task report.
"""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID

import pytest
from app.application.sessions import AbortSession, CreateSession, StartSession
from app.application.testing.fakes import FakeClock, FakeInferenceReadiness
from app.domain.common.actors import ActorRef as SessionActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import ScenarioVersionId, SessionId, UserId
from app.domain.common.state_machine import (
    ActorRef,
    GuardContext,
    StateMachine,
    Transition,
    TransitionTable,
)
from app.domain.dds.resources import RESOURCE_STATUS_TRANSITIONS
from app.domain.dds.response import (
    SERVICE_RESPONSE_MACHINE,
    SERVICE_RESPONSE_TRANSITIONS,
    LegGuardSubject,
    ServiceResponseStatus,
)
from app.domain.enums import (
    ActorType,
    DDSStageState,
    Operator112StageState,
    ResourceStatus,
    RoleType,
    SessionState,
)
from app.domain.lesson.lesson import LESSON_TRANSITIONS, LessonState
from app.domain.roles.dds import DDSModule
from app.domain.routing.catalog import StatusPolicy
from app.domain.session.session import SimulationSession
from app.domain.session.transitions import (
    DDS_TRANSITIONS,
    MEMO_DDS_TRANSITIONS,
    OPERATOR_112_TRANSITIONS,
    SESSION_TRANSITIONS,
)
from app.domain.session.variants import DdsMode
from app.infrastructure.ids import Uuid4Generator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.sessions.test_create_session import command

# ---------------------------------------------------------------------------------------------
# Shared machinery
# ---------------------------------------------------------------------------------------------


def _permissive_guards(table: TransitionTable[Any]) -> dict[str, Callable[[GuardContext], bool]]:
    names = {row.guard_name for row in table.values() if row.guard_name is not None}
    return dict.fromkeys(names, lambda _ctx: True)


def _actor_and_role_for(transition: Transition[Any]) -> tuple[ActorType, RoleType | None]:
    """Pick one `(actor_type, role_type)` this row's `allowed_actors`/`allowed_roles` permits."""
    if ActorType.TRAINEE in transition.allowed_actors:
        role = next(iter(transition.allowed_roles)) if transition.allowed_roles else None
        return ActorType.TRAINEE, role
    return next(iter(transition.allowed_actors)), None


def _assert_exhaustive(machine_name: str, table: TransitionTable[Any], states: list[Any]) -> None:
    machine: StateMachine[Any] = StateMachine(table, _permissive_guards(table))
    triggers = sorted({trigger for (_source, trigger) in table})
    assert triggers, f"{machine_name}: table has no rows at all"

    for state, trigger in itertools.product(states, triggers):
        key = (state, trigger)
        before = state
        if key in table:
            transition = table[key]
            actor_type, role_type = _actor_and_role_for(transition)
            ctx = GuardContext(actor=ActorRef(actor_type=actor_type), role_type=role_type)
            result = machine.fire(state, trigger, ctx)
            assert result == transition.target, (
                f"{machine_name}: {state!r} -{trigger}-> expected {transition.target!r}, "
                f"got {result!r}"
            )
        else:
            ctx = GuardContext(actor=ActorRef(actor_type=ActorType.SYSTEM))
            with pytest.raises(InvalidTransitionError):
                machine.fire(state, trigger, ctx)
            assert state == before, f"{machine_name}: {state!r} mutated by a rejected {trigger!r}"


# ---------------------------------------------------------------------------------------------
# Exhaustive per-machine tests
# ---------------------------------------------------------------------------------------------


def test_session_transitions_exhaustive() -> None:
    _assert_exhaustive("SESSION_TRANSITIONS", SESSION_TRANSITIONS, list(SessionState))


def test_operator_112_transitions_exhaustive() -> None:
    _assert_exhaustive(
        "OPERATOR_112_TRANSITIONS", OPERATOR_112_TRANSITIONS, list(Operator112StageState)
    )


def test_dds_transitions_exhaustive() -> None:
    _assert_exhaustive("DDS_TRANSITIONS", DDS_TRANSITIONS, list(DDSStageState))


def test_resource_status_transitions_exhaustive() -> None:
    _assert_exhaustive(
        "RESOURCE_STATUS_TRANSITIONS", RESOURCE_STATUS_TRANSITIONS, list(ResourceStatus)
    )


def test_lesson_transitions_exhaustive() -> None:
    """I3 E4a (HLD 70 §70.3.2): `LESSON_TRANSITIONS` joins the table-driven expectations."""
    _assert_exhaustive("LESSON_TRANSITIONS", LESSON_TRANSITIONS, list(LessonState))


def test_service_response_transitions_exhaustive() -> None:
    """I3 E5a (HLD 70 §70.4.2): every non-listed leg transition fails."""
    _assert_exhaustive(
        "SERVICE_RESPONSE_TRANSITIONS", SERVICE_RESPONSE_TRANSITIONS, list(ServiceResponseStatus)
    )


def test_memo_dds_transitions_exhaustive() -> None:
    """I3 E5a (HLD 70 §70.4.4): the memo view of `DDS_TRANSITIONS`, cross-product like the rest."""
    _assert_exhaustive("MEMO_DDS_TRANSITIONS", MEMO_DDS_TRANSITIONS, list(DDSStageState))


# ---------------------------------------------------------------------------------------------
# I3 E5a: the leg machine skips nothing, and the memo stage has no resource trigger
# ---------------------------------------------------------------------------------------------

_S = ServiceResponseStatus
_ORDER = (_S.RECEIVED, _S.ACCEPTED, _S.RESPONSE_STARTED, _S.ARRIVED, _S.WORKING, _S.COMPLETED)


@pytest.mark.parametrize(
    "source,target",
    [(source, target) for index, source in enumerate(_ORDER) for target in _ORDER[index + 2 :]]
    + [
        (_S.ADDED, _S.ACCEPTED),
        (_S.ADDED, _S.NOT_ACCEPTED),
        (_S.NOT_ACCEPTED, _S.RESPONSE_STARTED),
    ],
    ids=lambda value: value.value,
)
def test_skipping_a_leg_status_fails(source: ServiceResponseStatus, target: Any) -> None:
    """A-8: no trigger of `SERVICE_RESPONSE_TRANSITIONS` jumps over a status, whoever fires it
    and whatever the policy (`complete_without_brigade` is the one documented shortcut, 103 only,
    and it is refused here under `DEFAULT`)."""
    shortcuts = [
        trigger
        for (state, trigger), row in SERVICE_RESPONSE_TRANSITIONS.items()
        if state is source and row.target is target
    ]
    assert set(shortcuts) <= {"complete_without_brigade"}, (source, target, shortcuts)
    triggers = sorted({trigger for (_state, trigger) in SERVICE_RESPONSE_TRANSITIONS})
    ctx = GuardContext(
        actor=ActorRef(actor_type=ActorType.TRAINEE),
        role_type=RoleType.DDS,
        assignment=LegGuardSubject(status_policy=StatusPolicy.DEFAULT, comment_ru="x"),
    )
    for trigger in triggers:
        try:
            reached = SERVICE_RESPONSE_MACHINE.fire(source, trigger, ctx)
        except InvalidTransitionError:
            continue
        assert reached is not target, f"{source.value} -{trigger}-> {target.value} skips a step"


def test_the_leg_machine_refuses_every_trigger_from_a_terminal_status() -> None:
    triggers = sorted({trigger for (_state, trigger) in SERVICE_RESPONSE_TRANSITIONS})
    for terminal in (_S.COMPLETED, _S.REFUSED):
        for trigger in triggers:
            assert (terminal, trigger) not in SERVICE_RESPONSE_TRANSITIONS


_RESOURCE_TRIGGERS = (
    "open_resource_selection",
    "dispatch",
    "back_to_acknowledged",
    "first_en_route",
    "first_arrived",
    "work_started",
    "incident_resolved",
    "dispatch_additional",
)


@pytest.mark.parametrize("trigger", _RESOURCE_TRIGGERS)
def test_every_resource_trigger_is_rejected_in_memo_mode(trigger: str) -> None:
    """HLD 70 §70.4.4: `RESOURCE_SELECTION` … `WORKING` are never entered in memo mode — every
    resource trigger is "no such transition" on the memo machine, from every state, even with an
    actor the picker row would allow and every guard permissive."""
    machine: StateMachine[Any] = StateMachine(
        MEMO_DDS_TRANSITIONS, _permissive_guards(DDS_TRANSITIONS)
    )
    for state in DDSStageState:
        for actor_type in (ActorType.TRAINEE, ActorType.SIMULATION):
            ctx = GuardContext(actor=ActorRef(actor_type=actor_type), role_type=RoleType.DDS)
            with pytest.raises(InvalidTransitionError):
                machine.fire(state, trigger, ctx)


def test_the_memo_module_machine_is_the_memo_view() -> None:
    module = DDSModule()
    memo = b_variants(DdsMode.MEMO_STATUSES)
    picker = b_variants(DdsMode.RESOURCE_PICKER)
    assert module.state_machine_for(memo) is module.memo_state_machine
    assert module.state_machine_for(picker) is module.state_machine
    assert module.state_machine_for(None) is module.state_machine
    assert module.memo_state_machine._table is MEMO_DDS_TRANSITIONS


def b_variants(mode: DdsMode) -> Any:
    from app.domain.session.variants import (
        CardSource,
        DdsBrigadeCall,
        DdsCardCheck,
        SessionVariants,
    )

    return SessionVariants(
        card_source=CardSource.GENERATED_CARD,
        dds_mode=mode,
        dds_card_check=DdsCardCheck.OFF,
        dds_brigade_call=DdsBrigadeCall.OFF,
    )


# ---------------------------------------------------------------------------------------------
# Pinned illegal transitions (SPEC §7 / the HLD tables make these illegal by omission)
# ---------------------------------------------------------------------------------------------

_PINNED_ILLEGAL: tuple[tuple[str, TransitionTable[Any], Any, str], ...] = (
    ("SESSION_TRANSITIONS", SESSION_TRANSITIONS, SessionState.CREATED, "complete"),
    ("SESSION_TRANSITIONS", SESSION_TRANSITIONS, SessionState.COMPLETED, "start"),
    (
        "OPERATOR_112_TRANSITIONS",
        OPERATOR_112_TRANSITIONS,
        Operator112StageState.WAITING_FOR_CALL,
        "create_handoff",
    ),
    ("DDS_TRANSITIONS", DDS_TRANSITIONS, DDSStageState.RECEIVED, "dispatch"),
    ("MEMO_DDS_TRANSITIONS", MEMO_DDS_TRANSITIONS, DDSStageState.ACKNOWLEDGED, "dispatch"),
    (
        "MEMO_DDS_TRANSITIONS",
        MEMO_DDS_TRANSITIONS,
        DDSStageState.ACKNOWLEDGED,
        "open_resource_selection",
    ),
    (
        "SERVICE_RESPONSE_TRANSITIONS",
        SERVICE_RESPONSE_TRANSITIONS,
        ServiceResponseStatus.ACCEPTED,
        "arrive",
    ),
    (
        "SERVICE_RESPONSE_TRANSITIONS",
        SERVICE_RESPONSE_TRANSITIONS,
        ServiceResponseStatus.ADDED,
        "accept",
    ),
    ("LESSON_TRANSITIONS", LESSON_TRANSITIONS, LessonState.COMPLETED, "abort"),
    ("LESSON_TRANSITIONS", LESSON_TRANSITIONS, LessonState.CREATED, "complete"),
    ("LESSON_TRANSITIONS", LESSON_TRANSITIONS, LessonState.ABORTED, "start"),
)


@pytest.mark.parametrize(
    "machine_name,table,state,trigger",
    _PINNED_ILLEGAL,
    ids=[row[0] + ":" + row[3] for row in _PINNED_ILLEGAL],
)
def test_pinned_illegal_transitions_raise(
    machine_name: str, table: TransitionTable[Any], state: Any, trigger: str
) -> None:
    machine: StateMachine[Any] = StateMachine(table, _permissive_guards(table))
    ctx = GuardContext(actor=ActorRef(actor_type=ActorType.SYSTEM))
    with pytest.raises(InvalidTransitionError) as excinfo:
        machine.fire(state, trigger, ctx)
    assert excinfo.value.trigger == trigger
    assert (state, trigger) not in table, (
        f"{machine_name}: {state!r} -{trigger}-> is in the table — "
        "this pinned case is no longer illegal"
    )


# ---------------------------------------------------------------------------------------------
# The same invariant through the E5 use cases (SPEC §42 item 8, E5 acceptance row)
# ---------------------------------------------------------------------------------------------
#
# The tests above prove the *tables* reject what they do not list. These prove the property that
# actually protects the database: an invalid command reaching a real use case, over real
# PostgreSQL, raises `InvalidTransitionError` and appends **no** event — the `session_events` row
# count is identical before and after every rejected command.

# The session-lifecycle fixtures live in `tests/integration/sessions/conftest.py`; they are
# re-exported here by name rather than through `pytest_plugins`, which cannot register a module
# that is already loaded as a real conftest. `clean_database` is deliberately NOT re-exported —
# it is autouse over there, and the four table-driven tests above must stay database-free; the
# local `clean_sessions_db` below is its explicitly requested twin.
from tests.integration.sessions import conftest as _session_fixtures  # noqa: E402

abort_session = _session_fixtures.abort_session
clock = _session_fixtures.clock
create_session = _session_fixtures.create_session
demo_version_id = _session_fixtures.demo_version_id
ids = _session_fixtures.ids
inference = _session_fixtures.inference
instructor = _session_fixtures.instructor
publisher = _session_fixtures.publisher
session_factory = _session_fixtures.session_factory
start_session = _session_fixtures.start_session
trainee = _session_fixtures.trainee
unit_of_work = _session_fixtures.unit_of_work
users = _session_fixtures.users


@pytest.fixture
async def clean_sessions_db(migrated_engine: AsyncEngine) -> AsyncIterator[None]:
    """Empty the schema before and after one test (the non-autouse twin of `clean_database`)."""
    statement = text("TRUNCATE TABLE users, scenarios RESTART IDENTITY CASCADE")
    async with migrated_engine.begin() as connection:
        await connection.execute(statement)
    yield
    async with migrated_engine.begin() as connection:
        await connection.execute(statement)


async def _event_count(engine: AsyncEngine, session_id: SessionId) -> int:
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT count(*) FROM session_events WHERE session_id = :id"),
            {"id": UUID(str(session_id))},
        )
        return int(result.scalar_one())


@pytest.fixture
async def active_session(
    clean_sessions_db: None,
    create_session: CreateSession,
    start_session: StartSession,
    demo_version_id: ScenarioVersionId,
    instructor: SessionActorRef,
    users: dict[str, UserId],
) -> SimulationSession:
    """One `ACTIVE` session: created, then started."""
    created = await create_session(command(demo_version_id, instructor, users["trainee1"]))
    return await start_session(created.id, instructor)


@pytest.mark.integration
async def test_starting_an_already_active_session_appends_nothing(
    start_session: StartSession,
    active_session: SimulationSession,
    instructor: SessionActorRef,
    migrated_engine: AsyncEngine,
) -> None:
    before = await _event_count(migrated_engine, active_session.id)
    with pytest.raises(InvalidTransitionError) as excinfo:
        await start_session(active_session.id, instructor)
    assert excinfo.value.trigger == "start"
    assert excinfo.value.from_state == SessionState.ACTIVE.value
    assert await _event_count(migrated_engine, active_session.id) == before


@pytest.mark.integration
async def test_starting_an_aborted_session_appends_nothing(
    start_session: StartSession,
    abort_session: AbortSession,
    active_session: SimulationSession,
    instructor: SessionActorRef,
    migrated_engine: AsyncEngine,
) -> None:
    await abort_session(active_session.id, instructor, "прервано")
    before = await _event_count(migrated_engine, active_session.id)

    with pytest.raises(InvalidTransitionError):
        await start_session(active_session.id, instructor)
    assert await _event_count(migrated_engine, active_session.id) == before


@pytest.mark.integration
async def test_a_trainee_may_not_start_a_session(
    clean_sessions_db: None,
    unit_of_work: Callable[..., object],
    clock: FakeClock,
    create_session: CreateSession,
    demo_version_id: ScenarioVersionId,
    instructor: SessionActorRef,
    trainee: SessionActorRef,
    migrated_engine: AsyncEngine,
    users: dict[str, UserId],
) -> None:
    """`READY --start--> ACTIVE` is `allowed_actors={INSTRUCTOR}` (§10.8)."""
    ready = await create_session(command(demo_version_id, instructor, users["trainee1"]))
    before = await _event_count(migrated_engine, ready.id)

    use_case = StartSession(
        unit_of_work,  # type: ignore[arg-type]
        clock,
        FakeInferenceReadiness(ready=True),
        Uuid4Generator(),
        require_inference_ready=False,
    )
    with pytest.raises(InvalidTransitionError) as excinfo:
        await use_case(ready.id, trainee)

    assert excinfo.value.trigger == "start"
    assert await _event_count(migrated_engine, ready.id) == before
    async with unit_of_work() as uow:  # type: ignore[operator]
        reloaded = await uow.sessions.get(ready.id)
    assert reloaded is not None and reloaded.state is SessionState.READY


@pytest.mark.integration
async def test_aborting_twice_appends_nothing_the_second_time(
    abort_session: AbortSession,
    active_session: SimulationSession,
    instructor: SessionActorRef,
    migrated_engine: AsyncEngine,
) -> None:
    await abort_session(active_session.id, instructor, "первый раз")
    before = await _event_count(migrated_engine, active_session.id)

    with pytest.raises(InvalidTransitionError) as excinfo:
        await abort_session(active_session.id, instructor, "второй раз")
    assert excinfo.value.trigger == "abort"
    assert await _event_count(migrated_engine, active_session.id) == before
