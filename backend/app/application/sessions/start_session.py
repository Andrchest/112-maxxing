"""`StartSession` — `READY --start--> ACTIVE` (E5, §10.8, D5, D8).

One Unit of Work transaction: take the `SELECT … FOR UPDATE` row lock through `get_for_update`,
project the `GuardRuntime` from the session's event log, fire `start` on the aggregate, write the
new aggregate back and append the events the transition produced (`SESSION_STARTED`, then
`ROLE_STAGE_STARTED` for the first stage).

`require_inference_ready` (D8) reaches this use case as a **constructor argument**: the
application layer never imports `app.config`, so the composition root reads `Settings` and passes
the flag in. When it is false the readiness port is not even consulted — that is what D8's "the
application collapses both into the flag" means, and it is why a dev box without an inference
stack can still run a session.

An illegal `start` (wrong state, wrong actor) raises `InvalidTransitionError` *before* anything
is written, and the transaction is never committed: no state change, no event. A stack that is
merely not warm yet raises `InferenceNotReadyError` instead — see that class for why the two are
deliberately different answers.

One thing happens here that `start` itself does not describe: when the session's **first** stage
is the DDS one — a `role_chain` of `[DDS]` under `SINGLE_ROLE` / `ASSESSMENT` (D6) — there is no
112 stage to produce the `HandoffSnapshot` that stage exists to work on, so the scenario's
`expected_response.prefab_handoff` is materialised in this same transaction, right after
`ROLE_STAGE_STARTED`. See `app.application.handoff.prefab_handoff` for what that writes and why
it emits `HANDOFF_RECEIVED` but no `HANDOFF_CREATED`. A chain that starts at `OPERATOR_112` is
untouched by this: its handoff is the trainee's to make.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.application.handoff.prefab_handoff import materialise_prefab_handoff
from app.application.ports.clock import Clock
from app.application.ports.id_generator import IdGenerator
from app.application.ports.inference_readiness import InferenceReadiness
from app.application.ports.reference import ReferencePort
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.reference.queries import reference_catalog
from app.application.sessions.guard_context import build_guard_runtime
from app.domain.common.actors import ActorRef
from app.domain.common.errors import DomainError
from app.domain.common.ids import SessionId
from app.domain.enums import RoleType
from app.domain.events.session_event import DomainEvent
from app.domain.scenario.version import ScenarioVersion
from app.domain.session.session import SimulationSession

__all__ = ["InferenceNotReadyError", "SessionNotFoundError", "StartSession"]


class InferenceNotReadyError(DomainError):
    """A required inference service is not `READY` (`openapi.yaml`, `503 INFERENCE_NOT_READY`).

    This is raised **instead of** letting `guard_inference_ready` deny the transition. Both
    outcomes are "the session does not start", but they are not the same answer to a client:
    `openapi.yaml` gives `startSession` a dedicated `503` whose meaning is "come back when the
    stack is warm" (SPEC §37), while `409 INVALID_TRANSITION` means "this session can never be
    started from the state it is in". Collapsing the two would make the UI's start button
    permanently disabled-looking for a transient condition.

    Nothing is written when it is raised: the check runs before the trigger fires.
    """

    code = "INFERENCE_NOT_READY"

    def __init__(self, session_id: SessionId) -> None:
        self.session_id = session_id
        super().__init__(
            "a required inference service is not READY and REQUIRE_INFERENCE_READY is true"
        )


class SessionNotFoundError(DomainError):
    """No `simulation_sessions` row with the requested id (`openapi.yaml`, `404 NOT_FOUND`)."""

    code = "NOT_FOUND"

    def __init__(self, session_id: SessionId) -> None:
        self.session_id = session_id
        super().__init__(f"no session {session_id}")


class StartSession:
    """Start a session that is `READY`."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        inference: InferenceReadiness,
        ids: IdGenerator,
        *,
        require_inference_ready: bool,
        reference: ReferencePort | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        #: The reference pack: the prefab card is written against the version's card schema
        #: (I3 E3a, HLD 70 §70.5.4 — a schema-2 prefab names v2 paths).
        self._reference = reference
        self._clock = clock
        self._inference = inference
        #: The prefab handoff's card-revision ids; the domain owns no randomness (D2/D7).
        self._ids = ids
        #: D8's `REQUIRE_INFERENCE_READY`, injected — never read from `app.config` here.
        self._require_inference_ready = require_inference_ready

    async def __call__(
        self,
        session_id: SessionId,
        actor: ActorRef,
        *,
        lesson_arrival: Mapping[str, Any] | None = None,
    ) -> SimulationSession:
        """Fire `start`; returns the `ACTIVE` aggregate or raises `InvalidTransitionError`.

        `lesson_arrival` (`{kind, due_offset_ms, fired_offset_ms}`, lesson wall ms) is passed by
        the `LessonRunner` when it starts a lesson card (HLD 70 §70.3.3) and recorded in
        `SESSION_STARTED.lesson_arrival`.
        """
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get_for_update(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)

            if not await self._inference_ready():
                raise InferenceNotReadyError(session_id)

            runtime = build_guard_runtime(
                await uow.events.read(session_id), scenario_valid=True, inference_ready=True
            )
            # `now_ms=0`: the start *is* the origin every later offset is measured from
            # (`session_offset_ms(now, started_at)` with `now == started_at`), so it is written
            # literally here rather than read from a counter — SPEC §39, D7.
            started, events = session.start(
                self._clock.now(),
                actor=actor,
                now_ms=0,
                runtime=runtime,
                lesson_arrival=lesson_arrival,
            )

            await uow.sessions.save(started)
            await uow.events.append(session_id, [*events, *await self._prefab(uow, started)])
            await uow.commit()
        return started

    # -- internals ----------------------------------------------------------------------------

    async def _prefab(self, uow: UnitOfWork, started: SimulationSession) -> list[DomainEvent]:
        """The prefab handoff's events, or nothing at all for a chain that starts at 112.

        `create_session` already refused a DDS-first scenario without a prefab
        (`PrefabHandoffRequiredError`), so the absent-prefab branch is unreachable through the
        API; it returns nothing rather than raising, because a session that is already `ACTIVE`
        must not be undone by a scenario defect this use case did not cause.
        """
        stage = started.current_stage
        if stage is None or stage.role_type is not RoleType.DDS:
            return []
        document = await uow.scenarios.get_version_document(started.scenario_version_id)
        if document is None:  # pragma: no cover - the session exists, so its version does
            return []
        version = ScenarioVersion.model_validate(dict(document))
        prefab = version.expected_response.prefab_handoff
        if prefab is None:  # pragma: no cover - refused at session creation (D6)
            return []
        card_schema = reference_catalog(self._reference).card_schema(version.reference_pack_id)
        # `now_ms=0`: the start is the origin every offset is measured from, and the prefab
        # handoff is handed to DDS at the instant the stage opens.
        return await materialise_prefab_handoff(
            uow,
            started,
            prefab,
            stage.role_stage_id,
            ids=self._ids,
            now_ms=0,
            card_schema=card_schema,
        )

    async def _inference_ready(self) -> bool:
        """`REQUIRE_INFERENCE_READY is false` **or** every component reports `READY` (D8)."""
        if not self._require_inference_ready:
            return True
        return await self._inference.is_ready()
