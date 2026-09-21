"""`SqlAlchemyScoreRepository` against real PostgreSQL (§20.7, D11, epic E15-B, CHANGE item 7).

Round-trip, replace-on-rescore and the `exactly_one` evidence CHECK — the three things a fake
cannot prove.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import pytest
import sqlalchemy as sa
from app.domain.common.ids import ScenarioVersionId, SessionId
from app.domain.enums import EvaluatorType, ScoringCategory
from app.domain.events.session_event import SessionEvent
from app.domain.scoring.results import ScoreCategoryTotal, ScoreEvidence, ScoreReport, ScoreResult
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

RULE_ID = "fact_victim_inside"
"""Demo scenario rule #1 (`FACT_OBTAINED`, `scenarios/examples/apartment-fire/v1.yaml`)."""

OTHER_RULE_ID = "card_house_correct"
"""Demo scenario rule #2 (`CARD_FIELD_CORRECT`) — a second rule for the multi-row assertions."""


def _report(
    session_id: SessionId,
    scenario_version_id: ScenarioVersionId,
    event: SessionEvent,
    *,
    points: float = 10.0,
) -> ScoreReport:
    result = ScoreResult(
        rule_id=RULE_ID,
        evaluator_type=EvaluatorType.FACT_OBTAINED,
        category=ScoringCategory.INFORMATION_GATHERING,
        points_awarded=points,
        max_points=10.0,
        passed=points > 0,
        critical_failure=points <= 0,
        evidence=(ScoreEvidence(event_id=event.id, seq_no=event.seq_no, note_ru="доставлен факт"),),
    )
    return ScoreReport(
        scenario_version_id=scenario_version_id,
        session_id=session_id,
        total_points=points,
        total_max_points=10.0,
        by_category=(
            ScoreCategoryTotal(
                category=ScoringCategory.INFORMATION_GATHERING,
                points_awarded=points,
                max_points=10.0,
            ),
        ),
        critical_errors=(result,) if result.critical_failure else (),
        results=(result,),
        computed_from_event_count=1,
    )


async def test_replace_then_load_round_trips_the_report(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    demo_version_id: ScenarioVersionId,
    seeded_session: SessionId,
    seeded_event: SessionEvent,
) -> None:
    report = _report(seeded_session, demo_version_id, seeded_event)
    async with unit_of_work() as uow:
        await uow.scores.replace_for_session(seeded_session, demo_version_id, report)
        await uow.commit()

    async with unit_of_work() as uow:
        loaded = await uow.scores.load_report(seeded_session)
        await uow.commit()

    assert loaded is not None
    assert len(loaded) == 1
    stored = loaded[0]
    assert stored.rule_id == RULE_ID
    assert stored.evaluator_type is EvaluatorType.FACT_OBTAINED
    assert stored.category is ScoringCategory.INFORMATION_GATHERING
    assert stored.points_awarded == 10.0
    assert stored.max_points == 10.0
    assert stored.passed is True
    assert stored.critical_failure is False
    assert len(stored.evidence) == 1
    assert stored.evidence[0].event_id == seeded_event.id
    assert stored.evidence[0].seq_no == seeded_event.seq_no
    assert stored.evidence[0].note_ru == "доставлен факт"
    assert stored.evidence[0].card_revision_id is None
    assert stored.evidence[0].snapshot_id is None


async def test_load_report_of_a_never_scored_session_is_none(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork], seeded_session: SessionId
) -> None:
    async with unit_of_work() as uow:
        loaded = await uow.scores.load_report(seeded_session)
        await uow.commit()
    assert loaded is None


async def test_replace_for_session_deletes_the_previous_rows_first(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    demo_version_id: ScenarioVersionId,
    seeded_session: SessionId,
    seeded_event: SessionEvent,
    migrated_engine: AsyncEngine,
) -> None:
    """A re-score replaces — it does not duplicate (§20.7's `uq_score_results_session_rule`)."""
    first = _report(seeded_session, demo_version_id, seeded_event, points=10.0)
    second = _report(seeded_session, demo_version_id, seeded_event, points=0.0)

    async with unit_of_work() as uow:
        await uow.scores.replace_for_session(seeded_session, demo_version_id, first)
        await uow.commit()
    async with unit_of_work() as uow:
        await uow.scores.replace_for_session(seeded_session, demo_version_id, second)
        await uow.commit()

    async with migrated_engine.connect() as connection:
        rows = (
            await connection.execute(
                sa.text(
                    "SELECT points_awarded, passed FROM score_results"
                    " WHERE session_id = :session_id AND rule_id = :rule_id"
                ),
                {"session_id": UUID(str(seeded_session)), "rule_id": RULE_ID},
            )
        ).all()
    assert len(rows) == 1, "replace_for_session must not leave the old row behind"
    assert float(rows[0].points_awarded) == 0.0
    assert rows[0].passed is False


