"""Short independent transactions; never hold a DB connection during model inference."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.reports.ml_audit import AuditReport
from app.db.models.ml_audit import MLAuditJob, MLAuditRun
from app.db.models.session import RoleStage, SimulationSession
from app.domain.common.ids import SessionId

RUNS = cast(sa.Table, MLAuditRun.__table__)
JOBS = cast(sa.Table, MLAuditJob.__table__)
SESSIONS = cast(sa.Table, SimulationSession.__table__)


class SqlAlchemyMLAuditRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def latest(
        self,
        session_id: SessionId,
        input_hash: str,
        rubric_hash: str,
        engine_key: str,
    ) -> AuditReport | None:
        async with self.sessions() as db:
            value = await db.scalar(
                sa.select(RUNS.c.report)
                .where(
                    RUNS.c.session_id == session_id,
                    RUNS.c.input_checksum == input_hash,
                    RUNS.c.rubric_checksum == rubric_hash,
                    RUNS.c.engine_key == engine_key,
                )
                .order_by(RUNS.c.generated_at.desc(), RUNS.c.id.desc())
                .limit(1)
            )
        return None if value is None else AuditReport.model_validate(value)

    async def save(self, session_id: SessionId, engine_key: str, report: AuditReport) -> None:
        if report.run_id is None or report.generated_at is None:
            raise ValueError("persisted audit needs identity and timestamp")
        async with self.sessions.begin() as db:
            await db.execute(
                insert(RUNS)
                .values(
                    id=report.run_id,
                    session_id=session_id,
                    input_checksum=report.input_checksum,
                    rubric_checksum=report.rubric_checksum,
                    engine_key=engine_key,
                    generated_at=report.generated_at,
                    report=report.model_dump(mode="json"),
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )

    async def claim(self) -> tuple[SessionId, UUID] | None:
        now = datetime.now(UTC)
        async with self.sessions.begin() as db:
            # A grace interval lets the final ASR write arrive. Never enqueue aborted sessions.
            candidates = (
                sa.select(SESSIONS.c.id, sa.literal(now))
                .where(
                    SESSIONS.c.state == "COMPLETED",
                    sa.exists(
                        sa.select(RoleStage.id).where(
                            RoleStage.session_id == SESSIONS.c.id,
                            RoleStage.role_type == "OPERATOR_112",
                        )
                    ),
                    SESSIONS.c.completed_at <= now - timedelta(seconds=10),
                    ~sa.exists(
                        sa.select(JOBS.c.session_id).where(
                            JOBS.c.session_id == SESSIONS.c.id,
                        )
                    ),
                )
                .order_by(SESSIONS.c.completed_at)
                .limit(100)
            )
            await db.execute(
                insert(JOBS)
                .from_select(["session_id", "available_at"], candidates)
                .on_conflict_do_nothing(index_elements=["session_id"])
            )
            session_id = await db.scalar(
                sa.select(JOBS.c.session_id)
                .where(
                    JOBS.c.done.is_(False),
                    JOBS.c.attempts < 3,
                    JOBS.c.available_at <= now,
                )
                .order_by(JOBS.c.available_at, JOBS.c.session_id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if session_id is None:
                return None
            token = uuid4()
            await db.execute(
                sa.update(JOBS)
                .where(JOBS.c.session_id == session_id)
                .values(
                    attempts=JOBS.c.attempts + 1,
                    lease_token=token,
                    available_at=now + timedelta(minutes=5),
                )
            )
            return SessionId(session_id), token

    async def finish(self, session_id: SessionId, token: UUID, *, success: bool) -> None:
        async with self.sessions.begin() as db:
            await db.execute(
                sa.update(JOBS)
                .where(
                    JOBS.c.session_id == session_id,
                    JOBS.c.lease_token == token,
                )
                .values(
                    done=success,
                    lease_token=None,
                    available_at=datetime.now(UTC) + timedelta(seconds=60),
                )
            )
