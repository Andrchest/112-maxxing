"""Authorised cache access, immutable result history and restart-safe automatic audits."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.ml_audit_repository import MLAuditRepository
from app.application.ports.user_repository import UserRole
from app.application.reports.assemble_report import GetSessionReport, SessionReportView
from app.application.reports.ml_audit import (
    AuditReport,
    MLAuditor,
    Rubric,
    input_checksum,
    report_sources,
    rubric_checksum,
)
from app.domain.common.ids import SessionId, UserId

logger = logging.getLogger(__name__)

# Internal worker identity only; no token is issued and no HTTP caller can select it.
_SYSTEM = AuthenticatedUser(
    user_id=UserId(UUID(int=0)),
    username="ml-audit-worker",
    display_name_ru="ML-аудит",
    user_role=UserRole.ADMIN,
)


class MLAuditService:
    def __init__(
        self,
        reader: GetSessionReport,
        repository: MLAuditRepository,
        auditor: MLAuditor,
        rubric_for: Callable[[str], Rubric],
        *,
        engine_key: str,
        available: bool,
    ) -> None:
        self.reader = reader
        self.repository = repository
        self.auditor = auditor
        self.rubric_for = rubric_for
        self.engine_key = engine_key
        self.available = available

    async def _cached(self, view: SessionReportView, rubric: Rubric) -> AuditReport | None:
        sources, context = report_sources(view)
        # Scope the cache by the EXACT visible input. An instructor's richer report cannot
        # be served to a DDS-only trainee, even when they share the same session_id.
        return await self.repository.latest(
            view.session_id,
            input_checksum(sources, context),
            rubric_checksum(rubric),
            self.engine_key,
        )

    async def get(self, session_id: SessionId, user: AuthenticatedUser) -> AuditReport | None:
        view = await self.reader(session_id, user)  # Authorisation BEFORE cache read.
        rubric = self.rubric_for(str(view.score_report.scenario_version_id))
        return await self._cached(view, rubric)

    async def generate(
        self,
        session_id: SessionId,
        user: AuthenticatedUser,
        *,
        regenerate: bool = False,
    ) -> AuditReport:
        view = await self.reader(session_id, user)
        rubric = self.rubric_for(str(view.score_report.scenario_version_id))
        cached = await self._cached(view, rubric)
        if cached is not None and cached.score_percent is not None and not regenerate:
            return cached
        sources, context = report_sources(view)
        result = await self.auditor.evaluate(
            rubric,
            sources,
            context,
            provider_available=self.available,
        )
        result = result.model_copy(update={"run_id": uuid4(), "generated_at": datetime.now(UTC)})
        await self.repository.save(session_id, self.engine_key, result)
        return result


class MLAuditWorker:
    def __init__(self, service: MLAuditService, *, interval_seconds: float = 5) -> None:
        self.service = service
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def tick(self) -> bool:
        job = await self.service.repository.claim()
        if job is None:
            return False
        session_id, token = job
        success = False
        try:
            result = await self.service.generate(session_id, _SYSTEM)
            success = result.score_percent is not None
        except Exception:
            # No prompt, source text, personal data or exception body in the log.
            logger.warning("ML audit failed for session %s", session_id)
        finally:
            await self.service.repository.finish(session_id, token, success=success)
        return True

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                logger.warning("ML audit worker iteration failed")
            await asyncio.sleep(self.interval_seconds)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="ml-audit-worker")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
