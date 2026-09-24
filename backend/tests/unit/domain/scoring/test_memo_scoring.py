"""Memo-mode scoring keys on `DDS_SERVICE_STATUS_SET`, never on dispatch events (I3 E5a, HLD 70
§70.4.4, §70.2.5; D16).

A memo session's log has no `RESOURCE_DISPATCHED` / `RESOURCE_STATUS_CHANGED` and its stage never
walks `EN_ROUTE` … `RESOLVED`; what the ДДС did is the legs' status events. The rules a memo
scenario writes are ordinary `DEADLINE` / `WORKFLOW_ACTION` rules over `DDS_SERVICE_STATUS_SET`
payloads (`new_status`, `service_type`, `source`) — no evaluator changes — and the picker-only
rules carry `applies_to_variants: {dds_mode: [RESOURCE_PICKER]}`, so they are zero/zero here.
"""

from __future__ import annotations

from typing import Any

from app.domain.enums import ActorType, EvaluatorType, RoleType, ScoringCategory
from app.domain.events.types import EventType
from app.domain.scoring.engine import NOT_APPLICABLE_VARIANT_NOTE_RU, score
from app.domain.scoring.rules import ScoringRule

from tests.unit.domain.scoring._event_log_builders import (
    INSTRUCTOR_ID,
    SESSION_ID,
    TRAINEE_ID,
    LogBuilder,
    demo_scenario,
    det_uuid,
)

SCENARIO = demo_scenario()
MEMO = {
    "card_source": "GENERATED_CARD",
    "dds_mode": "MEMO_STATUSES",
    "dds_card_check": "OFF",
    "dds_brigade_call": "OFF",
}
FIRE = det_uuid("memo-leg-fire")
POLICE = det_uuid("memo-leg-police")


def _status(
    log: LogBuilder, leg: Any, service: str, previous: str, new: str, offset: int, *, trainee: bool
) -> None:
    log.add(
        EventType.DDS_SERVICE_STATUS_SET,
        {
            "assignment_id": str(leg),
            "service_type": service,
            "previous_status": previous,
            "new_status": new,
            "trigger": "x",
            "order_number": None,
            "comment_ru": "Не наша компетенция" if new == "NOT_ACCEPTED" else None,
            "completion_reason": None,
            "source": "TRAINEE" if trainee else "SYSTEM",
            "actor_user_id": str(TRAINEE_ID) if trainee else None,
            "at_offset_ms": offset,
        },
        actor_type=ActorType.TRAINEE if trainee else ActorType.SIMULATION,
        actor_id=TRAINEE_ID if trainee else None,
        offset_ms=offset,
    )


def memo_log(*, accept_at_ms: int = 20_000) -> tuple[Any, ...]:
    """A memo run: two legs at 5 s; POLICE declined at 12 s, FIRE accepted at `accept_at_ms`,
    worked to «Работы завершены»; no dispatch event anywhere."""
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
            "variants": MEMO,
        },
        actor_type=ActorType.INSTRUCTOR,
        actor_id=INSTRUCTOR_ID,
        offset_ms=0,
    )
    for leg, service in ((FIRE, "FIRE_RESCUE"), (POLICE, "POLICE")):
        log.add(
            EventType.HANDOFF_RECEIVED,
            {
                "snapshot_id": str(det_uuid("snapshot")),
                "assignment_id": str(leg),
                "role_stage_id": str(det_uuid("stage:DDS")),
                "service_type": service,
                "at_offset_ms": 5_000,
                "responder": "TRAINEE",
                "bound_user_id": None,
                "initial_response_status": "ADDED",
            },
            actor_type=ActorType.SIMULATION,
            offset_ms=5_000,
        )
    _status(log, POLICE, "POLICE", "ADDED", "RECEIVED", 12_000, trainee=False)
    _status(log, POLICE, "POLICE", "RECEIVED", "NOT_ACCEPTED", 12_000, trainee=True)
    _status(log, FIRE, "FIRE_RESCUE", "ADDED", "RECEIVED", accept_at_ms, trainee=False)
    _status(log, FIRE, "FIRE_RESCUE", "RECEIVED", "ACCEPTED", accept_at_ms, trainee=True)
    for offset, (previous, new) in enumerate(
        (
            ("ACCEPTED", "RESPONSE_STARTED"),
            ("RESPONSE_STARTED", "ARRIVED"),
            ("ARRIVED", "WORKING"),
            ("WORKING", "COMPLETED"),
        ),
        start=1,
    ):
        _status(log, FIRE, "FIRE_RESCUE", previous, new, 100_000 * offset, trainee=True)
    log.add(
        EventType.SESSION_COMPLETED,
        {"at_offset_ms": 600_000, "final_session_state": "COMPLETED", "total_events": 0},
        actor_type=ActorType.SIMULATION,
        offset_ms=600_000,
    )
    return log.build()


