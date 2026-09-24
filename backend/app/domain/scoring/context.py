"""`ScoringContext` — the one read model every evaluator sees (HLD `10-domain-model.md` §10.14).

Built once from `(scenario_version, events)` and nothing else (D5: "scoring reads only
`(ScenarioVersion, ordered SessionEvents)` — never the materialized tables"). Everything on it is
immutable and already in a deterministic order, so no evaluator can make a number depend on a
dict's or a set's iteration order.

Three rules this module, not the individual evaluators, is responsible for:

* **`SCORING_*` events are dropped** before anything else looks at the log. Scoring runs *after*
  `SESSION_COMPLETED` and appends one `SCORING_RULE_EVALUATED` per rule, so re-scoring the stored
  log would otherwise see its own previous output. `computed_from_event_count` counts what was
  actually read, which is what makes a re-score byte-identical to the original run.
* **The card timeline is the trainee's work only** (D3). A DDS-only session builds its operator
  card through `prefab_handoff`, whose revisions are authored by an `INSTRUCTOR`
  (`application/handoff/prefab_handoff.py`); scoring the trainee on the instructor's prefab would
  award the trainee points nobody earned, so `CARD_FIELD_CHANGED` events are kept only when
  `SessionEvent.actor_type is TRAINEE`.
* **A dispatched unit's service comes from the unit**, never from its assignment leg — an
  off-service unit attaches to the primary leg, so `assignment_id` does not imply a service. The
  per-unit `RESOURCE_DISPATCHED.service_type_by_resource` map is the only source
  (`application/dds/leg_for.py`).
* **A ДДС call's facts are not the 112 call's** (I3 E6b, HLD 80 §80.6.2). The per-turn pipeline
  events are reused under a ДДС call's `call_id` (a claimant call-back runs the frozen caller
  chain), so `deliveries_of` excludes every `FACTS_DELIVERED` whose `call_id` is a DDS call id —
  the `call_id`s of the log's `DDS_CALL_STARTED` — unless a rule asks for them (`on_call:
  DDS_CLAIMANT`). A call-back therefore never moves the 112 trainee's `FACT_OBTAINED` score.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.domain.common.ids import CardRevisionId
from app.domain.common.values import FactValue
from app.domain.dds.call import DdsCallKind
from app.domain.enums import ActorType, RoleType, ServiceId
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.session.variants import SessionVariants

if TYPE_CHECKING:  # `app.domain.scenario` imports the evaluator registry (§30.8 item 20), which
    # imports this module: the annotation is a string under `from __future__ import annotations`,
    # so the type is available to mypy without making that cycle real at import time.
    from app.domain.scenario.version import ScenarioVersion

__all__ = [
    "CALLER_112",
    "DDS_CLAIMANT",
    "CardFieldChange",
    "DispatchedUnit",
    "FactDelivery",
    "ScoringContext",
    "SelectedUnit",
    "UnorderedEventLogError",
    "build_context",
]

_SCORING_EVENT_TYPES: frozenset[EventType] = frozenset(
    member for member in EventType if member.name.startswith("SCORING_")
)
"""Every event `score()` produces and therefore must never read back (ruling R2)."""

CALLER_112 = "CALLER_112"
"""`FACT_OBTAINED.on_call`'s default: facts delivered on the 112 call (HLD 80 §80.6.2)."""
DDS_CLAIMANT = "DDS_CLAIMANT"
"""`FACT_OBTAINED.on_call`: facts the claimant delivered on a ДДС call-back (I3 E6b)."""


class UnorderedEventLogError(ValueError):
    """`events` was not strictly ordered by `seq_no` — a caller bug, not a bad score.

    Scoring is defined over "the ordered `SessionEvents`" (D5). A log handed over out of order, or
    with a duplicated `seq_no`, cannot be scored into a number anybody should trust, so this is a
    hard error rather than a quiet re-sort that would hide the caller's defect.
    """


@dataclass(frozen=True, slots=True)
class CardFieldChange:
    """One trainee-authored `CARD_FIELD_CHANGED` (§10.13), reduced to what scoring reads."""

    field_path: str
    new_value: FactValue
    revision_id: CardRevisionId | None
    event: SessionEvent


