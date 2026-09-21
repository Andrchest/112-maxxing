"""`getReportExplanation` (`openapi.yaml` `GET /api/v1/reports/{session_id}/explanation`,
SPEC §2, §29; D11).

A plain read of the stored row, gated by the same visibility rule as `generateReportExplanation`
and `getSessionReport` (`app.application.reports.visibility.report_visibility`) — a trainee who
may not read the report at all may not read its explanation either, released or not (R3). `404`
when nothing was ever generated for `(session_id, audience)`.

A stale explanation — its `score_report_checksum` no longer equal to the currently stored report's
(a rescore happened after it was generated) — is still returned, with its own checksum: DO item 2
says the client compares and shows "устарело" itself; this use case never silently regenerates.
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.report_explanation_repository import (
    ExplanationAudience,
    StoredReportExplanation,
)
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.reports.visibility import report_visibility
from app.application.sessions.authorisation import resolve_participant
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.errors import DomainError
from app.domain.common.ids import SessionId

__all__ = ["ExplanationNotFoundError", "GetExplanation"]


class ExplanationNotFoundError(DomainError):
    """No explanation stored for `(session_id, audience)` (`404 NOT_FOUND`)."""

    code = "NOT_FOUND"

    def __init__(self, session_id: SessionId, audience: str) -> None:
        self.session_id = session_id
        self.audience = audience
        super().__init__(f"session {session_id} has no stored {audience} explanation")


class GetExplanation:
    """`getReportExplanation`."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, session_id: SessionId, user: AuthenticatedUser, *, audience: ExplanationAudience
    ) -> StoredReportExplanation:
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)

            if not user.is_instructor_or_admin:
                resolve_participant(session, user)
            release = await uow.sessions.get_report_release(session_id)
            report_visibility(session, user, released=release is not None)

            stored = await uow.report_explanations.get(session_id, audience)
            await uow.commit()
        if stored is None:
            raise ExplanationNotFoundError(session_id, audience)
        return stored
