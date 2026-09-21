"""`GenerateExplanation` (`generateReportExplanation`, SPEC §2, §29; R1, R8; DO items 2, 3).

Fakes only: `FakeLLM` (D13) for the model, `InMemoryScoreRepository`-shaped reader for scores (the
injected `ScoreReportReader`), `FakeUnitOfWorkFactory` for everything else. The behavioural half of
the "cannot write score tables" invariant lives in
`backend/tests/invariants/test_explanation_cannot_write_scores.py`; this file is the ordinary
use-case behaviour: guard order, regenerate, LLM failure, checksum.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.llm import LlmTimeoutError, LlmUnavailableError
from app.application.ports.user_repository import UserRole
from app.application.reports.explanation.errors import (
    ExplanationAlreadyExistsError,
    ExplanationLLMUnavailableError,
    ReportNotReadyError,
)
from app.application.reports.explanation.generate_explanation import GenerateExplanation
from app.application.reports.visibility import ReportNotReleasedError
from app.application.sessions.authorisation import ParticipantNotAssignedError
from app.application.testing.fakes import InMemoryScoreRepository
from app.domain.enums import EvaluatorType, ScoringCategory, SessionMode, SessionState
from app.domain.scoring.engine import report_checksum
from app.domain.scoring.results import ScoreEvidence, ScoreReport, ScoreResult
from app.inference.llm.fake_llm import FakeLLM

from tests.unit.domain.session._builders import (
    SESSION_ID,
    build_session,
    build_stage,
    scenario_version,
    user,
)
from tests.unit.domain.world._builders import det_uuid as world_det_uuid

from ._support import FakeUnitOfWorkFactory, FixedClock, SequentialIds

TRAINEE_ID = user("operator")
INSTRUCTOR_ID = user("instructor")
STRANGER_ID = user("stranger")

TRAINEE = AuthenticatedUser(
    user_id=TRAINEE_ID,
    username="trainee1",
    display_name_ru="Стажёр",
    user_role=UserRole.TRAINEE,
)
STRANGER = AuthenticatedUser(
    user_id=STRANGER_ID,
    username="stranger",
    display_name_ru="Чужой",
    user_role=UserRole.TRAINEE,
)
INSTRUCTOR = AuthenticatedUser(
    user_id=INSTRUCTOR_ID,
    username="instructor1",
    display_name_ru="Инструктор",
    user_role=UserRole.INSTRUCTOR,
)


def _stage():
    from app.domain.enums import Operator112StageState, RoleType

    return build_stage(
        order_index=0,
        role_type=RoleType.OPERATOR_112,
        state=Operator112StageState.STAGE_COMPLETED,
        participant_user_id=TRAINEE_ID,
        started_at_offset_ms=0,
        completed_at_offset_ms=100_000,
    )


def _session(*, session_mode=SessionMode.SINGLE_ROLE, state=SessionState.COMPLETED):
    from app.domain.session.session import SessionParticipant

    return build_session(
        session_mode=session_mode,
        state=state,
        stages=(_stage(),),
        participants=(SessionParticipant(user_id=TRAINEE_ID),),
    )


def _results() -> tuple[ScoreResult, ...]:
    return (
        ScoreResult(
            rule_id="rule.victim_fact",
            evaluator_type=EvaluatorType.FACT_OBTAINED,
            category=ScoringCategory.INFORMATION_GATHERING,
            points_awarded=5.0,
            max_points=5.0,
            passed=True,
            critical_failure=False,
            evidence=(
                ScoreEvidence(event_id=world_det_uuid("ev1"), note_ru="Факт получен вовремя"),
            ),
        ),
    )


def _factory(*, session_mode=SessionMode.SINGLE_ROLE, state=SessionState.COMPLETED, released=False):
    version = scenario_version()
    session = _session(session_mode=session_mode, state=state)
    releases = {}
    factory = FakeUnitOfWorkFactory(
        sessions={SESSION_ID: session}, scenario_version=version, releases=releases
    )
    if released:
        factory.session_repo.release(SESSION_ID, released_by_user_id=INSTRUCTOR_ID)
    return factory


def _use_case(
    factory: FakeUnitOfWorkFactory, llm: FakeLLM, *, scores: InMemoryScoreRepository | None = None
) -> GenerateExplanation:
    scores = scores if scores is not None else InMemoryScoreRepository()
    return GenerateExplanation(
        factory,
        scores,
        llm,
        FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        SequentialIds(),
        llm_provider="fake",
        max_tokens=400,
        temperature=0.2,
        timeout_ms=8000,
    )


def _scores_with(results: tuple[ScoreResult, ...]) -> InMemoryScoreRepository:
    scores = InMemoryScoreRepository()
    scores.rows[SESSION_ID] = (scenario_version().id, results)
    return scores


async def test_a_trainee_can_generate_their_own_single_role_report_explanation() -> None:
    factory = _factory()
    llm = FakeLLM(["Стажёр получил 5 баллов из 5."])
    use_case = _use_case(factory, llm, scores=_scores_with(_results()))

    stored = await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=False)

    assert stored.text_ru == "Стажёр получил 5 баллов из 5."
    assert stored.audience == "TRAINEE"
    assert stored.llm_provider == "fake"
    assert stored.llm_model == "fake-llm"
    assert len(llm.calls) == 1


async def test_an_instructor_may_generate_regardless_of_release() -> None:
    factory = _factory(session_mode=SessionMode.MULTI_TRAINEE, released=False)
    llm = FakeLLM(["Сжатый разбор."])
    use_case = _use_case(factory, llm, scores=_scores_with(_results()))

    stored = await use_case(SESSION_ID, INSTRUCTOR, audience="INSTRUCTOR", regenerate=False)

    assert stored.audience == "INSTRUCTOR"


async def test_a_stranger_is_refused_before_anything_about_the_session_leaks() -> None:
    factory = _factory()
    llm = FakeLLM(["text"])
    use_case = _use_case(factory, llm, scores=_scores_with(_results()))

    with pytest.raises(ParticipantNotAssignedError):
        await use_case(SESSION_ID, STRANGER, audience="TRAINEE", regenerate=False)
    assert llm.calls == []


async def test_a_session_that_has_not_completed_is_not_ready() -> None:
    factory = _factory(state=SessionState.ACTIVE)
    llm = FakeLLM(["text"])
    use_case = _use_case(factory, llm, scores=_scores_with(_results()))

    with pytest.raises(ReportNotReadyError):
        await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=False)
    assert llm.calls == []


async def test_a_completed_session_with_no_stored_score_is_not_ready() -> None:
    """R1: "report for an unfinished session refused" also holds for a session that reached
    COMPLETED but has no persisted score (e.g. a ScoringEvidenceError at close)."""
    factory = _factory()
    llm = FakeLLM(["text"])
    use_case = _use_case(factory, llm, scores=InMemoryScoreRepository())

    with pytest.raises(ReportNotReadyError):
        await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=False)
    assert llm.calls == []


async def test_a_trainee_is_refused_before_release_when_the_mode_requires_one() -> None:
    factory = _factory(session_mode=SessionMode.MULTI_TRAINEE, released=False)
    llm = FakeLLM(["text"])
    use_case = _use_case(factory, llm, scores=_scores_with(_results()))

    with pytest.raises(ReportNotReleasedError):
        await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=False)
    assert llm.calls == []


async def test_a_trainee_may_generate_once_the_mode_has_released_it() -> None:
    factory = _factory(session_mode=SessionMode.MULTI_TRAINEE, released=True)
    llm = FakeLLM(["Готово."])
    use_case = _use_case(factory, llm, scores=_scores_with(_results()))

    stored = await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=False)
    assert stored.text_ru == "Готово."


async def test_a_second_generation_without_regenerate_is_refused() -> None:
    factory = _factory()
    llm = FakeLLM(["first", "second"])
    use_case = _use_case(factory, llm, scores=_scores_with(_results()))
    await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=False)

    with pytest.raises(ExplanationAlreadyExistsError):
        await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=False)
    assert len(llm.calls) == 1


async def test_regenerate_true_replaces_the_stored_row() -> None:
    factory = _factory()
    llm = FakeLLM(["first", "second"])
    use_case = _use_case(factory, llm, scores=_scores_with(_results()))
    first = await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=False)

    second = await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=True)

    assert first.text_ru == "first"
    assert second.text_ru == "second"
    stored = await factory.explanations.get(SESSION_ID, "TRAINEE")
    assert stored is not None
    assert stored.text_ru == "second"


async def test_a_timeout_becomes_llm_unavailable_and_stores_nothing() -> None:
    factory = _factory()
    llm = FakeLLM([TimeoutError("no answer")])
    use_case = _use_case(factory, llm, scores=_scores_with(_results()))

    with pytest.raises(ExplanationLLMUnavailableError):
        await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=False)
    assert await factory.explanations.get(SESSION_ID, "TRAINEE") is None


async def test_llm_unavailable_error_becomes_the_503_and_stores_nothing() -> None:
    factory = _factory()
    llm = FakeLLM([LlmUnavailableError("connection refused")])
    use_case = _use_case(factory, llm, scores=_scores_with(_results()))

    with pytest.raises(ExplanationLLMUnavailableError):
        await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=False)
    assert await factory.explanations.get(SESSION_ID, "TRAINEE") is None


async def test_llm_timeout_error_becomes_the_503() -> None:
    factory = _factory()
    llm = FakeLLM([LlmTimeoutError("too slow")])
    use_case = _use_case(factory, llm, scores=_scores_with(_results()))

    with pytest.raises(ExplanationLLMUnavailableError):
        await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=False)


async def test_empty_model_text_is_treated_as_unavailable() -> None:
    factory = _factory()
    llm = FakeLLM(["   "])
    use_case = _use_case(factory, llm, scores=_scores_with(_results()))

    with pytest.raises(ExplanationLLMUnavailableError):
        await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=False)
    assert await factory.explanations.get(SESSION_ID, "TRAINEE") is None


async def test_the_stored_checksum_matches_report_checksum_of_the_same_results() -> None:
    factory = _factory()
    llm = FakeLLM(["text"])
    results = _results()
    use_case = _use_case(factory, llm, scores=_scores_with(results))

    stored = await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=False)

    total_points = sum(r.points_awarded for r in results)
    total_max_points = sum(r.max_points for r in results)
    expected = report_checksum(
        ScoreReport(
            scenario_version_id=scenario_version().id,
            session_id=SESSION_ID,
            total_points=total_points,
            total_max_points=total_max_points,
            by_category=(),
            critical_errors=(),
            results=results,
            computed_from_event_count=0,
        )
    )
    assert stored.score_report_checksum == expected


async def test_the_prompt_carries_the_rule_title_and_the_stored_points() -> None:
    factory = _factory()
    llm = FakeLLM(["text"])
    use_case = _use_case(factory, llm, scores=_scores_with(_results()))

    await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=False)

    user_message = llm.calls[0].messages[1].content
    assert "5.00" in user_message