@dataclass(frozen=True, slots=True)
class FactDelivery:
    """One fact the caller actually delivered, from `FACTS_DELIVERED` only (D10, §42 test 10)."""

    fact_id: str
    at_offset_ms: int
    event: SessionEvent
    call_id: str | None = None
    """The delivering call's id, lowercase — a DDS call id or the 112 call's (I3 E6b)."""


@dataclass(frozen=True, slots=True)
class SelectedUnit:
    """A unit the DDS trainee put on the board (`RESOURCE_SELECTED`)."""

    resource_id: str
    service_type: ServiceId | None
    capabilities: frozenset[str]
    event: SessionEvent


@dataclass(frozen=True, slots=True)
class DispatchedUnit:
    """A dispatched unit with *its own* service type (`RESOURCE_DISPATCHED`, ruling R6)."""

    resource_id: str
    service_type: ServiceId | None
    capabilities: frozenset[str]
    event: SessionEvent


@dataclass(frozen=True, slots=True)
class ScoringContext:
    """Everything the ten evaluators may look at, and nothing else (§10.14)."""

    scenario_version: ScenarioVersion
    events: tuple[SessionEvent, ...]
    by_type: Mapping[EventType, tuple[SessionEvent, ...]]
    card_changes: tuple[CardFieldChange, ...]
    handoff_event: SessionEvent | None
    handoff_card_values: Mapping[str, FactValue]
    deliveries: tuple[FactDelivery, ...]
    selected_units: tuple[SelectedUnit, ...]
    dispatched_units: tuple[DispatchedUnit, ...]
    dispatched_capabilities: frozenset[str]
    role_chain: tuple[RoleType, ...]
    role_chain_event: SessionEvent | None
    variants: SessionVariants
    session_completed: SessionEvent | None
    stage_completed_by_role: Mapping[RoleType, SessionEvent]
    dds_call_ids: frozenset[str] = frozenset()
    """The session's DDS call ids (`DDS_CALL_STARTED.call_id`, lowercase; HLD 80 §80.6.2)."""
    claimant_call_ids: frozenset[str] = frozenset()
    """The subset of `dds_call_ids` whose `kind` is `CLAIMANT`."""

    # -- offsets -------------------------------------------------------------------------

    @property
    def computed_from_event_count(self) -> int:
        """How many events were actually read (`ScoreReport.computed_from_event_count`)."""
        return len(self.events)

    def of_type(self, event_type: EventType) -> tuple[SessionEvent, ...]:
        """Every event of `event_type`, in `seq_no` order."""
        return self.by_type.get(event_type, ())

    def first_of_type(self, event_type: EventType) -> SessionEvent | None:
        occurrences = self.of_type(event_type)
        return occurrences[0] if occurrences else None

    def cutoff_seq_no(self, evaluated_at: str) -> int:
        """The `seq_no` an `evaluated_at: HANDOFF | SESSION_END` rule reads the card at.

        `HANDOFF` without a `HANDOFF_CREATED` in the log (a DDS-only session, or a 112 stage that
        never handed off) falls back to the end of the log: there is no earlier moment to freeze
        at, and the rule must still resolve to a number with evidence.
        """
        if evaluated_at == "HANDOFF" and self.handoff_event is not None:
            return self.handoff_event.seq_no
        return self.events[-1].seq_no if self.events else 0

    # -- card timeline -------------------------------------------------------------------

    def card_value_at(self, field_path: str, cutoff_seq_no: int) -> FactValue:
        """The value of `field_path` as the trainee left it at `cutoff_seq_no` (D5)."""
        change = self.last_card_change(field_path, cutoff_seq_no)
        return change.new_value if change is not None else None

    def last_card_change(self, field_path: str, cutoff_seq_no: int) -> CardFieldChange | None:
        """The last trainee change to `field_path` at or before `cutoff_seq_no`."""
        found: CardFieldChange | None = None
        for change in self.card_changes:
            if change.field_path != field_path or change.event.seq_no > cutoff_seq_no:
                continue
            found = change
        return found

    def first_card_change(self, field_path: str, cutoff_seq_no: int) -> CardFieldChange | None:
        """The first trainee change to `field_path` at or before `cutoff_seq_no`."""
        for change in self.card_changes:
            if change.field_path != field_path or change.event.seq_no > cutoff_seq_no:
                continue
            return change
        return None

    # -- facts ---------------------------------------------------------------------------

    def deliveries_of(self, fact_id: str, *, on_call: str = CALLER_112) -> tuple[FactDelivery, ...]:
        """Every delivery of `fact_id`, in log order (`FACTS_DELIVERED` only — D10).

        `on_call` (I3 E6b, HLD 80 §80.6.2): `CALLER_112` — the default, and everything before E6b —
        excludes the deliveries of every ДДС call; `DDS_CLAIMANT` keeps only a claimant
        call-back's."""
        if on_call == DDS_CLAIMANT:
            return tuple(
                delivery
                for delivery in self.deliveries
                if delivery.fact_id == fact_id and delivery.call_id in self.claimant_call_ids
            )
        return tuple(
            delivery
            for delivery in self.deliveries
            if delivery.fact_id == fact_id and delivery.call_id not in self.dds_call_ids
        )

    # -- bounding events (the "absence" evidence of D11) ---------------------------------

    def stage_bound(self, *roles: RoleType) -> SessionEvent | None:
        """The bounding `ROLE_STAGE_COMPLETED` for the first of `roles` that has one.

        Falls back to the last `ROLE_STAGE_COMPLETED` of the log and then to
        `SESSION_COMPLETED`: "absence" evidence points at the event that proves the window
        closed without the thing happening (D11).
        """
        for role in roles:
            completed = self.stage_completed_by_role.get(role)
            if completed is not None:
                return completed
        stages = self.of_type(EventType.ROLE_STAGE_COMPLETED)
        if stages:
            return stages[-1]
        return self.session_completed


