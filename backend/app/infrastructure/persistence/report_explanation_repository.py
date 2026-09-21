"""`SqlAlchemyReportExplanationRepository` over `report_explanations` (§20.10, D11, SPEC §29).

One table, one class holding exactly one `Table`. The isolation is structural, as with the DDS
adapters: this module's imports name `report_explanations` and nothing else, so no holder of it
gains a path to `score_results` / `score_evidence` — half of the epic's "the explanation cannot
write score tables" guarantee (D11).

`upsert` is a single `INSERT … ON CONFLICT (session_id, audience) DO UPDATE`, which is what
`regenerate: true` means at the storage layer. Refusing a *second* generation without that flag is
a product rule the use case applies before calling here (`EXPLANATION_ALREADY_EXISTS`); the
repository does not police it.
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.report_explanation_repository import (
    ExplanationAudience,
    StoredReportExplanation,
)
from app.db.models.reports import ReportExplanation as ReportExplanationRow
from app.domain.common.ids import SessionId
from app.infrastructure.persistence.mappers import (
    report_explanation_from_row,
    report_explanation_row_values,
)

__all__ = ["SqlAlchemyReportExplanationRepository"]

_EXPLANATIONS = ReportExplanationRow.__table__


class SqlAlchemyReportExplanationRepository:
    """`ReportExplanationRepository` over PostgreSQL, bound to one `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, session_id: SessionId, audience: ExplanationAudience
    ) -> StoredReportExplanation | None:
        """The stored explanation for `(session_id, audience)`, or `None`."""
        result = await self._session.execute(
            sa.select(_EXPLANATIONS).where(
                sa.and_(
                    _EXPLANATIONS.c.session_id == UUID(str(session_id)),
                    _EXPLANATIONS.c.audience == audience,
                )
            )
        )
        row = result.mappings().one_or_none()
        return None if row is None else report_explanation_from_row(row)

    async def list_for_session(self, session_id: SessionId) -> list[StoredReportExplanation]:
        """Every stored explanation of `session_id`, ordered by `audience`."""
        result = await self._session.execute(
            sa.select(_EXPLANATIONS)
            .where(_EXPLANATIONS.c.session_id == UUID(str(session_id)))
            .order_by(_EXPLANATIONS.c.audience)
        )
        return [report_explanation_from_row(row) for row in result.mappings()]

    async def upsert(self, explanation: StoredReportExplanation) -> UUID:
        """Insert, or replace the row `UNIQUE (session_id, audience)` already holds."""
        values = report_explanation_row_values(explanation)
        statement = (
            pg_insert(_EXPLANATIONS)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["session_id", "audience"],
                set_={
                    "text_ru": values["text_ru"],
                    "generated_at": values["generated_at"],
                    "llm_provider": values["llm_provider"],
                    "llm_model": values["llm_model"],
                    "score_report_checksum": values["score_report_checksum"],
                },
            )
            .returning(_EXPLANATIONS.c.id)
        )
        result = await self._session.execute(statement)
        return UUID(str(result.scalar_one()))
