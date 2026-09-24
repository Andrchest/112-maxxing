"""`ResponderKnowledge` and `ResponderContextLoader` — everything a service head may know on a ДДС
call (HLD `80-telephony.md` §80.4.2, D24, INV 1/2/3; I3 E6c).

The head of a service is the AI party of a `SERVICE_HEAD` call. What it knows is **the script plus
the snapshot** and nothing else:

* the catalog entry of its service and its persona (reference data);
* the leg's `HandoffSnapshot` values — exactly what the ДДС was sent, the DDS's own layer (D3);
* the leg's script steps that are **due** (`due_scripted_steps`, pure and due-offset stamped; the
  implicit `RECEIVED` left out) and only how many are still pending — never which (INV 2: a
  not-yet-due step is never spoken);
* the leg's status now, its «Номер наряда», and this leg's previous calls (`DDS_CALL_*`) and the
  proposals already spoken on this call.

The loader is constructed with the Unit of Work factory it reads the session, the leg, the
snapshot and the event log through, the clock, the reference pack, and the **script probe** — the
same runner-side `responder_scripts` probe E5b binds for stage automation (INV 3) — and **no
WorldTruth or CallerBelief repository**: it cannot read them because it is never given them (the
constructor-signature test holds that, the INV 3 pattern). Nothing in `ResponderKnowledge` can hold
a world or caller value: its only card values are the snapshot's.

**The first-call checklist (§80.4.2).** On the leg's first answered call the head knows nothing
beyond the snapshot it was sent and asks for what the checklist names: the snapshot's non-empty
`required_for_handoff` paths of the session's card schema (address, what happened, …; the
caller's own number and the recipient list are not the brigade's business). The trainee's answers
are matched to those values by code (`ResponderTemplates`), never by a model.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from app.application.ports.clock import Clock
from app.application.ports.reference import ReferencePort
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.reference.card_schemas import pack_card_schema, session_pack_id
from app.application.reference.queries import reference_catalog
from app.application.simulation.sim_time import running_ms
from app.domain.common.ids import SessionId
from app.domain.common.values import FactValue
from app.domain.dds.assignment import DDSAssignment
from app.domain.dds.call import DdsCallDirection, fold_dds_calls
from app.domain.dds.personas import Persona, resolve_persona
from app.domain.dds.responders import (
    ScriptedResponders,
    ScriptedStep,
    due_scripted_steps,
    persona_override_for,
    script_for,
)
from app.domain.dds.response import ServiceResponseStatus
from app.domain.enums import RoleType, ServiceId
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.layers.card_schema import CardSchema
from app.domain.routing.catalog import ServiceCatalogEntry
from app.domain.session.session import SimulationSession

__all__ = [
    "CHECKLIST_EXCLUDED_PREFIXES",
    "ChecklistItem",
    "DueStep",
    "ResponderContextLoader",
    "ResponderKnowledge",
    "ResponderNotFoundError",
    "ScriptProbe",
    "checklist_of",
]

type ScriptProbe = Callable[[SessionId], Awaitable[ScriptedResponders | None]]
"""`expected_response.responders`, read runner-side (`ScenarioResponderScripts`, INV 3)."""

CHECKLIST_EXCLUDED_PREFIXES: tuple[str, ...] = ("caller.", "recipients.")
"""Required card paths a brigade head does not ask for: the caller's own data and the list."""


class ResponderNotFoundError(LookupError):
    """The call names no session, no leg or no snapshot the loader can read."""


@dataclass(frozen=True, slots=True)
class DueStep:
    """One due script step: its index in the script, the step, and its due offset (INV 7)."""

    index: int
    step: ScriptedStep
    due_offset_ms: int


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    """One snapshot path the head asks for on the first call, with the card's own label."""

    field_path: str
    label_ru: str
    value: FactValue


@dataclass(frozen=True, slots=True)
class ResponderKnowledge:
    """Everything the service head knows on one call (§80.4.2). Script + snapshot, nothing else."""

    session_id: SessionId
    call_id: uuid.UUID
    direction: DdsCallDirection
    assignment_id: uuid.UUID
    service_type: ServiceId
    service: ServiceCatalogEntry | None
    persona: Persona | None
    snapshot_values: Mapping[str, FactValue]
    checklist: tuple[ChecklistItem, ...]
    steps_due: tuple[DueStep, ...]
    steps_pending_count: int
    leg_status_now: ServiceResponseStatus
    leg_order_number: str | None
    received_at_offset_ms: int
    first_call: bool
    """No earlier call on this leg was answered: the head asks the checklist (§80.4.2)."""
    call_history: tuple[uuid.UUID, ...]
    """This leg's previous calls, oldest first."""
    proposed_on_this_call: frozenset[tuple[str, int]]
    """`(status, due_offset_ms)` already proposed on this call: never proposed twice on it."""
    now_ms: int


def checklist_of(
    snapshot_values: Mapping[str, FactValue], schema: CardSchema
) -> tuple[ChecklistItem, ...]:
    """The snapshot's non-empty `required_for_handoff` paths, in schema order (§80.4.2)."""
    items: list[ChecklistItem] = []
    for spec in schema.fields:
        if not spec.required_for_handoff:
            continue
        if spec.field_path.startswith(CHECKLIST_EXCLUDED_PREFIXES):
            continue
        value = snapshot_values.get(spec.field_path)
        if value is None or value == "" or value == [] or isinstance(value, bool):
            continue
        items.append(ChecklistItem(field_path=spec.field_path, label_ru=spec.label_ru, value=value))
    return tuple(items)


