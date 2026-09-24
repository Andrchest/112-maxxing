"""The ДДС → 112 call scores REQ-5332's checklist with the existing evaluators (I3 E6d, HLD
`80-telephony.md` §80.3.4, §80.8.1 (4)).

The scoring fixtures the E6d row names: each checklist item the ДДС covered on a call to 112 is a
`DDS_CALL_ASSERTION` (MODEL) with a checklist `field_path` — `call.self_identification`,
`address.*`, `call.card_reference`, `incident.change` — and a `WORKFLOW_ACTION` rule per item turns
it into points; an item never said earns the rule's `penalty_if_missing`. A missing
self-identification is therefore a penalty, through the scoring path every other rule takes (no new
evaluator). Every rule is `applies_to_variants: {dds_brigade_call: [ON]}`: an `OFF` session scores
them not applicable.

`CHECKLIST_TABLE` is the fixture table: item present / missing → assertion → rule points.
"""

from __future__ import annotations

from typing import Any

import pytest
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
CALL = det_uuid("call-112")
ON_ONLY = {"dds_brigade_call": ("ON",)}
POINTS = 10
PENALTY = -10

#: `(field_path, matches_snapshot, value_ru)` of each REQ-5332 item, in the memo's order.
ITEMS: dict[str, tuple[str, bool, str]] = {
    "self_identification": (
        "call.self_identification",
        True,
        "Дежурный пожарно-спасательной службы Иванов",
    ),
    "address": ("address.street", True, "Академика Королёва"),
    "card_reference": ("call.card_reference", True, "36814851"),
    "change": ("incident.change", False, "Огонь перекинулся на гараж, нужна полиция"),
}


def _variants(brigade_call: str) -> dict[str, str]:
    return {
        "card_source": "GENERATED_CARD",
        "dds_mode": "MEMO_STATUSES",
        "dds_card_check": "OFF",
        "dds_brigade_call": brigade_call,
    }


def call_112_log(
    *,
    brigade_call: str = "ON",
    covered: tuple[str, ...] = tuple(ITEMS),
    wrong_address: bool = False,
    wrong_card_number: bool = False,
) -> tuple[Any, ...]:
    """A memo run with the phone: the ДДС calls 112 at 10 s, the AI operator answers at 14 s, and
    the ДДС covers exactly the `covered` items, one turn each — plus, with `wrong_address`, an
    address the code matched to no snapshot value, and with `wrong_card_number`, a card number
    that is not the card's (I4 E21)."""
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
            "kind": "OPERATOR_112",
            "direction": "OUTBOUND",
            "assignment_id": None,
            "service_type": None,
            "dialed": "112",
            "endpoint": "BROWSER",
            "room": f"dds-{SESSION_ID}-{CALL}",
            "persona_id": "OPERATOR_112",
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
    offset = 18_000
    for name in covered:
        field_path, matches, value = ITEMS[name]
        log.add(
            EventType.DDS_CALL_ASSERTION,
            {
                "call_id": str(CALL),
                "turn_id": str(det_uuid(f"turn-{name}")),
                "field_path": field_path,
                "value_ru": value,
                "matches_snapshot": matches,
                "at_offset_ms": offset,
            },
            actor_type=ActorType.MODEL,
            offset_ms=offset,
        )
        offset += 4_000
    if wrong_address:
        log.add(
            EventType.DDS_CALL_ASSERTION,
            {
                "call_id": str(CALL),
                "turn_id": str(det_uuid("turn-wrong-address")),
                "field_path": "address.street",
                "value_ru": "улица Ленина",
                "matches_snapshot": False,
                "at_offset_ms": offset,
            },
            actor_type=ActorType.MODEL,
            offset_ms=offset,
        )
    if wrong_card_number:
        log.add(
            EventType.DDS_CALL_ASSERTION,
            {
                "call_id": str(CALL),
                "turn_id": str(det_uuid("turn-wrong-card-number")),
                "field_path": "call.card_reference",
                "value_ru": "11112222",
                "matches_snapshot": False,
                "at_offset_ms": offset,
            },
            actor_type=ActorType.MODEL,
            offset_ms=offset,
        )
    log.add(
        EventType.DDS_CALL_ENDED,
        {"call_id": str(CALL), "reason": "HANGUP", "duration_ms": 30_000, "at_offset_ms": 44_000},
        actor_type=ActorType.TRAINEE,
        actor_id=TRAINEE_ID,
        offset_ms=44_000,
    )
    log.add(
        EventType.SESSION_COMPLETED,
        {"at_offset_ms": 600_000, "final_session_state": "COMPLETED", "total_events": 0},
        actor_type=ActorType.SIMULATION,
        offset_ms=600_000,
    )
    return log.build()


