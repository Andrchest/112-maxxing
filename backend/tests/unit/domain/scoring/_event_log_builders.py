"""Deterministic full-session event logs for the scoring tests (E15, SPEC §42 tests 9-11).

Nothing here is random and nothing reads a clock: ids come from `det_uuid` (`uuid5`), `seq_no` is
the position in the log and every offset is written down. Two runs of the same builder produce
byte-identical logs, which is the precondition for asserting that two `score()` calls produce
byte-identical reports.

The scenario is always the committed demo (`scenarios/examples/apartment-fire/v1.yaml`) through
`demo_scenario()` — a test can therefore never drift away from the scoring rules the gate
validates. `good_log()` is a realistic full 112 -> DDS cycle that earns every point; each mutator
takes that log and changes exactly one thing, so a per-rule assertion reads as "this and only this
is what the trainee did wrong".
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from app.domain.common.ids import EventId, SessionId, UserId
from app.domain.enums import ActorType, RoleType, ServiceId
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scenario.version import ScenarioVersion

from tests.unit.domain.world._builders import demo_scenario, det_uuid

__all__ = [
    "MUTATORS",
    "SESSION_ID",
    "TRAINEE_ID",
    "LogBuilder",
    "card_revision_ids",
    "dds_only_log",
    "demo_scenario",
    "det_uuid",
    "good_log",
    "mutate",
    "reworded_log",
    "with_previous_scoring_events",
]

SESSION_ID = SessionId(det_uuid("scoring-session"))
TRAINEE_ID = UserId(det_uuid("scoring-trainee"))
INSTRUCTOR_ID = UserId(det_uuid("scoring-instructor"))
CARD_ID = det_uuid("scoring-card")
INCIDENT_ID = det_uuid("scoring-incident")
ASSIGNMENT_ID = det_uuid("scoring-assignment")
SNAPSHOT_ID = det_uuid("scoring-snapshot")
CALL_ID = det_uuid("scoring-call")

#: Offsets (ms) the assertions quote. Named so a boundary test can say `== limit` in words.
CALL_ANSWERED_MS = 5_000
VICTIM_FACT_MS = 60_000
HANDOFF_MS = 200_000
ON_SCENE_MS = 400_000
STATUS_UPDATE_MS = 430_000
SESSION_END_MS = 600_000

#: `deadline_handoff`: `max_offset_ms` 240 000 from `CALL_ANSWERED`, `linear_zero_ms` 360 000.
DEADLINE_LIMIT_MS = 240_000
DEADLINE_ZERO_MS = 360_000

#: The card the good run hands over — the six `handoff_minimum_fields` paths and then some.
GOOD_CARD_VALUES: Mapping[str, Any] = {
    "incident.type": "FIRE",
    "address.locality": "Смоленск",
    "address.street": "улица Николаева",
    "address.house": "27",
    "address.entrance": "3",
    "address.floor": 5,
    "address.apartment": "45",
    "caller.phone": "+79101234567",
    "description.text": "Задымление и открытое горение в квартире, в квартире человек.",
}

#: What the caller delivers, in the order the good run gets it out of them.
GOOD_DELIVERIES: tuple[tuple[int, tuple[str, ...]], ...] = (
    (20_000, ("incident.type", "incident.smoke_visible")),
    (30_000, ("address.locality", "address.street", "address.house", "address.apartment")),
    (45_000, ("address.floor", "address.entrance")),
    (VICTIM_FACT_MS, ("people.victim_01.inside",)),
    (70_000, ("caller.phone", "caller.full_name")),
)

#: The units the good DDS run sends: two FIRE_RESCUE (one with the ladder) and one AMBULANCE.
GOOD_UNITS: tuple[tuple[str, ServiceId, tuple[str, ...]], ...] = (
    ("ac1", ServiceId("FIRE_RESCUE"), ("FIRE_SUPPRESSION", "WATER_SUPPLY", "SMOKE_DIVING")),
    ("al1", ServiceId("FIRE_RESCUE"), ("HIGH_RISE_ACCESS", "LADDER_RESCUE")),
    ("smp11", ServiceId("AMBULANCE"), ("BASIC_LIFE_SUPPORT",)),
)


class LogBuilder:
    """Appends `SessionEvent`s with monotonically increasing `seq_no` and deterministic ids."""

    def __init__(self, session_id: SessionId = SESSION_ID) -> None:
        self._session_id = session_id
        self._events: list[SessionEvent] = []

    def add(
        self,
        event_type: EventType,
        payload: Mapping[str, Any],
        *,
        actor_type: ActorType,
        offset_ms: int,
        actor_id: UserId | None = None,
        name: str | None = None,
    ) -> SessionEvent:
        seq_no = len(self._events) + 1
        label = name or f"{event_type.value}:{seq_no}"
        event = SessionEvent(
            id=EventId(det_uuid(f"event:{label}")),
            session_id=self._session_id,
            seq_no=seq_no,
            event_type=event_type,
            timestamp_utc=_timestamp(offset_ms),
            monotonic_offset_ms=offset_ms,
            actor_type=actor_type,
            actor_id=actor_id,
            payload=dict(payload),
        )
        self._events.append(event)
        return event

    def build(self) -> tuple[SessionEvent, ...]:
        return tuple(self._events)


def _timestamp(offset_ms: int) -> Any:
    """A wall-clock stamp derived from the offset — never `datetime.now` (§42 test 9)."""
    from datetime import UTC, datetime, timedelta

    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(milliseconds=offset_ms)


# ---------------------------------------------------------------------------------------------
# The good run
# ---------------------------------------------------------------------------------------------


def good_log(
    *,
    card_values: Mapping[str, Any] | None = None,
    deliveries: Sequence[tuple[int, tuple[str, ...]]] | None = None,
    handoff_ms: int = HANDOFF_MS,
    recipient_services: Sequence[str] = ("FIRE_RESCUE", "AMBULANCE"),
    extra_services: Sequence[str] = (),
    units: Sequence[tuple[str, ServiceId, tuple[str, ...]]] | None = None,
    status_update_ms: int | None = STATUS_UPDATE_MS,
    call_answered_count: int = 1,
    caller_text: str = "Горит квартира на четвёртом этаже, дом 27!",
) -> tuple[SessionEvent, ...]:
    """A realistic full 112 -> DDS cycle that earns every point of the demo scenario.

    Every knob exists because one mutator needs it; the defaults are the good run, so a test that
    does not name a knob is reading the same log as every other test.
    """
    card = dict(GOOD_CARD_VALUES if card_values is None else card_values)
    facts = tuple(GOOD_DELIVERIES if deliveries is None else deliveries)
    sent = tuple(GOOD_UNITS if units is None else units)
    services = [*recipient_services, *extra_services]

    log = LogBuilder()
    log.add(
        EventType.SESSION_CREATED,
        {
            "session_id": str(SESSION_ID),
            "scenario_id": str(det_uuid("scenario")),
            "scenario_version_id": str(det_uuid("scenario-version")),
            "scenario_slug": "apartment-fire",
            "scenario_version": 1,
            "session_mode": "FULL_CYCLE_SINGLE_TRAINEE",
            "session_seed": "apartment-fire-v1",
            "time_scale": 1.0,
            "role_chain": ["OPERATOR_112", "DDS"],
            "created_by_user_id": str(INSTRUCTOR_ID),
        },
        actor_type=ActorType.INSTRUCTOR,
        actor_id=INSTRUCTOR_ID,
        offset_ms=0,
    )
    log.add(
        EventType.SESSION_STARTED,
        {
            "started_at_utc": "2026-01-01T00:00:00Z",
            "first_role_stage_id": str(det_uuid("stage:112")),
            "first_role_type": "OPERATOR_112",
        },
        actor_type=ActorType.INSTRUCTOR,
        actor_id=INSTRUCTOR_ID,
        offset_ms=0,
    )
    _stage_started(log, RoleType.OPERATOR_112, 0)
    log.add(
        EventType.CALL_RINGING,
        {
            "call_id": str(CALL_ID),
            "room_name": "sim",
            "caller_display_ru": "Заявитель",
            "at_offset_ms": 1_000,
        },
        actor_type=ActorType.SIMULATION,
        offset_ms=1_000,
    )
    for index in range(call_answered_count):
        log.add(
            EventType.CALL_ANSWERED,
            {
                "call_id": str(CALL_ID),
                "at_offset_ms": CALL_ANSWERED_MS + index,
                "ring_duration_ms": 4_000,
                "answered_by_user_id": str(TRAINEE_ID),
            },
            actor_type=ActorType.TRAINEE,
            actor_id=TRAINEE_ID,
            offset_ms=CALL_ANSWERED_MS + index,
            name=f"CALL_ANSWERED:{index}",
        )
    _stage_state(log, RoleType.OPERATOR_112, "RINGING", "CONNECTED", CALL_ANSWERED_MS + 100)
    _stage_state(log, RoleType.OPERATOR_112, "CONNECTED", "INTERVIEW", CALL_ANSWERED_MS + 200)

    for turn, (offset, fact_ids) in enumerate(facts):
        _caller_turn(log, turn, offset, fact_ids, caller_text)

    for revision, (path, value) in enumerate(sorted(card.items()), start=1):
        _card_field(log, path, value, revision, 100_000 + revision * 100, ActorType.TRAINEE)

    for position, service in enumerate(services):
        log.add(
            EventType.SERVICE_SELECTED,
            {
                "card_id": str(CARD_ID),
                "revision_id": str(det_uuid(f"revision:service:{service}")),
                "service_type": service,
                "selected_services": list(services[: position + 1]),
                "at_offset_ms": 150_000 + position * 100,
            },
            actor_type=ActorType.TRAINEE,
            actor_id=TRAINEE_ID,
            offset_ms=150_000 + position * 100,
            name=f"SERVICE_SELECTED:{service}",
        )

    log.add(
        EventType.HANDOFF_CREATED,
        {
            "snapshot_id": str(SNAPSHOT_ID),
            "incident_id": str(INCIDENT_ID),
            "card_id": str(CARD_ID),
            "card_revision_id": str(det_uuid("revision:handoff")),
            "recipient_services": list(services),
            "card_values": dict(card),
            "content_sha256": "0" * 64,
            "at_offset_ms": handoff_ms,
        },
        actor_type=ActorType.TRAINEE,
        actor_id=TRAINEE_ID,
        offset_ms=handoff_ms,
    )
    _stage_completed(log, RoleType.OPERATOR_112, "STAGE_COMPLETED", handoff_ms + 1_000)

    _stage_started(log, RoleType.DDS, handoff_ms + 2_000)
    log.add(
        EventType.HANDOFF_RECEIVED,
        {
            "snapshot_id": str(SNAPSHOT_ID),
            "assignment_id": str(ASSIGNMENT_ID),
            "role_stage_id": str(det_uuid("stage:DDS")),
            "service_type": "FIRE_RESCUE",
            "at_offset_ms": handoff_ms + 2_100,
        },
        actor_type=ActorType.SIMULATION,
        offset_ms=handoff_ms + 2_100,
    )
    log.add(
        EventType.DDS_ACKNOWLEDGED,
        {
            "assignment_id": str(ASSIGNMENT_ID),
            "at_offset_ms": handoff_ms + 3_000,
            "latency_from_handoff_ms": 3_000,
            "actor_user_id": str(TRAINEE_ID),
        },
        actor_type=ActorType.TRAINEE,
        actor_id=TRAINEE_ID,
        offset_ms=handoff_ms + 3_000,
    )
    _dispatch(log, sent, handoff_ms + 10_000)

    log.add(
        EventType.RESOURCE_STATUS_CHANGED,
        {
            "resource_id": str(det_uuid("resource:ac1")),
            "callsign": "АЦ-1",
            "previous_status": "EN_ROUTE",
            "new_status": "ON_SCENE",
            "trigger": "ETA",
            "assignment_id": str(ASSIGNMENT_ID),
            "source_world_event_id": None,
            "at_offset_ms": ON_SCENE_MS,
        },
        actor_type=ActorType.SIMULATION,
        offset_ms=ON_SCENE_MS,
    )
    if status_update_ms is not None:
        log.add(
            EventType.DDS_STATUS_UPDATE_SENT,
            {
                "assignment_id": str(ASSIGNMENT_ID),
                "update_kind": "ON_SCENE_REPORT",
                "text_ru": "Силы на месте, ведётся разведка.",
                "at_offset_ms": status_update_ms,
                "actor_user_id": str(TRAINEE_ID),
            },
            actor_type=ActorType.TRAINEE,
            actor_id=TRAINEE_ID,
            offset_ms=status_update_ms,
        )
    log.add(
        EventType.DDS_INCIDENT_CLOSED,
        {
            "assignment_id": str(ASSIGNMENT_ID),
            "closure_reason": "RESOLVED",
            "released_resource_ids": [str(det_uuid(f"resource:{key}")) for key, _, _ in sent],
            "at_offset_ms": SESSION_END_MS - 2_000,
            "actor_user_id": str(TRAINEE_ID),
        },
        actor_type=ActorType.TRAINEE,
        actor_id=TRAINEE_ID,
        offset_ms=SESSION_END_MS - 2_000,
    )
    _stage_completed(log, RoleType.DDS, "CLOSED", SESSION_END_MS - 1_000)
    log.add(
        EventType.SESSION_COMPLETED,
        {
            "at_offset_ms": SESSION_END_MS,
            "final_session_state": "COMPLETED",
            "total_events": 0,
        },
        actor_type=ActorType.SIMULATION,
        offset_ms=SESSION_END_MS,
    )
    return log.build()


def dds_only_log() -> tuple[SessionEvent, ...]:
    """A `SINGLE_ROLE` DDS run: the card is the instructor's prefab, and there is no handoff.

    `prefab_handoff` writes the operator card through `set_field` as an `INSTRUCTOR`
    (`application/handoff/prefab_handoff.py`) and emits `HANDOFF_RECEIVED` directly — no trainee
    created a handoff, so §10.13's `TRAINEE`-only `HANDOFF_CREATED` never appears. Every
    `CARD_FIELD_CHANGED` here is therefore `INSTRUCTOR`-authored and must not score as the
    trainee's work (ruling R5).
    """
    log = LogBuilder()
    log.add(
        EventType.SESSION_CREATED,
        {
            "session_id": str(SESSION_ID),
            "scenario_id": str(det_uuid("scenario")),
            "scenario_version_id": str(det_uuid("scenario-version")),
            "scenario_slug": "apartment-fire",
            "scenario_version": 1,
            "session_mode": "SINGLE_ROLE",
            "session_seed": "apartment-fire-v1",
            "time_scale": 1.0,
            "role_chain": ["DDS"],
            "created_by_user_id": str(INSTRUCTOR_ID),
        },
        actor_type=ActorType.INSTRUCTOR,
        actor_id=INSTRUCTOR_ID,
        offset_ms=0,
    )
    _stage_started(log, RoleType.DDS, 0)
    for revision, (path, value) in enumerate(sorted(GOOD_CARD_VALUES.items()), start=1):
        _card_field(log, path, value, revision, revision * 100, ActorType.INSTRUCTOR)
    log.add(
        EventType.HANDOFF_RECEIVED,
        {
            "snapshot_id": str(SNAPSHOT_ID),
            "assignment_id": str(ASSIGNMENT_ID),
            "role_stage_id": str(det_uuid("stage:DDS")),
            "service_type": "FIRE_RESCUE",
            "at_offset_ms": 5_000,
        },
        actor_type=ActorType.SIMULATION,
        offset_ms=5_000,
    )
    _dispatch(log, GOOD_UNITS, 20_000)
    log.add(
        EventType.RESOURCE_STATUS_CHANGED,
        {
            "resource_id": str(det_uuid("resource:ac1")),
            "callsign": "АЦ-1",
            "previous_status": "EN_ROUTE",
            "new_status": "ON_SCENE",
            "trigger": "ETA",
            "assignment_id": str(ASSIGNMENT_ID),
            "source_world_event_id": None,
            "at_offset_ms": 200_000,
        },
        actor_type=ActorType.SIMULATION,
        offset_ms=200_000,
    )
    log.add(
        EventType.DDS_STATUS_UPDATE_SENT,
        {
            "assignment_id": str(ASSIGNMENT_ID),
            "update_kind": "ON_SCENE_REPORT",
            "text_ru": "Силы на месте.",
            "at_offset_ms": 230_000,
            "actor_user_id": str(TRAINEE_ID),
        },
        actor_type=ActorType.TRAINEE,
        actor_id=TRAINEE_ID,
        offset_ms=230_000,
    )
    _stage_completed(log, RoleType.DDS, "CLOSED", 250_000)
    log.add(
        EventType.SESSION_COMPLETED,
        {
            "at_offset_ms": 260_000,
            "final_session_state": "COMPLETED",
            "total_events": 0,
        },
        actor_type=ActorType.SIMULATION,
        offset_ms=260_000,
    )
    return log.build()


# ---------------------------------------------------------------------------------------------
# Mutators — one wrong thing each (§42 test 11 runs over all of them)
# ---------------------------------------------------------------------------------------------


def _field_never_filled() -> tuple[SessionEvent, ...]:
    card = {key: value for key, value in GOOD_CARD_VALUES.items() if key != "caller.phone"}
    return good_log(card_values=card)


def _wrong_house_number() -> tuple[SessionEvent, ...]:
    return good_log(card_values={**GOOD_CARD_VALUES, "address.house": "72"})


def _late_handoff() -> tuple[SessionEvent, ...]:
    return good_log(handoff_ms=CALL_ANSWERED_MS + 300_000)


def _forbidden_service() -> tuple[SessionEvent, ...]:
    return good_log(extra_services=("UTILITY_EMERGENCY",))


def _off_service_unit() -> tuple[SessionEvent, ...]:
    """The ladder truck is replaced by a police patrol: allowed, but it is not a fire unit."""
    units = (
        GOOD_UNITS[0],
        ("pps204", ServiceId("POLICE"), ("PUBLIC_ORDER", "AREA_CORDON")),
        GOOD_UNITS[2],
    )
    return good_log(units=units)


def _missing_status_update() -> tuple[SessionEvent, ...]:
    return good_log(status_update_ms=None)


def _fact_never_delivered() -> tuple[SessionEvent, ...]:
    deliveries = tuple(
        (offset, tuple(f for f in fact_ids if f != "people.victim_01.inside"))
        for offset, fact_ids in GOOD_DELIVERIES
    )
    return good_log(deliveries=deliveries)


def _fact_delivered_late() -> tuple[SessionEvent, ...]:
    """The victim fact arrives at 190 s — past `within_ms: 180000`, before the handoff."""
    deliveries = (
        *(
            (offset, tuple(f for f in fact_ids if f != "people.victim_01.inside"))
            for offset, fact_ids in GOOD_DELIVERIES
        ),
        (190_000, ("people.victim_01.inside",)),
    )
    return good_log(deliveries=deliveries)


def _contradiction_after_delivery() -> tuple[SessionEvent, ...]:
    """The caller said floor 5 and it was delivered; the operator typed 9 anyway."""
    return good_log(card_values={**GOOD_CARD_VALUES, "address.floor": 9})


def _double_answered_call() -> tuple[SessionEvent, ...]:
    return good_log(call_answered_count=2)


MUTATORS: Mapping[str, Callable[[], tuple[SessionEvent, ...]]] = {
    "field_never_filled": _field_never_filled,
    "wrong_house_number": _wrong_house_number,
    "late_handoff": _late_handoff,
    "forbidden_service": _forbidden_service,
    "off_service_unit": _off_service_unit,
    "missing_status_update": _missing_status_update,
    "fact_never_delivered": _fact_never_delivered,
    "fact_delivered_late": _fact_delivered_late,
    "contradiction_after_delivery": _contradiction_after_delivery,
    "double_answered_call": _double_answered_call,
    "dds_only_prefab_card": dds_only_log,
}


def mutate(name: str) -> tuple[SessionEvent, ...]:
    """One mutated log by name — `MUTATORS` is the whole list §42 test 11 sweeps."""
    return MUTATORS[name]()


def reworded_log() -> tuple[SessionEvent, ...]:
    """The good run with every caller-text-bearing payload reworded (§42 test 10).

    `FACTS_DELIVERED` is untouched — that is the whole point: what the caller *said* changed
    completely, what the code decided was *delivered* did not.
    """
    return good_log(
        caller_text="Пожар! Дым валит из окон, дом двадцать семь, помогите скорее!!!",
    )


def with_previous_scoring_events(
    events: Sequence[SessionEvent],
    scenario: ScenarioVersion | None = None,
) -> tuple[SessionEvent, ...]:
    """Append one `SCORING_RULE_EVALUATED` per rule, as a previous scoring run would have (R2)."""
    version = scenario if scenario is not None else demo_scenario()
    out = list(events)
    last = out[-1]
    for index, rule in enumerate(version.scoring_rules, start=1):
        out.append(
            SessionEvent(
                id=EventId(det_uuid(f"event:SCORING:{rule.rule_id}")),
                session_id=last.session_id,
                seq_no=last.seq_no + index,
                event_type=EventType.SCORING_RULE_EVALUATED,
                timestamp_utc=last.timestamp_utc,
                monotonic_offset_ms=last.monotonic_offset_ms,
                actor_type=ActorType.SYSTEM,
                payload={
                    "rule_id": rule.rule_id,
                    "evaluator_type": rule.evaluator_type.value,
                    "category": rule.category.value,
                    "points_awarded": 0.0,
                    "max_points": rule.max_points,
                    "passed": False,
                    "critical": rule.critical,
                    "evidence": [],
                },
            )
        )
    return tuple(out)


def card_revision_ids(events: Sequence[SessionEvent]) -> frozenset[uuid.UUID]:
    """Every `revision_id` a `CARD_FIELD_CHANGED` in `events` carries (§42 test 11)."""
    found: set[uuid.UUID] = set()
    for event in events:
        if event.event_type is EventType.CARD_FIELD_CHANGED:
            raw = event.payload.get("revision_id")
            if isinstance(raw, str):
                found.add(uuid.UUID(raw))
    return frozenset(found)


# ---------------------------------------------------------------------------------------------
# Small appenders
# ---------------------------------------------------------------------------------------------


def _stage_started(log: LogBuilder, role: RoleType, offset_ms: int) -> None:
    log.add(
        EventType.ROLE_STAGE_STARTED,
        {
            "role_stage_id": str(det_uuid(f"stage:{role.value}")),
            "role_type": role.value,
            "order_index": 0 if role is RoleType.OPERATOR_112 else 1,
            "initial_state": "WAITING_FOR_CALL" if role is RoleType.OPERATOR_112 else "RECEIVED",
            "participant_user_id": str(TRAINEE_ID),
        },
        actor_type=ActorType.SIMULATION,
        offset_ms=offset_ms,
        name=f"ROLE_STAGE_STARTED:{role.value}",
    )


def _stage_completed(log: LogBuilder, role: RoleType, final_state: str, offset_ms: int) -> None:
    log.add(
        EventType.ROLE_STAGE_COMPLETED,
        {
            "role_stage_id": str(det_uuid(f"stage:{role.value}")),
            "role_type": role.value,
            "final_state": final_state,
            "duration_ms": offset_ms,
        },
        actor_type=ActorType.SIMULATION,
        offset_ms=offset_ms,
        name=f"ROLE_STAGE_COMPLETED:{role.value}",
    )


def _stage_state(log: LogBuilder, role: RoleType, previous: str, new: str, offset_ms: int) -> None:
    log.add(
        EventType.STAGE_STATE_CHANGED,
        {
            "role_stage_id": str(det_uuid(f"stage:{role.value}")),
            "role_type": role.value,
            "previous_state": previous,
            "new_state": new,
            "trigger": "COMMAND",
            "fired_by_actor_type": "TRAINEE",
            "fired_by_user_id": str(TRAINEE_ID),
            "at_offset_ms": offset_ms,
        },
        actor_type=ActorType.SIMULATION,
        offset_ms=offset_ms,
        name=f"STAGE_STATE_CHANGED:{role.value}:{new}",
    )


def _caller_turn(
    log: LogBuilder,
    turn: int,
    offset_ms: int,
    fact_ids: tuple[str, ...],
    caller_text: str,
) -> None:
    """One trainee question and the caller's answer, including the text-bearing payloads.

    The text payloads exist precisely so INV 10 has something to reword; `FACTS_DELIVERED` is the
    only one of them scoring reads (D10).
    """
    text = f"{caller_text} [{turn}]"
    log.add(
        EventType.CALLER_TTS_STARTED,
        {
            "call_id": str(CALL_ID),
            "turn_index": turn,
            "planned_text": text,
            "at_offset_ms": offset_ms - 2_000,
        },
        actor_type=ActorType.SIMULATION,
        offset_ms=offset_ms - 2_000,
        name=f"CALLER_TTS_STARTED:{turn}",
    )
    log.add(
        EventType.CALLER_TTS_ENDED,
        {
            "call_id": str(CALL_ID),
            "turn_index": turn,
            "delivered_text": text,
            "completed": True,
            "at_offset_ms": offset_ms - 100,
        },
        actor_type=ActorType.SIMULATION,
        offset_ms=offset_ms - 100,
        name=f"CALLER_TTS_ENDED:{turn}",
    )
    if fact_ids:
        log.add(
            EventType.FACTS_DELIVERED,
            {
                "turn_index": turn,
                "fact_ids": list(fact_ids),
                "delivered_via": "TTS_COMPLETED",
                "at_offset_ms": offset_ms,
            },
            actor_type=ActorType.SIMULATION,
            offset_ms=offset_ms,
            name=f"FACTS_DELIVERED:{turn}",
        )


def _card_field(
    log: LogBuilder,
    field_path: str,
    value: Any,
    revision_no: int,
    offset_ms: int,
    actor_type: ActorType,
) -> None:
    log.add(
        EventType.CARD_FIELD_CHANGED,
        {
            "card_id": str(CARD_ID),
            "revision_id": str(det_uuid(f"revision:{field_path}")),
            "revision_no": revision_no,
            "field_path": field_path,
            "previous_value": None,
            "new_value": value,
            "value_type": "STRING",
            "actor_user_id": str(TRAINEE_ID if actor_type is ActorType.TRAINEE else INSTRUCTOR_ID),
            "at_offset_ms": offset_ms,
        },
        actor_type=actor_type,
        actor_id=TRAINEE_ID if actor_type is ActorType.TRAINEE else INSTRUCTOR_ID,
        offset_ms=offset_ms,
        name=f"CARD_FIELD_CHANGED:{field_path}",
    )


def _dispatch(
    log: LogBuilder,
    units: Sequence[tuple[str, ServiceId, tuple[str, ...]]],
    offset_ms: int,
) -> None:
    for position, (key, service, capabilities) in enumerate(units):
        log.add(
            EventType.RESOURCE_SELECTED,
            {
                "assignment_id": str(ASSIGNMENT_ID),
                "resource_id": str(det_uuid(f"resource:{key}")),
                "callsign": key.upper(),
                "service_type": service,
                "resource_type": "FIRE_ENGINE",
                "capabilities": list(capabilities),
                "at_offset_ms": offset_ms + position * 100,
            },
            actor_type=ActorType.TRAINEE,
            actor_id=TRAINEE_ID,
            offset_ms=offset_ms + position * 100,
            name=f"RESOURCE_SELECTED:{key}",
        )
    union: list[str] = []
    for _, _, capabilities in units:
        union.extend(capability for capability in capabilities if capability not in union)
    log.add(
        EventType.RESOURCE_DISPATCHED,
        {
            "assignment_id": str(ASSIGNMENT_ID),
            "resource_ids": [str(det_uuid(f"resource:{key}")) for key, _, _ in units],
            "callsigns": [key.upper() for key, _, _ in units],
            "capabilities_union": union,
            "eta_seconds_by_resource": {
                str(det_uuid(f"resource:{key}")): 180 for key, _, _ in units
            },
            "service_type_by_resource": {
                str(det_uuid(f"resource:{key}")): service for key, service, _ in units
            },
            "at_offset_ms": offset_ms + 1_000,
            "is_additional": False,
        },
        actor_type=ActorType.TRAINEE,
        actor_id=TRAINEE_ID,
        offset_ms=offset_ms + 1_000,
    )