class ResponderContextLoader:
    """Builds `ResponderKnowledge` for one call (see the module docstring for what it may read)."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        scripts: ScriptProbe,
        reference: ReferencePort | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._scripts = scripts
        self._reference = reference

    async def load(self, session_id: SessionId, call_id: uuid.UUID) -> ResponderKnowledge:
        """The head's knowledge right now, on call `call_id` of session `session_id`."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None or session.started_at is None:
                raise ResponderNotFoundError(f"session {session_id}")
            call = await uow.dds_calls.get(session_id, call_id)
            if call is None or call.assignment_id is None:
                raise ResponderNotFoundError(f"service-head call {call_id}")
            leg = await _leg(uow, session, str(call.assignment_id))
            snapshot = await uow.handoffs.get(leg.snapshot_id)
            if snapshot is None:
                raise ResponderNotFoundError(f"snapshot of leg {leg.assignment_id}")
            log = list(await uow.events.read(session_id))
            now_ms = running_ms(session, self._clock.now())
            await uow.commit()
        responders = await self._scripts(session_id)
        return self._knowledge(
            session_id, call_id, call.direction, leg, snapshot.card_values, log, responders, now_ms
        )

    def _knowledge(
        self,
        session_id: SessionId,
        call_id: uuid.UUID,
        direction: DdsCallDirection,
        leg: DDSAssignment,
        snapshot_values: Mapping[str, FactValue],
        log: Sequence[SessionEvent],
        responders: ScriptedResponders | None,
        now_ms: int,
    ) -> ResponderKnowledge:
        catalog = reference_catalog(self._reference)
        pack_id = session_pack_id(log)
        services = catalog.services(pack_id)
        entry = None if services is None else services.get(leg.service_type)
        persona = resolve_persona(
            catalog.personas(pack_id),
            code=None if entry is None else entry.code,
            kind=None if entry is None else entry.kind.value,
            override=persona_override_for(responders, leg.service_type),
        )
        script = script_for(responders, leg.service_type)
        due = due_scripted_steps(leg.response_status, leg.received_at_offset_ms, script, now_ms)
        # `RECEIVED` is the leg's implicit first step (opening the card receives it, §70.4.2): it is
        # not something a head reports, and no trainee command could confirm it.
        steps_due = tuple(
            DueStep(index=_index_of(script, step), step=step, due_offset_ms=at)
            for step, at in due
            if step.status is not ServiceResponseStatus.RECEIVED
        )
        remaining = _remaining_after(script, leg.response_status)
        leg_key = str(leg.assignment_id).lower()
        wanted = str(call_id).lower()
        leg_calls = [
            call
            for call in fold_dds_calls(session_id, log)
            if call.assignment_id is not None and str(call.assignment_id).lower() == leg_key
        ]
        previous = [call for call in leg_calls if str(call.call_id).lower() != wanted]
        return ResponderKnowledge(
            session_id=session_id,
            call_id=call_id,
            direction=direction,
            assignment_id=uuid.UUID(str(leg.assignment_id)),
            service_type=leg.service_type,
            service=entry,
            persona=persona,
            snapshot_values=dict(snapshot_values),
            checklist=checklist_of(snapshot_values, pack_card_schema(catalog, log)),
            steps_due=steps_due,
            steps_pending_count=max(0, remaining - len(due)),
            leg_status_now=leg.response_status,
            leg_order_number=leg.order_number,
            received_at_offset_ms=leg.received_at_offset_ms,
            first_call=not any(call.answered_at_offset_ms is not None for call in previous),
            call_history=tuple(call.call_id for call in previous),
            proposed_on_this_call=_proposed_on(log, wanted),
            now_ms=now_ms,
        )


async def _leg(uow: UnitOfWork, session: SimulationSession, assignment_id: str) -> DDSAssignment:
    """The leg by id, among the session's DDS stages' legs."""
    for stage in session.stages:
        if stage.role_type is not RoleType.DDS:
            continue
        for leg in await uow.dds_assignments.list_for_stage(stage.role_stage_id):
            if str(leg.assignment_id).lower() == assignment_id.lower():
                return leg
    raise ResponderNotFoundError(f"leg {assignment_id}")


def _index_of(script: Sequence[ScriptedStep], step: ScriptedStep) -> int:
    for index, candidate in enumerate(script):
        if candidate is step:
            return index
    return script.index(step)


def _remaining_after(script: Sequence[ScriptedStep], status: ServiceResponseStatus) -> int:
    """How many steps of `script` the leg has not taken yet (`due_scripted_steps`' reading)."""
    start = 0
    for index, step in enumerate(script):
        if step.status is status:
            start = index + 1
    return len(script) - start


def _proposed_on(log: Sequence[SessionEvent], call_key: str) -> frozenset[tuple[str, int]]:
    """`(status, due_offset_ms)` of every `DDS_CALL_STATUS_PROPOSED` already on this call."""
    return frozenset(
        (str(event.payload["status"]), int(event.payload["due_offset_ms"]))
        for event in log
        if event.event_type is EventType.DDS_CALL_STATUS_PROPOSED
        and str(event.payload.get("call_id", "")).lower() == call_key
    )