# ---------------------------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------------------------


def build_context(
    scenario_version: ScenarioVersion,
    events: Sequence[SessionEvent],
) -> ScoringContext:
    """Build the context once from `(scenario_version, events)` (§10.14, D5)."""
    readable = _ordered_without_scoring_events(events)
    by_type: dict[EventType, list[SessionEvent]] = {}
    for event in readable:
        by_type.setdefault(event.event_type, []).append(event)

    handoff_events = by_type.get(EventType.HANDOFF_CREATED, [])
    handoff_event = handoff_events[0] if handoff_events else None
    role_chain, role_chain_event = _role_chain(by_type)

    return ScoringContext(
        scenario_version=scenario_version,
        events=readable,
        by_type={event_type: tuple(group) for event_type, group in by_type.items()},
        card_changes=_card_changes(by_type.get(EventType.CARD_FIELD_CHANGED, [])),
        handoff_event=handoff_event,
        handoff_card_values=_handoff_card_values(handoff_event),
        deliveries=_deliveries(by_type.get(EventType.FACTS_DELIVERED, [])),
        selected_units=_selected_units(by_type),
        dispatched_units=_dispatched_units(by_type),
        dispatched_capabilities=_dispatched_capabilities(by_type),
        role_chain=role_chain,
        role_chain_event=role_chain_event,
        variants=_variants(scenario_version, by_type),
        session_completed=_last(by_type.get(EventType.SESSION_COMPLETED, [])),
        stage_completed_by_role=_stage_completed_by_role(by_type),
        dds_call_ids=_dds_call_ids(by_type),
        claimant_call_ids=_dds_call_ids(by_type, kind=DdsCallKind.CLAIMANT),
    )


def _dds_call_ids(
    by_type: Mapping[EventType, Sequence[SessionEvent]], kind: DdsCallKind | None = None
) -> frozenset[str]:
    """`DDS_CALL_STARTED.call_id`s (of one `kind`, or all), lowercase (HLD 80 §80.6.2)."""
    return frozenset(
        str(event.payload["call_id"]).lower()
        for event in by_type.get(EventType.DDS_CALL_STARTED, [])
        if event.payload.get("call_id")
        and (kind is None or event.payload.get("kind") == kind.value)
    )


def _ordered_without_scoring_events(events: Sequence[SessionEvent]) -> tuple[SessionEvent, ...]:
    previous: int | None = None
    for event in events:
        if previous is not None and event.seq_no <= previous:
            raise UnorderedEventLogError(
                f"events must be strictly ordered by seq_no; got {previous} then {event.seq_no}"
            )
        previous = event.seq_no
    return tuple(event for event in events if event.event_type not in _SCORING_EVENT_TYPES)