async def test_replace_for_session_writes_one_evidence_row_per_result(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    demo_version_id: ScenarioVersionId,
    seeded_session: SessionId,
    seeded_event: SessionEvent,
) -> None:
    fact_result = ScoreResult(
        rule_id=RULE_ID,
        evaluator_type=EvaluatorType.FACT_OBTAINED,
        category=ScoringCategory.INFORMATION_GATHERING,
        points_awarded=10.0,
        max_points=10.0,
        passed=True,
        critical_failure=False,
        evidence=(ScoreEvidence(event_id=seeded_event.id, note_ru="факт получен"),),
    )
    card_result = ScoreResult(
        rule_id=OTHER_RULE_ID,
        evaluator_type=EvaluatorType.CARD_FIELD_CORRECT,
        category=ScoringCategory.CARD_QUALITY,
        points_awarded=-4.0,
        max_points=8.0,
        passed=False,
        critical_failure=True,
        evidence=(
            ScoreEvidence(event_id=seeded_event.id, note_ru="дом указан неверно"),
            ScoreEvidence(event_id=seeded_event.id, note_ru="запись поля"),
        ),
    )
    report = ScoreReport(
        scenario_version_id=demo_version_id,
        session_id=seeded_session,
        total_points=6.0,
        total_max_points=18.0,
        by_category=(),
        critical_errors=(card_result,),
        results=(fact_result, card_result),
        computed_from_event_count=1,
    )

    async with unit_of_work() as uow:
        await uow.scores.replace_for_session(seeded_session, demo_version_id, report)
        await uow.commit()

    async with unit_of_work() as uow:
        loaded = await uow.scores.load_report(seeded_session)
        await uow.commit()

    assert loaded is not None
    by_rule = {result.rule_id: result for result in loaded}
    assert len(by_rule[RULE_ID].evidence) == 1
    assert len(by_rule[OTHER_RULE_ID].evidence) == 2
    # Rule order (`scoring_rules.order_index`): `fact_victim_inside` #1, `card_house_correct` #2.
    assert [result.rule_id for result in loaded] == [RULE_ID, OTHER_RULE_ID]


async def test_score_evidence_rejects_a_row_with_no_reference_set(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    demo_version_id: ScenarioVersionId,
    seeded_session: SessionId,
    migrated_engine: AsyncEngine,
) -> None:
    """§20.7's `exactly_one` CHECK is a second line of defence behind the domain validator: a row
    that reached SQL with all three references null (bypassing `ScoreEvidence`'s own validation,
    e.g. from a future caller that writes raw SQL) is still refused at the database."""
    async with unit_of_work() as uow:
        result_id = (
            await uow.session.execute(
                sa.text(
                    "INSERT INTO score_results"
                    " (session_id, scenario_version_id, rule_id, evaluator_type, category,"
                    "  points_awarded, max_points, passed, critical_failure)"
                    " VALUES (:session_id, :scenario_version_id, :rule_id, 'FACT_OBTAINED',"
                    "  'INFORMATION_GATHERING', 0, 10, true, false) RETURNING id"
                ),
                {
                    "session_id": UUID(str(seeded_session)),
                    "scenario_version_id": UUID(str(demo_version_id)),
                    "rule_id": RULE_ID,
                },
            )
        ).scalar_one()
        with pytest.raises(IntegrityError, match="exactly_one"):
            await uow.session.execute(
                sa.text(
                    "INSERT INTO score_evidence (score_result_id, note_ru)"
                    " VALUES (:score_result_id, 'no reference at all')"
                ),
                {"score_result_id": result_id},
            )
        await uow.rollback()
