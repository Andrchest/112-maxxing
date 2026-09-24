"""Call rules score the ДДС phone's events with the existing evaluators (I3 E6c, HLD
`80-telephony.md` §80.6.2; SPEC §28 "at least").

The scoring fixtures the E6c row names: `WORKFLOW_ACTION` / `DEADLINE` over `DDS_CALL_STARTED`,
`DDS_CALL_ASSERTION`, `DDS_CALL_STATUS_PROPOSED` and the trainee's `DDS_SERVICE_STATUS_SET`, each
`applies_to_variants: {dds_brigade_call: [ON]}`. "The trainee transcribed the status heard on the
call" is `WORKFLOW_ACTION {event_type: DDS_SERVICE_STATUS_SET, payload_match: {new_status, source:
TRAINEE}, must_occur_after: DDS_CALL_STATUS_PROPOSED}` — expressible without a new evaluator, so
`CALL_STATUS_TRANSCRIBED` is not added (the HLD adds it "only if `must_occur_after` cannot express
it"). An `OFF` session scores every call rule not applicable.
"""

from __future__ import annotations

from typing import Any

from app.domain.enums import ActorType, EvaluatorType, ScoringCategory
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
LEG = det_uuid("call-leg-fire")
CALL = det_uuid("call-head-101")
ON_ONLY = {"dds_brigade_call": ("ON",)}


def _variants(brigade_call: str) -> dict[str, str]:
    return {
        "card_source": "GENERATED_CARD",
        "dds_mode": "MEMO_STATUSES",
        "dds_card_check": "OFF",
        "dds_brigade_call": brigade_call,
    }


def call_log(
    *, brigade_call: str = "ON", confirm_at_ms: int = 40_000, proposal_at_ms: int = 30_000
) -> tuple[Any, ...]:
    """A memo run with the phone: the ДДС calls 101 at 10 s, states the street, hears ACCEPTED at
    `proposal_at_ms` and sets ACCEPTED at `confirm_at_ms` naming the call."""
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
            "variants": _variants(brigade_call),
        },
        actor_type=ActorType.INSTRUCTOR,
        actor_id=INSTRUCTOR_ID,
        offset_ms=0,
    )
    log.add(
        EventType.DDS_CALL_STARTED,
        {
            "call_id": str(CALL),
            "kind": "SERVICE_HEAD",
            "direction": "OUTBOUND",
            "assignment_id": str(LEG),
            "service_type": "FIRE_RESCUE",
            "dialed": "101",
            "endpoint": "BROWSER",
            "room": f"dds-{SESSION_ID}-{CALL}",
            "persona_id": "BRIGADE_101",
            "actor_user_id": str(TRAINEE_ID),
            "selection_reason": "BROWSER_BUTTON",
            "at_offset_ms": 10_000,
        },
        actor_type=ActorType.TRAINEE,
        actor_id=TRAINEE_ID,
        offset_ms=10_000,
    )
    log.add(
        EventType.DDS_CALL_ANSWERED,
        {"call_id": str(CALL), "answered_by": "AI", "at_offset_ms": 14_000},
        actor_type=ActorType.SIMULATION,
        offset_ms=14_000,
    )
    log.add(
        EventType.DDS_CALL_ASSERTION,
        {
            "call_id": str(CALL),
            "turn_id": str(det_uuid("turn-1")),
            "field_path": "address.street",
            "value_ru": "Николаева",
            "matches_snapshot": True,
            "at_offset_ms": 18_000,
        },
        actor_type=ActorType.MODEL,
        offset_ms=18_000,
    )
    proposal = (
        EventType.DDS_CALL_STATUS_PROPOSED,
        {
            "call_id": str(CALL),
            "assignment_id": str(LEG),
            "service_type": "FIRE_RESCUE",
            "status": "ACCEPTED",
            "order_number": None,
            "comment_ru": None,
            "script_after_ms": 15_000,
            "due_offset_ms": 20_000,
            "at_offset_ms": proposal_at_ms,
        },
    )
    confirmation = (
        EventType.DDS_SERVICE_STATUS_SET,
        {
            "assignment_id": str(LEG),
            "service_type": "FIRE_RESCUE",
            "previous_status": "RECEIVED",
            "new_status": "ACCEPTED",
            "trigger": "accept",
            "order_number": None,
            "comment_ru": None,
            "completion_reason": None,
            "source": "TRAINEE",
            "actor_user_id": str(TRAINEE_ID),
            "at_offset_ms": confirm_at_ms,
            "proposed_by_call_id": str(CALL),
        },
    )
    ordered = sorted(
        (
            (proposal_at_ms, proposal, ActorType.SIMULATION, None),
            (confirm_at_ms, confirmation, ActorType.TRAINEE, TRAINEE_ID),
        ),
        key=lambda item: item[0],
    )
    for offset, (event_type, payload), actor, actor_id in ordered:
        log.add(event_type, payload, actor_type=actor, actor_id=actor_id, offset_ms=offset)
    log.add(
        EventType.SESSION_COMPLETED,
        {"at_offset_ms": 600_000, "final_session_state": "COMPLETED", "total_events": 0},
        actor_type=ActorType.SIMULATION,
        offset_ms=600_000,
    )
    return log.build()


