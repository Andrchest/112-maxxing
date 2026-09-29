"""A separate store; no API to mutate official scores or session events."""

from typing import Protocol
from uuid import UUID

from app.application.reports.ml_audit import AuditReport
from app.domain.common.ids import SessionId


class MLAuditRepository(Protocol):
    async def latest(
        self,
        session_id: SessionId,
        input_hash: str,
        rubric_hash: str,
        engine_key: str,
    ) -> AuditReport | None: ...

    async def save(self, session_id: SessionId, engine_key: str, report: AuditReport) -> None: ...

    async def claim(self) -> tuple[SessionId, UUID] | None:
        """Discover completed sessions and lease one (at most three automatic attempts)."""
        ...

    async def finish(self, session_id: SessionId, token: UUID, *, success: bool) -> None: ...
