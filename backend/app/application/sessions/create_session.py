"""`CreateSession` — one session, one incident, N role stages, three layer rows (E5, D3, D5, D6).

Everything below happens in **one** Unit of Work transaction (D5), in this order:

1. read the `scenario_versions` row by id — absent means `ScenarioVersionNotFoundError`
   (`404 NOT_FOUND`);
2. turn its stored `content` back into a `ScenarioVersion`, look up the reference pack it names
   (`legacy-r1` when none; an unknown pack is `409 REFERENCE_PACK_UNKNOWN`, HLD 70 §70.6.1 — its
   ids and sha256 become `SESSION_CREATED.reference_pack`) and re-run `validate_scenario_version`
   on it against that catalog (rules R37/R38). The verdict is a *boolean* carried into
   `GuardRuntime.scenario_valid`, not an exception: §10.8 makes "the scenario version passed
   validation" a guard on `CREATED --validate--> READY`, so an invalid version is rejected as an
   `InvalidTransitionError` on the session machine — which is also how a `role_chain` naming an
   unimplemented `RoleModule` (`EDDS`, D6) is refused here rather than at import time;
3. resolve the requested variants against the version (`resolve_variants`, HLD 70 §70.2.2:
   request → scenario default; `409 VARIANT_NOT_AVAILABLE` before `409 VARIANT_NOT_SUPPORTED`),
   then build the aggregate with `app.domain.session.session.create_session` on the **effective**
   role chain those variants give, every id taken from the `IdGenerator` (the domain owns no
   randomness, D2/D7);
4. fire `validate` as `SYSTEM`;
5. instantiate `WorldTruth` and `CallerBelief` from the version through `layers/copies.py` — the
   only conversion path between the information layers (D3) — plus an **empty** `OperatorCard`;
6. persist the aggregate, the three layer rows, the session's own copy of the scenario's
   `available_resources` (§20.5: "per-session instances […] so that resource state is
   session-scoped and two concurrent sessions never collide") and the zeroed `world_engine_states`
   row the world event engine ticks against (E6, D7);
7. `lock_scenario_version` in the same transaction (D4, SPEC §42 invariant 6);
8. append `SESSION_CREATED` and whatever `validate` emitted, then commit.

Any failure anywhere in that list leaves the database untouched: no session row, no events, and
the scenario version *not* locked. That is the whole reason steps 6-8 share one transaction with
step 7 rather than locking the version up front.

`create_in(uow, command)` is the same work inside a Unit of Work the caller owns (I3 E4a):
`createLesson` creates every card of a lesson through it, in one transaction, so a lesson is either
created with all its sessions or not at all (HLD 70 §70.3.2). A lesson card carries `lesson_id` /
`lesson_position`, recorded in `SESSION_CREATED` and on the session row; `SESSION_CREATED.timers`
records the version's resolved per-card timers (§70.3.4) for every session.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.application.ports.id_generator import IdGenerator
from app.application.ports.reference import ReferencePort
from app.application.ports.resource_repository import StoredResource
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.ports.world_engine_state_repository import WorldEngineState
from app.application.reference.queries import reference_catalog
from app.domain.common.actors import ActorRef
from app.domain.common.errors import DomainError, ScenarioValidationError
from app.domain.common.ids import (
    CardId,
    IncidentId,
    LessonId,
    ResourceId,
    RoleStageId,
    ScenarioVersionId,
    SessionId,
    UserId,
)
from app.domain.common.state_machine import GuardRuntime
from app.domain.dds.resources import EmergencyResource
from app.domain.enums import ActorType, RoleType, SessionMode
from app.domain.events.session_event import DomainEvent
from app.domain.layers.copies import instantiate_caller_belief, instantiate_world_truth
from app.domain.layers.operator_card import OperatorCard
from app.domain.routing.catalog import ReferenceCatalog
from app.domain.scenario.validation import validate_scenario_version
from app.domain.scenario.version import ScenarioVersion
from app.domain.session.session import SimulationSession, create_session
from app.domain.session.variants import PartialVariants, effective_role_chain, resolve_variants

__all__ = [
    "CreateSession",
    "CreateSessionCommand",
    "ReferencePackUnknownError",
    "ScenarioVersionNotFoundError",
]

_SYSTEM = ActorRef(actor_type=ActorType.SYSTEM)
"""`validate` is a `SYSTEM` trigger (§10.8): the engine, not the instructor, decides readiness."""


class ScenarioVersionNotFoundError(DomainError):
    """No `scenario_versions` row with the requested id (`openapi.yaml`, `404 NOT_FOUND`)."""

    code = "NOT_FOUND"

    def __init__(self, scenario_version_id: ScenarioVersionId) -> None:
        self.scenario_version_id = scenario_version_id
        super().__init__(f"no scenario version {scenario_version_id}")


class ReferencePackUnknownError(DomainError):
    """The version names a `reference_pack` the loaded manifest does not have (HLD 70 §70.6.1,
    `409 REFERENCE_PACK_UNKNOWN`): the session could not record which files it runs with."""

    code = "REFERENCE_PACK_UNKNOWN"

    def __init__(self, pack_id: str) -> None:
        self.pack_id = pack_id
        super().__init__(f"reference pack {pack_id!r} is not in reference/manifest.json")


@dataclass(frozen=True)
class CreateSessionCommand:
    """`openapi.yaml`'s `SessionCreateRequest` plus the authenticated actor.

    `participants` is `(user_id, assigned_role_type)` in request order; `None` as a role is legal
    only where the mode's `assignment_rule` is `ALL_STAGES_ONE_PARTICIPANT` — and that is checked
    by the `validate` guard, not here.
    """

    scenario_version_id: ScenarioVersionId
    session_mode: SessionMode
    actor: ActorRef
    participants: Sequence[tuple[UserId, RoleType | None]] = field(default_factory=tuple)
    session_seed: str | None = None
    time_scale: float = 1.0
    variants: PartialVariants = field(default_factory=PartialVariants)
    """`SessionCreateRequest.variants` — every switch optional (HLD 70 §70.2.2)."""
    lesson_id: LessonId | None = None
    """The lesson this session is a card of (HLD 70 §70.3.2); set only by `createLesson`."""
    lesson_position: int | None = None
    """The card's plan position; set exactly when `lesson_id` is."""


