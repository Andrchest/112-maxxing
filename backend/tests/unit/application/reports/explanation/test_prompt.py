"""`build_messages` — the score-explanation prompt builder (SPEC §2, §29; R8, DO item 1)."""

from __future__ import annotations

import inspect

from app.application.reports.explanation.prompt import build_messages
from app.domain.common.ids import ScenarioVersionId, SessionId
from app.domain.enums import EvaluatorType, ScoringCategory
from app.domain.scoring.results import (
    ScoreCategoryTotal,
    ScoreEvidence,
    ScoreReport,
    ScoreResult,
)

from tests.unit.domain.world._builders import det_uuid

SESSION_ID = SessionId(det_uuid("prompt-session"))
SCENARIO_VERSION_ID = ScenarioVersionId(det_uuid("prompt-scenario-version"))


def _report() -> ScoreReport:
    passed = ScoreResult(
        rule_id="rule.victim_fact",
        evaluator_type=EvaluatorType.FACT_OBTAINED,
        category=ScoringCategory.INFORMATION_GATHERING,
        points_awarded=5.0,
        max_points=5.0,
        passed=True,
        critical_failure=False,
        evidence=(ScoreEvidence(event_id=det_uuid("ev1"), note_ru="Факт получен вовремя"),),
    )
    failed = ScoreResult(
        rule_id="rule.address_correct",
        evaluator_type=EvaluatorType.CARD_FIELD_CORRECT,
        category=ScoringCategory.CARD_QUALITY,
        points_awarded=0.0,
        max_points=10.0,
        passed=False,
        critical_failure=True,
        evidence=(ScoreEvidence(event_id=det_uuid("ev2"), note_ru="Адрес не совпадает"),),
    )
    return ScoreReport(
        scenario_version_id=SCENARIO_VERSION_ID,
        session_id=SESSION_ID,
        total_points=5.0,
        total_max_points=15.0,
        by_category=(
            ScoreCategoryTotal(
                category=ScoringCategory.INFORMATION_GATHERING, points_awarded=5.0, max_points=5.0
            ),
            ScoreCategoryTotal(
                category=ScoringCategory.CARD_QUALITY, points_awarded=0.0, max_points=10.0
            ),
        ),
        critical_errors=(failed,),
        results=(passed, failed),
        computed_from_event_count=42,
    )


_RULE_TITLES = {
    "rule.victim_fact": "Получен факт о пострадавшем",
    "rule.address_correct": "Адрес указан верно",
}


def test_the_builder_takes_exactly_the_whitelisted_parameters() -> None:
    """R8's input whitelist, at the type level: nothing else can be passed in by accident."""
    parameters = list(inspect.signature(build_messages).parameters)
    assert parameters == ["report", "rule_titles", "audience"]


def test_returns_a_system_and_a_user_message() -> None:
    messages = build_messages(_report(), _RULE_TITLES, "TRAINEE")
    assert [message.role for message in messages] == ["system", "user"]


def test_the_user_message_cites_points_and_titles_exactly_as_given() -> None:
    messages = build_messages(_report(), _RULE_TITLES, "TRAINEE")
    user_text = messages[1].content
    assert "5.00" in user_text
    assert "15.00" in user_text
    assert "Получен факт о пострадавшем" in user_text
    assert "Адрес указан верно" in user_text
    assert "rule.address_correct" not in user_text  # cited by title, not by id


def test_evidence_notes_are_carried_into_the_summary() -> None:
    messages = build_messages(_report(), _RULE_TITLES, "TRAINEE")
    assert "Адрес не совпадает" in messages[1].content


def test_a_missing_rule_title_falls_back_to_the_bare_rule_id() -> None:
    messages = build_messages(_report(), {}, "TRAINEE")
    assert "rule.victim_fact" in messages[1].content


def test_trainee_and_instructor_get_different_system_prompts() -> None:
    trainee = build_messages(_report(), _RULE_TITLES, "TRAINEE")[0].content
    instructor = build_messages(_report(), _RULE_TITLES, "INSTRUCTOR")[0].content
    assert trainee != instructor
    assert "стажёр" in trainee.lower()
    assert "инструктор" in instructor.lower()


def test_the_system_prompt_forbids_altering_numbers_for_every_audience() -> None:
    for audience in ("TRAINEE", "INSTRUCTOR"):
        system_text = build_messages(_report(), _RULE_TITLES, audience)[0].content
        assert "не придумывай" in system_text.lower() or "не меняй" in system_text.lower()
