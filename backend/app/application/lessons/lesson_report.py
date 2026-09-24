"""`getLessonReport` — the N card reports of an ended lesson plus their weighted sum
(HLD 70 §70.3.6, §70.3.7; D11).

No new evaluator and no recomputation: each card's report is the existing `getSessionReport` of
its session, read — with its own visibility and release rules — for the caller, so a trainee sees
a card's report exactly when they could open that session's report on its own (`403
REPORT_NOT_RELEASED` until the lesson or the card is released in a mode that gates it). The sum is
weighted by `PlanEntry.weight` (1.0 until E9a): `weighted_total = Σ weight · total_points`,
`weighted_max = Σ weight · total_max_points`, over the cards that have a report — an `ABORTED`
card is never scored (SPEC §28) and so is listed nowhere in the sum. A trainee's report lists only
the cards they took part in.

The lesson must have ended (`COMPLETED` or `ABORTED`), else `409 REPORT_NOT_READY`.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.lessons.errors import (
    LessonNotFoundError,
    LessonReportNotReadyError,
    NotALessonParticipantError,
)
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.reports.assemble_report import GetSessionReport, SessionReportView
from app.application.sessions.authorisation import ParticipantNotAssignedError
from app.domain.common.ids import LessonId, SessionId
from app.domain.enums import SessionState

__all__ = ["GetLessonReport", "LessonReportCard", "LessonReportView"]


@dataclass(frozen=True)
class LessonReportCard:
    position: int
    session_id: SessionId
    weight: float
    report: SessionReportView


@dataclass(frozen=True)
class LessonReportView:
    lesson_id: LessonId
    cards: tuple[LessonReportCard, ...]
    weighted_total: float
    weighted_max: float


class GetLessonReport:
    """`getLessonReport`."""

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, get_session_report: GetSessionReport
    ) -> None:
        self._unit_of_work = unit_of_work
        self._get_session_report = get_session_report

    async def __call__(self, lesson_id: LessonId, user: AuthenticatedUser) -> LessonReportView:
        async with self._unit_of_work() as uow:
            lesson = await uow.lessons.get(lesson_id)
            if lesson is None:
                raise LessonNotFoundError(lesson_id)
            if not user.is_instructor_or_admin and not any(
                participant.user_id == user.user_id for participant in lesson.participants
            ):
                raise NotALessonParticipantError(lesson_id)
            if not lesson.is_terminal:
                raise LessonReportNotReadyError(lesson_id, lesson.state)
            cards = await uow.lessons.list_cards(lesson_id)
            await uow.commit()

        reported: list[LessonReportCard] = []
        for card in cards:
            if card.state is not SessionState.COMPLETED:
                continue
            try:
                report = await self._get_session_report(card.session_id, user)
            except ParticipantNotAssignedError:
                continue  # a trainee's report lists only the cards they took part in
            reported.append(
                LessonReportCard(
                    position=card.position,
                    session_id=card.session_id,
                    weight=lesson.entry(card.position).weight,
                    report=report,
                )
            )
        return LessonReportView(
            lesson_id=lesson_id,
            cards=tuple(reported),
            weighted_total=sum(
                card.weight * card.report.score_report.total_points for card in reported
            ),
            weighted_max=sum(
                card.weight * card.report.score_report.total_max_points for card in reported
            ),
        )