def _last(events: Sequence[SessionEvent]) -> SessionEvent | None:
    return events[-1] if events else None


def _card_changes(events: Sequence[SessionEvent]) -> tuple[CardFieldChange, ...]:
    changes: list[CardFieldChange] = []
    for event in events:
        if event.actor_type is not ActorType.TRAINEE:
            continue
        field_path = _str(event.payload.get("field_path"))
        if field_path is None:
            continue
        changes.append(
            CardFieldChange(
                field_path=field_path,
                new_value=_fact_value(event.payload.get("new_value")),
                revision_id=_card_revision_id(event.payload.get("revision_id")),
                event=event,
            )
        )
    return tuple(changes)


def _handoff_card_values(handoff_event: SessionEvent | None) -> Mapping[str, FactValue]:
    if handoff_event is None:
        return {}
    card_values = handoff_event.payload.get("card_values")
    if not isinstance(card_values, Mapping):
        return {}
    return {
        str(key): _fact_value(value)
        for key, value in sorted(card_values.items(), key=lambda item: str(item[0]))
    }


def _deliveries(events: Sequence[SessionEvent]) -> tuple[FactDelivery, ...]:
    deliveries: list[FactDelivery] = []
    for event in events:
        fact_ids = event.payload.get("fact_ids")
        if not isinstance(fact_ids, list | tuple):
            continue
        at_offset_ms = _int(event.payload.get("at_offset_ms"), event.monotonic_offset_ms)
        raw_call_id = event.payload.get("call_id")
        call_id = None if raw_call_id is None else str(raw_call_id).lower()
        for fact_id in fact_ids:
            if isinstance(fact_id, str):
                deliveries.append(
                    FactDelivery(
                        fact_id=fact_id, at_offset_ms=at_offset_ms, event=event, call_id=call_id
                    )
                )
    return tuple(deliveries)


def _selected_units(
    by_type: Mapping[EventType, Sequence[SessionEvent]],
) -> tuple[SelectedUnit, ...]:
    """Units selected and not later deselected, in first-selection order."""
    selected: dict[str, SelectedUnit] = {}
    for event in _merged(by_type, EventType.RESOURCE_SELECTED, EventType.RESOURCE_DESELECTED):
        resource_id = _str(event.payload.get("resource_id"))
        if resource_id is None:
            continue
        if event.event_type is EventType.RESOURCE_DESELECTED:
            selected.pop(resource_id, None)
            continue
        selected[resource_id] = SelectedUnit(
            resource_id=resource_id,
            service_type=_service_type(event.payload.get("service_type")),
            capabilities=_capabilities(event.payload.get("capabilities")),
            event=event,
        )
    return tuple(selected.values())


def _dispatched_units(
    by_type: Mapping[EventType, Sequence[SessionEvent]],
) -> tuple[DispatchedUnit, ...]:
    capabilities_by_resource = {
        unit.resource_id: unit.capabilities for unit in _selected_units(by_type)
    }
    dispatched: dict[str, DispatchedUnit] = {}
    for event in by_type.get(EventType.RESOURCE_DISPATCHED, []):
        services = event.payload.get("service_type_by_resource")
        service_by_resource: Mapping[str, Any] = (
            {str(key): value for key, value in services.items()}
            if isinstance(services, Mapping)
            else {}
        )
        resource_ids = event.payload.get("resource_ids")
        if not isinstance(resource_ids, list | tuple):
            continue
        for raw in resource_ids:
            resource_id = _str(raw)
            if resource_id is None or resource_id in dispatched:
                continue
            dispatched[resource_id] = DispatchedUnit(
                resource_id=resource_id,
                service_type=_service_type(service_by_resource.get(resource_id)),
                capabilities=capabilities_by_resource.get(resource_id, frozenset()),
                event=event,
            )
    return tuple(dispatched.values())


def _dispatched_capabilities(
    by_type: Mapping[EventType, Sequence[SessionEvent]],
) -> frozenset[str]:
    covered: set[str] = set()
    for event in by_type.get(EventType.RESOURCE_DISPATCHED, []):
        covered |= _capabilities(event.payload.get("capabilities_union"))
    return frozenset(covered)