class CreateSession:
    """Create one session in one transaction."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        ids: IdGenerator,
        reference: ReferencePort | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._ids = ids
        self._reference = reference

    async def __call__(self, command: CreateSessionCommand) -> SimulationSession:
        """Create the session and return the persisted aggregate (state `READY`)."""
        async with self._unit_of_work() as uow:
            session = await self.create_in(uow, command)
            await uow.commit()
        return session

    async def create_in(self, uow: UnitOfWork, command: CreateSessionCommand) -> SimulationSession:
        """Create the session inside `uow`, which the caller commits (or rolls back)."""
        version, session, events = await self._build(uow, command)
        await self._persist(uow, version, session)
        await uow.scenarios.lock_scenario_version(session.scenario_version_id)
        await uow.events.append(session.id, events)
        return session

    # -- steps --------------------------------------------------------------------------------

    async def _build(
        self, uow: UnitOfWork, command: CreateSessionCommand
    ) -> tuple[ScenarioVersion, SimulationSession, list[DomainEvent]]:
        version, scenario_slug = await self._load_version(uow, command.scenario_version_id)
        reference = reference_catalog(self._reference)
        reference_pack = reference.record(version.reference_pack_id)
        if reference_pack is None:
            raise ReferencePackUnknownError(version.reference_pack_id)
        scenario_valid = _is_valid(version, reference)
        variants = resolve_variants(command.variants, version.scenario_variants)
        chain = effective_role_chain(version.role_chain, variants.card_source)

        participants = tuple(command.participants)
        created, events = create_session(
            session_id=SessionId(self._ids.new()),
            incident_id=IncidentId(self._ids.new()),
            stage_ids=[RoleStageId(self._ids.new()) for _ in chain],
            scenario_version=version,
            scenario_id=version.scenario_id,
            scenario_slug=scenario_slug,
            session_mode=command.session_mode,
            created_by=command.actor,
            participants=participants,
            participant_ids=[self._ids.new() for _ in participants],
            session_seed=command.session_seed,
            time_scale=command.time_scale,
            variants=variants,
            reference_pack=reference_pack,
            lesson_id=command.lesson_id,
            lesson_position=command.lesson_position,
        )
        # `now_ms=0`: nothing before `SESSION_STARTED` has a timeline to be offset against —
        # `session_offset_ms(now, started_at=None)` is `0` — and the offset is never taken from a
        # process-monotonic counter, which a backend restart would invalidate (SPEC §39, D7).
        ready, validate_events = created.validate_session(
            actor=_SYSTEM, now_ms=0, runtime=GuardRuntime(scenario_valid=scenario_valid)
        )
        return version, ready, [*events, *validate_events]

    async def _load_version(
        self, uow: UnitOfWork, scenario_version_id: ScenarioVersionId
    ) -> tuple[ScenarioVersion, str]:
        stored = await uow.scenarios.get_version(scenario_version_id)
        if stored is None:
            raise ScenarioVersionNotFoundError(scenario_version_id)
        document = await uow.scenarios.get_version_document(scenario_version_id)
        if document is None:  # pragma: no cover - the two reads hit the same row
            raise ScenarioVersionNotFoundError(scenario_version_id)
        scenario = await uow.scenarios.get_scenario(stored.scenario_id)
        if scenario is None:
            raise ScenarioVersionNotFoundError(scenario_version_id)
        return _parse(document), scenario.slug

    async def _persist(
        self, uow: UnitOfWork, version: ScenarioVersion, session: SimulationSession
    ) -> None:
        """Write the aggregate, its three starting layer rows, its resources and its engine state.

        Three layer rows, not four: a session starts with no `HandoffSnapshot` — the 112 stage
        produces the first one (SPEC §10), so `uow.handoffs` is deliberately not touched here.

        The resource board and the `world_engine_states` row are instantiated in the *same*
        transaction because a session that exists without them cannot be ticked: the first
        `tick_session` would find no board and no bookkeeping, and there is no second moment at
        which the scenario's `available_resources` could legitimately be copied (§20.5, D7).
        """
        await uow.sessions.add(session)

        incident_id = session.incident.incident_id
        await uow.world_truth.add(instantiate_world_truth(version, incident_id))
        await uow.caller_beliefs.add(instantiate_caller_belief(version, incident_id))
        await uow.operator_cards.add(
            OperatorCard(card_id=CardId(self._ids.new()), incident_id=incident_id, values={})
        )
        await uow.resources.add_all(session.id, self._instantiate_resources(version))
        await uow.world_engine_states.add(WorldEngineState(incident_id=incident_id))

    def _instantiate_resources(self, version: ScenarioVersion) -> list[StoredResource]:
        """The scenario's `available_resources` as this session's own resource instances (§20.5).

        Every runtime id comes from the `IdGenerator` (D2/D7 — the domain owns no randomness), and
        the scenario-local `resource_id` (`"ac2"`) is kept beside the resource: effects and
        selectors name resources by that string, while the board is keyed by the runtime id.
        A resource starts in its scenario-defined `availability.initial_status`.
        """
        return [
            StoredResource(
                scenario_resource_id=spec.resource_id,
                resource=EmergencyResource(
                    resource_id=ResourceId(self._ids.new()),
                    service_type=spec.service_type,
                    resource_type=spec.resource_type,
                    callsign=spec.callsign,
                    name_ru=spec.name_ru,
                    capabilities=frozenset(spec.capabilities),
                    current_status=spec.availability.initial_status,
                    availability=spec.availability,
                    eta=spec.eta,
                    home_station_ru=spec.home_station_ru,
                    crew_size=spec.crew_size,
                    status_changed_at_offset_ms=0,
                ),
            )
            for spec in version.available_resources
        ]


def _parse(document: Mapping[str, Any]) -> ScenarioVersion:
    """The stored document back into the domain type — the one parser (`app.domain.scenario`)."""
    return ScenarioVersion.model_validate(dict(document))


def _is_valid(version: ScenarioVersion, reference: ReferenceCatalog) -> bool:
    """Re-run `validate_scenario_version` and report the verdict as a guard fact (§10.8)."""
    try:
        validate_scenario_version(version, reference=reference)
    except ScenarioValidationError:
        return False
    return True
