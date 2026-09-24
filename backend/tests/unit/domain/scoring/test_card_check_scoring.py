"""Card-check rules are non-applicable when `dds_card_check: OFF` (I3 E5b, HLD 70 §70.2.5; C1).

A scenario scores «Отметить ошибку в карточке» with ordinary rules over `DDS_CARD_ISSUE_FLAGGED`
tagged `applies_to_variants: {dds_card_check: [ON]}`. Under the default `OFF` such a rule yields the
zero/zero `ScoreResult` that changes neither totals nor critical errors — a trainee is never
penalised for not flagging a card the variant does not let them flag. Under `ON` it scores.
"""

from __future__ import annotations

from typing import Any

from app.domain.enums import ActorType, EvaluatorType, ScoringCategory
from app.domain.events.types import EventType
from app.domain.scoring.engine import NOT_APPLICABLE_VARIANT_NOTE_RU, score
from app.domain.scoring.rules import ScoringRule

from tests.unit.domain.scoring._event_log_builders import TRAINEE_ID, LogBuilder, det_uuid
from tests.unit.domain.scoring.test_memo_scoring import MEMO, SCENARIO, memo_log

FLAG_THE_HOUSE = ScoringRule(
    rule_id="card_check_flags_the_house",
    name_ru="ДДС отметила ошибку в номере дома",
    description_ru="При проверке карточки ДДС отмечает неверный номер дома.",
    category=ScoringCategory.WORKFLOW,
    max_points=6,
    critical=True,
    evaluator_type=EvaluatorType.WORKFLOW_ACTION,
    config={
        "event_type": "DDS_CARD_ISSUE_FLAGGED",
        "payload_match": {"field_path": "address.house", "issue_kind": ["WRONG", "CONTRADICTION"]},
        "min_count": 1,
        "max_count": 1,
        "required_stage_state": None,
        "must_occur_after": None,
        "points": 6,
        "penalty_if_missing": -6,
        "penalty_per_excess": 0,
    },
    applies_to_variants={"dds_card_check": ("ON",)},
)


def _log(card_check: str, *, flagged: bool) -> tuple[Any, ...]:
    """E5a's memo log, recorded under `card_check`, optionally with one flag at 30 s."""
    base = memo_log()
    log = LogBuilder()
    for event in base:
        payload = dict(event.payload)
        if event.event_type is EventType.SESSION_CREATED:
            payload["variants"] = {**MEMO, "dds_card_check": card_check}
        log.add(
            event.event_type,
            payload,
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            offset_ms=event.monotonic_offset_ms,
        )
        if (
            flagged
            and event.event_type is EventType.DDS_SERVICE_STATUS_SET
            and event.payload["new_status"] == "ACCEPTED"
        ):
            log.add(
                EventType.DDS_CARD_ISSUE_FLAGGED,
                {
                    "assignment_id": event.payload["assignment_id"],
                    "field_path": "address.house",
                    "issue_kind": "WRONG",
                    "comment_ru": "Номер дома не совпадает",
                    "actor_user_id": str(TRAINEE_ID),
                    "at_offset_ms": event.monotonic_offset_ms,
                },
                actor_type=ActorType.TRAINEE,
                actor_id=TRAINEE_ID,
                offset_ms=event.monotonic_offset_ms,
                name=f"flag:{det_uuid('flag')}",
            )
    return log.build()


def _version() -> Any:
    return SCENARIO.model_copy(update={"scoring_rules": (FLAG_THE_HOUSE,)})


def test_a_card_check_rule_is_zero_over_zero_when_card_check_is_off() -> None:
    report = score(_version(), _log("OFF", flagged=False))
    (result,) = report.results
    assert (result.points_awarded, result.max_points) == (0.0, 0.0)
    assert not result.critical_failure
    assert [item.note_ru for item in result.evidence] == [NOT_APPLICABLE_VARIANT_NOTE_RU]
    assert report.critical_errors == ()
    assert (report.total_points, report.total_max_points) == (0.0, 0.0)


def test_a_card_check_rule_scores_when_card_check_is_on() -> None:
    flagged = score(_version(), _log("ON", flagged=True))
    assert flagged.results[0].points_awarded == 6
    assert flagged.results[0].max_points == 6

    missed = score(_version(), _log("ON", flagged=False))
    assert missed.results[0].points_awarded < 6
    assert missed.results[0].critical_failure