def _stage_completed_by_role(
    by_type: Mapping[EventType, Sequence[SessionEvent]],
) -> Mapping[RoleType, SessionEvent]:
    """The FIRST `ROLE_STAGE_COMPLETED` per role — the moment that role's window closed."""
    completed: dict[RoleType, SessionEvent] = {}
    for event in by_type.get(EventType.ROLE_STAGE_COMPLETED, []):
        role = _role_type(event.payload.get("role_type"))
        if role is not None and role not in completed:
            completed[role] = event
    return completed


def _role_chain(
    by_type: Mapping[EventType, Sequence[SessionEvent]],
) -> tuple[tuple[RoleType, ...], SessionEvent | None]:
    """The session's role chain as the log records it, plus the event that recorded it (R7).

    `SESSION_CREATED.role_chain` is the primary source: §10.13 gives it that key, it is the first
    event of every session, and it states the chain the instructor configured rather than the
    stages that happened to run. `ROLE_STAGE_STARTED.role_type` is the fallback for a log that
    does not start at the beginning; a log with neither records no chain at all, and
    `applies_to_roles` then cannot be decided from the log, so every rule applies.
    """
    created = by_type.get(EventType.SESSION_CREATED, [])
    if created:
        event = created[0]
        raw = event.payload.get("role_chain")
        if isinstance(raw, list | tuple):
            roles = tuple(role for role in (_role_type(item) for item in raw) if role is not None)
            if roles:
                return roles, event
    started = by_type.get(EventType.ROLE_STAGE_STARTED, [])
    chain: list[RoleType] = []
    for event in started:
        role = _role_type(event.payload.get("role_type"))
        if role is not None and role not in chain:
            chain.append(role)
    if chain:
        return tuple(chain), started[0]
    return (), None


def _variants(
    scenario_version: ScenarioVersion,
    by_type: Mapping[EventType, Sequence[SessionEvent]],
) -> SessionVariants:
    """The session's variants as `SESSION_CREATED.variants` records them (HLD 70 §70.2.5).

    A log written before E1 has no such key; it then reads as the scenario's derived default —
    the schema-1 derivation, which is exactly how that session ran — so it rescores identically
    (INV 9). A malformed record falls back the same way rather than raising (total readers).
    """
    created = by_type.get(EventType.SESSION_CREATED, [])
    raw = created[0].payload.get("variants") if created else None
    if isinstance(raw, Mapping):
        try:
            return SessionVariants.model_validate(dict(raw))
        except ValueError:
            pass
    return scenario_version.scenario_variants.default


# ---------------------------------------------------------------------------------------------
# Payload readers. Every one is total: a malformed payload contributes nothing rather than
# raising, exactly like `facts/revealed.py`'s fold.
# ---------------------------------------------------------------------------------------------


def _merged(
    by_type: Mapping[EventType, Sequence[SessionEvent]],
    *event_types: EventType,
) -> tuple[SessionEvent, ...]:
    merged: list[SessionEvent] = []
    for event_type in event_types:
        merged.extend(by_type.get(event_type, []))
    return tuple(sorted(merged, key=lambda event: event.seq_no))


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else (str(value) if isinstance(value, UUID) else None)


def _int(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    return value if isinstance(value, int) else fallback


def _fact_value(value: object) -> FactValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple):
        return [item if isinstance(item, str) else str(item) for item in value]
    return str(value)


def _card_revision_id(value: object) -> CardRevisionId | None:
    if isinstance(value, UUID):
        return CardRevisionId(value)
    if isinstance(value, str):
        try:
            return CardRevisionId(UUID(value))
        except ValueError:
            return None
    return None


def _service_type(value: object) -> ServiceId | None:
    """A payload's service id (a catalog id, D18); `None` when absent or not a non-empty string."""
    if isinstance(value, str) and value:
        return ServiceId(value)
    return None


def _role_type(value: object) -> RoleType | None:
    if isinstance(value, RoleType):
        return value
    if isinstance(value, str):
        try:
            return RoleType(value)
        except ValueError:
            return None
    return None


def _capabilities(value: object) -> frozenset[str]:
    if not isinstance(value, list | tuple | set | frozenset):
        return frozenset()
    return frozenset(str(item) for item in value)