def _rule(rule_id: str, evaluator: EvaluatorType, config: dict[str, Any], **extra: Any) -> Any:
    return ScoringRule(
        rule_id=rule_id,
        name_ru=rule_id,
        description_ru=rule_id,
        category=ScoringCategory.TIMELINESS,
        max_points=10,
        critical=False,
        evaluator_type=evaluator,
        config=config,
        **extra,
    )


ACCEPT_IN_TIME = _rule(
    "memo_accept_within_30s",
    EvaluatorType.DEADLINE,
    {
        "from_event_type": "HANDOFF_RECEIVED",
        "to_event_type": "DDS_SERVICE_STATUS_SET",
        "to_payload_match": {"service_type": "FIRE_RESCUE", "new_status": "ACCEPTED"},
        "max_offset_ms": 30_000,
        "points": 10,
        "penalty_if_late": -5,
        "scale": "STEP",
        "linear_zero_ms": None,
    },
    applies_to_variants={"dds_mode": ("MEMO_STATUSES",)},
)
COMPETENCE_DECLINE = _rule(
    "memo_police_declines",
    EvaluatorType.WORKFLOW_ACTION,
    {
        "event_type": "DDS_SERVICE_STATUS_SET",
        "payload_match": {"new_status": "NOT_ACCEPTED", "service_type": "POLICE"},
        "min_count": 1,
        "max_count": 1,
        "required_stage_state": None,
        "must_occur_after": None,
        "points": 10,
        "penalty_if_missing": 0,
        "penalty_per_excess": 0,
    },
    applies_to_variants={"dds_mode": ("MEMO_STATUSES",)},
)


def _picker_only(rule_id: str) -> Any:
    rule = next(item for item in SCENARIO.scoring_rules if item.rule_id == rule_id)
    return rule.model_copy(
        update={
            "applies_to_roles": (RoleType.DDS,),
            "applies_to_variants": {"dds_mode": ("RESOURCE_PICKER",)},
        }
    )


def _version(*rules: Any) -> Any:
    return SCENARIO.model_copy(update={"scoring_rules": tuple(rules)})


def test_memo_rules_score_the_status_events() -> None:
    report = score(_version(ACCEPT_IN_TIME, COMPETENCE_DECLINE), memo_log())
    by_id = {result.rule_id: result for result in report.results}

    assert by_id["memo_accept_within_30s"].points_awarded == 10
    assert by_id["memo_police_declines"].points_awarded == 10
    for result in report.results:
        assert result.evidence
        assert all(item.event_id is not None for item in result.evidence)


def test_a_late_primary_decision_loses_the_deadline_points() -> None:
    report = score(_version(ACCEPT_IN_TIME), memo_log(accept_at_ms=60_000))
    assert report.results[0].points_awarded < 10


def test_picker_rules_on_dispatch_events_are_not_applicable_in_memo_mode() -> None:
    """`RESOURCE_SELECTION` (a dispatch-event rule) carries `{dds_mode: [RESOURCE_PICKER]}`:
    zero/zero on a memo log that has no dispatch at all, never a missed-dispatch penalty."""
    picker = _picker_only("resources_fire_high_rise")
    report = score(_version(picker, ACCEPT_IN_TIME), memo_log())
    skipped = next(result for result in report.results if result.rule_id == picker.rule_id)

    assert (skipped.points_awarded, skipped.max_points) == (0.0, 0.0)
    assert not skipped.critical_failure
    assert [item.note_ru for item in skipped.evidence] == [NOT_APPLICABLE_VARIANT_NOTE_RU]
    assert report.critical_errors == ()


def test_a_memo_log_carries_no_dispatch_event() -> None:
    types = {event.event_type for event in memo_log()}
    assert EventType.RESOURCE_DISPATCHED not in types
    assert EventType.RESOURCE_STATUS_CHANGED not in types
    assert EventType.DDS_SERVICE_STATUS_SET in types
