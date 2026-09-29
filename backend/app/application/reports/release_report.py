"""`releaseReportToTrainee` — the instructor's visibility flag (E16 R2, D6, D11).

`openapi.yaml` says what this is and is not: "For modes whose
`SessionPolicy.report_visible_to_trainee_before_release` is `false` (`MULTI_TRAINEE`,
`ASSESSMENT`) the trainee's `GET /api/v1/reports/{session_id}` answers `403 REPORT_NOT_RELEASED`
until this command runs. It changes no score: releasing is a visibility flag, not a scoring
operation (D11)."

Three consequences the implementation takes literally:

* **It emits no event.** `x-emits: []`. The session's event log is the record of what happened in
  the simulation (D5); who looked at the report afterwards is not part of that, and appending to
  a `COMPLETED` session's log would change the very input `rescoreSession` replays (SPEC §28).
  The two columns on `simulation_sessions` are the whole state.
* **It is idempotent.** A second call returns the first release unchanged — same `released_at`,
  same `released_by_user_id`. The conditional UPDATE in `SessionRepository.release_report` is
  what makes that true of the *statement*, not of a read-then-write.
* **The session must be `COMPLETED`.** Releasing a report that does not exist yet is
  `409 REPORT_NOT_READY`, the same code and the same reason `getSessionReport` uses.

Releasing a session whose mode is trainee-visible anyway (`SINGLE_ROLE`,
`FULL_CYCLE_SINGLE_TRAINEE`) is permitted and is a no-op for visibility: it records that an
instructor reviewed and published the result, which is a fact worth having even when nothing was
gated on it.

**`CHECKED` (HLD 70 §70.4.6, C2, I3 E4a).** «Проверена» is the instructor's release. It is
materialised on `incidents.card_status` only — still no event, the log is closed — and only where
the projection allows it: the card status is re-derived from the log with `report_released=True`
at the log's last offset, so a card that is `COMPLETED`, `REFUSED`, `NOT_COMPLETED` or
`NOT_NOTIFIED` keeps that status and a merely `WORKED` one becomes `CHECKED`.
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.auth.ownership import require_owner_or_admin
from app.application.ports.audit_changes import NO_AUDIT_CHANGES, AuditChangeCollector
from app.application.ports.clock import Clock
from app.application.ports.session_repository import ReportRelease
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.scoring.rescore_session import ReportNotReadyError
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.ids import SessionId
from app.domain.dds.card_status import CardStatus, fold_card_status
from app.domain.enums import SessionState

__all__ = ["ReleaseReportToTrainee"]


class ReleaseReportToTrainee:
    """`releaseReportToTrainee`: `INSTRUCTOR`/`ADMIN` only (D8; a trainee releasing their own
    report to themselves would make the gate meaningless)."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        *,
        changes: AuditChangeCollector = NO_AUDIT_CHANGES,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._changes = changes  # I7 E43

    async def __call__(self, session_id: SessionId, user: AuthenticatedUser) -> ReportRelease:
        if not user.is_instructor_or_admin:
            raise ForbiddenForRoleError(
                f"the caller may not release the report of session {session_id}: "
                "INSTRUCTOR/ADMIN only"
            )
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            # I5 E39 (Q-E9b-4 а): only the instructor who created the session (or an ADMIN).
            require_owner_or_admin(
                session.created_by_user_id, user, resource=f"the report of session {session_id}"
            )
            if session.state is not SessionState.COMPLETED:
                raise ReportNotReadyError(session_id, session.state)
            released_before = await uow.sessions.get_report_release(session_id) is not None
            release = await uow.sessions.release_report(
                session_id,
                released_by_user_id=user.user_id,
                released_at=self._clock.now(),
            )
            fold = fold_card_status(await uow.events.read(session_id))
            if fold.status_at(fold.horizon_ms or 0, report_released=True) is CardStatus.CHECKED:
                await uow.sessions.set_card_status(session_id, CardStatus.CHECKED)
            await uow.commit()
        self._changes.record("report", "released", released_before, True)
        return release
