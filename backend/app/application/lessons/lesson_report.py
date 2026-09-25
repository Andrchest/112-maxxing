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

**ABORTED cards are listed unscored (I4 E31, HLD 71 §71.8, D34; ТЗ ¶342–343).** A lesson ended
early keeps its unfinished cards in the report: each ABORTED card is listed with `score: None` and
`unscored` — its state, its timeline and its times (`GetSessionReport.unscored`: the same timeline
projection and visibility as a report). A lesson release covers them (they have no per-session
release). The weighted sum is unchanged: it counts scored cards only. Scoring an unfinished card is
not built (Q-E9b-6). Only terminal cards are listed: `abortLesson` aborts every other card.

**Norms and counters (I4 E33, HLD 71 §71.10).** A scored card's `norms` (its times against the
session's recorded timers), `failed_rule_count` and `critical_error_count` come with its
`getSessionReport` view (`SessionReportView.norms` …) — read, never re-scored (D11). An unscored
card has none of them. `getLessonReportCsv` renders this same view
(`app.application.reports.csv_export.lesson_report_csv`), so the file and the JSON carry the
same numbers.

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
from app.application.reports.assemble_report import (
    GetSessionReport,
    SessionReportView,
    UnscoredSessionView,
)
from app.application.sessions.authorisation import ParticipantNotAssignedError
from app.domain.common.ids import LessonId, SessionId
from app.domain.enums import SessionState

__all__ = ["GetLessonReport", "LessonReportCard", "LessonReportView"]


@dataclass(frozen=True)
class LessonReportCard:
    """One card: `report` for a COMPLETED card, `unscored` for an ABORTED one (I4 E31) —
    exactly one of the two is set."""

    position: int
    session_id: SessionId
    weight: float
    report: SessionReportView | None
    unscored: UnscoredSessionView | None = None


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

        lesson_released = lesson.report_released_at is not None
        listed: list[LessonReportCard] = []
        for card in cards:
            if card.state not in (SessionState.COMPLETED, SessionState.ABORTED):
                continue
            weight = lesson.entry(card.position).weight
            try:
                if card.state is SessionState.COMPLETED:
                    report = await self._get_session_report(card.session_id, user)
                    listed.append(
                        LessonReportCard(card.position, card.session_id, weight, report=report)
                    )
                else:
                    unscored = await self._get_session_report.unscored(
                        card.session_id, user, released=lesson_released
                    )
                    listed.append(
                        LessonReportCard(
                            card.position, card.session_id, weight, report=None, unscored=unscored
                        )
                    )
            except ParticipantNotAssignedError:
                continue  # a trainee's report lists only the cards they took part in
        scored = [(card.weight, card.report) for card in listed if card.report is not None]
        return LessonReportView(
            lesson_id=lesson_id,
            cards=tuple(listed),
            weighted_total=sum(
                weight * report.score_report.total_points for weight, report in scored
            ),
            weighted_max=sum(
                weight * report.score_report.total_max_points for weight, report in scored
            ),
        )