def _rule(rule_id: str, payload_match: dict[str, Any], event_type: str) -> ScoringRule:
    return ScoringRule(
        rule_id=rule_id,
        name_ru=rule_id,
        description_ru=rule_id,
        category=ScoringCategory.WORKFLOW,
        max_points=POINTS,
        critical=False,
        evaluator_type=EvaluatorType.WORKFLOW_ACTION,
        config={
            "event_type": event_type,
            "payload_match": payload_match,
            "min_count": 1,
            "max_count": None,
            "required_stage_state": None,
            "must_occur_after": "DDS_CALL_STARTED",
            "points": POINTS,
            "penalty_if_missing": PENALTY,
            "penalty_per_excess": 0,
        },
        applies_to_variants=ON_ONLY,
    )


CALLED_112 = _rule("called_112", {"kind": "OPERATOR_112", "dialed": "112"}, "DDS_CALL_STARTED")
#: One rule per REQ-5332 item. The address is any `address.*` path that matched the snapshot
#: (`payload_match`'s list value is "any of", I3 E5b).
CHECKLIST_RULES: dict[str, ScoringRule] = {
    "self_identification": _rule(
        "introduced_self_to_112",
        {"field_path": "call.self_identification"},
        "DDS_CALL_ASSERTION",
    ),
    "address": _rule(
        "named_the_address_to_112",
        {
            "field_path": ["address.street", "address.house", "address.city"],
            "matches_snapshot": True,
        },
        "DDS_CALL_ASSERTION",
    ),
    "card_reference": _rule(
        "named_the_routed_card_to_112",
        # I4 E21: the number said is the card's «Происшествие N» number.
        {"field_path": "call.card_reference", "matches_snapshot": True},
        "DDS_CALL_ASSERTION",
    ),
    "change": _rule(
        "reported_the_change_to_112",
        {"field_path": "incident.change"},
        "DDS_CALL_ASSERTION",
    ),
}
RULES = (CALLED_112, *CHECKLIST_RULES.values())

#: The fixture table: `(item, present?) → the rule's points`.
CHECKLIST_TABLE: list[tuple[str, bool, float]] = [
    (item, present, POINTS if present else PENALTY) for item in ITEMS for present in (True, False)
]


def _by_id(log: tuple[Any, ...]) -> dict[str, Any]:
    report = score(SCENARIO.model_copy(update={"scoring_rules": RULES}), log)
    return {result.rule_id: result for result in report.results}


def test_every_covered_item_earns_its_rule_points() -> None:
    results = _by_id(call_112_log())
    for rule in RULES:
        assert results[rule.rule_id].points_awarded == POINTS, rule.rule_id
        assert results[rule.rule_id].evidence


@pytest.mark.parametrize(("item", "present", "points"), CHECKLIST_TABLE)
def test_the_checklist_table(item: str, present: bool, points: float) -> None:
    """Item present / missing → its `DDS_CALL_ASSERTION` → the rule's points; the other items'
    rules are untouched."""
    covered = tuple(name for name in ITEMS if name != item or present)
    results = _by_id(call_112_log(covered=covered))
    assert results[CHECKLIST_RULES[item].rule_id].points_awarded == points
    for other, rule in CHECKLIST_RULES.items():
        if other != item:
            assert results[rule.rule_id].points_awarded == POINTS, other


def test_a_missing_self_identification_is_a_penalty() -> None:
    results = _by_id(call_112_log(covered=("address", "card_reference", "change")))
    introduced = results["introduced_self_to_112"]
    assert introduced.points_awarded == PENALTY < 0


def test_an_address_that_matches_no_snapshot_value_earns_nothing() -> None:
    """A stated address the code did not match (`matches_snapshot: false`) is not the address."""
    log = call_112_log(covered=("self_identification",), wrong_address=True)
    results = _by_id(log)
    assert results["named_the_address_to_112"].points_awarded == PENALTY


def test_a_card_number_that_is_not_the_cards_earns_nothing() -> None:
    """I4 E21: `call.card_reference` with a number other than the card's (`matches_snapshot:
    false`) does not name the routed card."""
    log = call_112_log(covered=("self_identification",), wrong_card_number=True)
    results = _by_id(log)
    assert results["named_the_routed_card_to_112"].points_awarded == PENALTY


def test_off_scores_every_112_rule_not_applicable() -> None:
    results = _by_id(call_112_log(brigade_call="OFF"))
    for rule in RULES:
        skipped = results[rule.rule_id]
        assert (skipped.points_awarded, skipped.max_points) == (0.0, 0.0)
        assert [item.note_ru for item in skipped.evidence] == [NOT_APPLICABLE_VARIANT_NOTE_RU]


def test_rescoring_a_112_call_log_is_equal() -> None:
    """INV 9: scoring reads the stored events only — twice, the same report."""
    version = SCENARIO.model_copy(update={"scoring_rules": RULES})
    assert score(version, call_112_log()) == score(version, call_112_log())