def _rule(rule_id: str, evaluator: EvaluatorType, config: dict[str, Any]) -> Any:
    return ScoringRule(
        rule_id=rule_id,
        name_ru=rule_id,
        description_ru=rule_id,
        category=ScoringCategory.WORKFLOW,
        max_points=10,
        critical=False,
        evaluator_type=evaluator,
        config=config,
        applies_to_variants=ON_ONLY,
    )


def _workflow(event_type: str, payload_match: Any, *, after: str | None = None) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "payload_match": payload_match,
        "min_count": 1,
        "max_count": None,
        "required_stage_state": None,
        "must_occur_after": after,
        "points": 10,
        "penalty_if_missing": -5,
        "penalty_per_excess": 0,
    }


CALLED_THE_HEAD = _rule(
    "called_the_101_head",
    EvaluatorType.WORKFLOW_ACTION,
    _workflow("DDS_CALL_STARTED", {"kind": "SERVICE_HEAD", "service_type": "FIRE_RESCUE"}),
)
STATED_THE_STREET = _rule(
    "stated_the_street",
    EvaluatorType.WORKFLOW_ACTION,
    _workflow("DDS_CALL_ASSERTION", {"field_path": "address.street", "matches_snapshot": True}),
)
TRANSCRIBED_THE_STATUS = _rule(
    "transcribed_the_heard_status",
    EvaluatorType.WORKFLOW_ACTION,
    _workflow(
        "DDS_SERVICE_STATUS_SET",
        {"new_status": "ACCEPTED", "source": "TRAINEE"},
        after="DDS_CALL_STATUS_PROPOSED",
    ),
)
TRANSCRIBED_IN_TIME = _rule(
    "transcribed_within_30s",
    EvaluatorType.DEADLINE,
    {
        "from_event_type": "DDS_CALL_STATUS_PROPOSED",
        "to_event_type": "DDS_SERVICE_STATUS_SET",
        "to_payload_match": {"new_status": "ACCEPTED", "source": "TRAINEE"},
        "max_offset_ms": 30_000,
        "points": 10,
        "penalty_if_late": -5,
        "scale": "STEP",
        "linear_zero_ms": None,
    },
)
RULES = (CALLED_THE_HEAD, STATED_THE_STREET, TRANSCRIBED_THE_STATUS, TRANSCRIBED_IN_TIME)


def _by_id(log: tuple[Any, ...]) -> dict[str, Any]:
    report = score(SCENARIO.model_copy(update={"scoring_rules": RULES}), log)
    return {result.rule_id: result for result in report.results}


def test_the_call_rules_score_the_call_events() -> None:
    results = _by_id(call_log())
    for rule in RULES:
        assert results[rule.rule_id].points_awarded == 10, rule.rule_id
        assert results[rule.rule_id].evidence


def test_a_status_set_before_anything_was_heard_is_not_a_transcription() -> None:
    """`must_occur_after` is the transcription's order: set before the head said it ⇒ missing."""
    results = _by_id(call_log(confirm_at_ms=25_000, proposal_at_ms=30_000))
    assert results["transcribed_the_heard_status"].points_awarded == -5


def test_a_late_transcription_loses_the_deadline_points() -> None:
    results = _by_id(call_log(confirm_at_ms=90_000))
    assert results["transcribed_within_30s"].points_awarded == -5


def test_off_scores_every_call_rule_not_applicable() -> None:
    results = _by_id(call_log(brigade_call="OFF"))
    for rule in RULES:
        skipped = results[rule.rule_id]
        assert (skipped.points_awarded, skipped.max_points) == (0.0, 0.0)
        assert [item.note_ru for item in skipped.evidence] == [NOT_APPLICABLE_VARIANT_NOTE_RU]


def test_rescoring_a_call_log_is_equal() -> None:
    """INV 9: scoring reads the stored events only — twice, the same report."""
    version = SCENARIO.model_copy(update={"scoring_rules": RULES})
    assert score(version, call_log()) == score(version, call_log())
