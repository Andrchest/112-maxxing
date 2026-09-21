"""`SqlAlchemyScoreRepository` over `score_results` / `score_evidence` (§20.7, D11).

One layer, one module: `app.domain.scoring` never imports this (D2 — the domain owns no I/O, R1),
and `backend/tools/check_imports.py` enforces the direction. ORM rows never leave this module;
every conversion goes through `app.infrastructure.persistence.mappers` (D2).
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.reference import ScoringRule as ScoringRuleRow
from app.db.models.scoring import ScoreEvidence as ScoreEvidenceRow
from app.db.models.scoring import ScoreResult as ScoreResultRow
from app.domain.common.ids import ScenarioVersionId, SessionId
from app.domain.scoring.results import ScoreReport, ScoreResult
from app.infrastructure.persistence.mappers import (
    score_evidence_row_values,
    score_result_from_row,
    score_result_row_values,
)

__all__ = ["SqlAlchemyScoreRepository"]

_RESULTS = ScoreResultRow.__table__
_EVIDENCE = ScoreEvidenceRow.__table__
_RULES = ScoringRuleRow.__table__


class SqlAlchemyScoreRepository:
    """`ScoreRepository` over `score_results` / `score_evidence` (§20.7)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_for_session(
        self,
        session_id: SessionId,
        scenario_version_id: ScenarioVersionId,
        report: ScoreReport,
    ) -> None:
        """Delete then re-insert (§20.7's unique `(session_id, rule_id)` — a re-score replaces).

        `ON DELETE CASCADE` (`fk_score_evidence_score_result_id_score_results`) takes the old
        `score_evidence` rows with the old `score_results` rows; nothing here deletes them a
        second time.
        """
        await self._session.execute(
            sa.delete(_RESULTS).where(_RESULTS.c.session_id == UUID(str(session_id)))
        )
        if not report.results:
            return
        result_rows: list[dict[str, object]] = []
        evidence_rows: list[dict[str, object]] = []
        for result in report.results:
            result_id = uuid4()
            result_rows.append(
                score_result_row_values(result_id, session_id, scenario_version_id, result)
            )
            for evidence in result.evidence:
                evidence_rows.append(score_evidence_row_values(uuid4(), result_id, evidence))
        await self._session.execute(sa.insert(_RESULTS), result_rows)
        if evidence_rows:
            await self._session.execute(sa.insert(_EVIDENCE), evidence_rows)

    async def load_report(self, session_id: SessionId) -> tuple[ScoreResult, ...] | None:
        """Stored `score_results` in rule `order_index` (a join to `scoring_rules`), each with its
        real `score_evidence`."""
        result = await self._session.execute(
            sa.select(_RESULTS, _RULES.c.order_index)
            .select_from(
                _RESULTS.join(
                    _RULES,
                    sa.and_(
                        _RULES.c.scenario_version_id == _RESULTS.c.scenario_version_id,
                        _RULES.c.rule_id == _RESULTS.c.rule_id,
                    ),
                )
            )
            .where(_RESULTS.c.session_id == UUID(str(session_id)))
            .order_by(_RULES.c.order_index)
        )
        rows = result.all()
        if not rows:
            return None

        result_ids = [row.id for row in rows]
        evidence_result = await self._session.execute(
            sa.select(_EVIDENCE)
            .where(_EVIDENCE.c.score_result_id.in_(result_ids))
            .order_by(_EVIDENCE.c.id)
        )
        evidence_by_result: dict[UUID, list[sa.RowMapping]] = defaultdict(list)
        for evidence_row in evidence_result:
            evidence_by_result[evidence_row.score_result_id].append(evidence_row._mapping)

        return tuple(
            score_result_from_row(row._mapping, evidence_by_result.get(row.id, [])) for row in rows
        )
