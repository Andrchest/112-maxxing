"""`getTraineeStatistics` and `getMyHistory` (I4 E33, HLD 71 §71.10; ТЗ ¶101 REQ-2092, ¶138
REQ-2122, ¶225 REQ-2189, ¶232 REQ-2194, ¶252 REQ-2210, ¶265/266 REQ-2220/2221).

**Read, never re-scored (D11).** Every number is an aggregate of stored rows: a session's percent
is its stored `total_points / total_max_points` (the same two numbers its report shows), the
failed rules are stored results that did not pass, and the norm deviations are
`norms.card_norms` over the session's log against its recorded timers. No evaluator runs here.

**One row per trainee**, over the `COMPLETED`, scored sessions they took part in:

* `session_count` — those sessions; `lesson_count` — the distinct lessons among them;
* `average_percent` — the mean of each session's percent (a session with `total_max_points` 0
  has none), `None` without one;
* `failed_rules_by_category` — stored failed results per `ScoringCategory`, summed;
* `accept_deviation_ms_avg` — the mean `ACCEPT` deviation of the legs **this trainee played**;
* `fill_deviation_ms_avg` — the mean `FILL` deviation of the 112 cards **this trainee filled**.

Who played what is read from the session, never guessed: the 112 card is filled by the
participant covering `OPERATOR_112` (an explicit `assigned_role_type`, or none under
`ALL_STAGES_ONE_PARTICIPANT`, which covers the whole chain — `visibility.viewer_roles_of`'s rule).
A leg is played by its `bound_user_id`; an unbound leg by any participant covering `DDS`; a
`SCRIPTED` leg by nobody (`dds/responders.plays_leg`'s reading). A measured interval only — an
unmeasured one is not a zero.

A session percent is clamped to 0…100 (`TraineeStatisticsRow.average_percent`'s bounds): a total
below zero (penalties) reads as 0 %.

**Who sees what.** INSTRUCTOR / ADMIN: every trainee, or one (`trainee_id`), or one group's
members (`group_id`). A TRAINEE: themselves only — another `trainee_id` is `403
FORBIDDEN_FOR_ROLE` — and only the sessions whose report is visible to them (the existing release
rule, `SessionPolicy.report_visible_to_trainee_before_release` or a release), so a statistic never
shows a score its report still hides. `getMyHistory` is the caller's own row plus their completed
sessions, newest first; a session whose report is not visible to them yet is listed with its date
and without its score.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from statistics import fmean

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.reports.norms import CardNorm, NormKind, card_norms
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.statistics.ports import (
    ScoredSession,
    StatisticsFilter,
    StatisticsReader,
    TraineeAccount,
)
from app.domain.common.errors import DomainError
from app.domain.common.ids import LessonId, SessionId, UserId
from app.domain.dds.response import LegResponder
from app.domain.enums import RoleType
from app.domain.events.types import EventType
from app.domain.session.policy import SESSION_POLICIES

__all__ = [
    "GetMyHistory",
    "GetTraineeStatistics",
    "MyHistorySessionView",
    "MyHistoryView",
    "StatisticsSubjectNotFoundError",
    "TraineeStatisticsRowView",
    "TraineeStatisticsView",
    "session_percent",
    "statistics_row",
]


class StatisticsSubjectNotFoundError(DomainError):
    """No such trainee account or trainee group (`404 NOT_FOUND`)."""

    code = "NOT_FOUND"


@dataclass(frozen=True, slots=True)
class TraineeStatisticsRowView:
    """`TraineeStatisticsRow` as application data."""

    trainee_user_id: UserId
    display_name_ru: str
    session_count: int
    lesson_count: int
    average_percent: float | None
    failed_rules_by_category: Mapping[str, int]
    accept_deviation_ms_avg: float | None
    fill_deviation_ms_avg: float | None


@dataclass(frozen=True, slots=True)
class TraineeStatisticsView:
    """`TraineeStatistics`."""

    rows: tuple[TraineeStatisticsRowView, ...]


@dataclass(frozen=True, slots=True)
class MyHistorySessionView:
    """`MyHistorySession`: `score_percent` / `failed_rule_count` are `None` until the report is
    visible to the caller."""

    session_id: SessionId
    lesson_id: LessonId | None
    scenario_title_ru: str
    completed_at: datetime
    score_percent: float | None
    failed_rule_count: int | None


@dataclass(frozen=True, slots=True)
class MyHistoryView:
    """`MyHistory`."""

    statistics: TraineeStatisticsRowView
    sessions: tuple[MyHistorySessionView, ...]


# -- the pure part -------------------------------------------------------------------------------


def session_percent(session: ScoredSession) -> float | None:
    """`100 · total_points / total_max_points`, clamped to 0…100; `None` for a zero maximum."""
    if session.total_max_points <= 0:
        return None
    percent = 100.0 * session.total_points / session.total_max_points
    return min(100.0, max(0.0, percent))


def visible_to_trainee(session: ScoredSession) -> bool:
    """The report release rule (`visibility.report_visibility`) for a participant."""
    policy = SESSION_POLICIES[session.session_mode]
    return policy.report_visible_to_trainee_before_release or session.report_released


def took_part(session: ScoredSession, user_id: UserId) -> bool:
    return any(participant.user_id == user_id for participant in session.participants)


def statistics_row(
    trainee: TraineeAccount, sessions: Sequence[ScoredSession]
) -> TraineeStatisticsRowView:
    """The row of `trainee` over `sessions` (already the ones they took part in)."""
    percents = [p for p in (session_percent(session) for session in sessions) if p is not None]
    failed: dict[str, int] = {}
    accept: list[int] = []
    fill: list[int] = []
    for session in sessions:
        for category, count in session.failed_by_category.items():
            failed[category] = failed.get(category, 0) + count
        for norm in _attributed_norms(session, trainee.user_id):
            if norm.deviation_ms is None:
                continue
            (accept if norm.kind is NormKind.ACCEPT else fill).append(norm.deviation_ms)
    lessons = {session.lesson_id for session in sessions if session.lesson_id is not None}
    return TraineeStatisticsRowView(
        trainee_user_id=trainee.user_id,
        display_name_ru=trainee.display_name_ru,
        session_count=len(sessions),
        lesson_count=len(lessons),
        average_percent=fmean(percents) if percents else None,
        failed_rules_by_category=dict(sorted(failed.items())),
        accept_deviation_ms_avg=fmean(accept) if accept else None,
        fill_deviation_ms_avg=fmean(fill) if fill else None,
    )


def _attributed_norms(session: ScoredSession, user_id: UserId) -> Iterable[CardNorm]:
    """The norms of `session` this participant is answerable for (module doc)."""
    roles = _roles_of(session, user_id)
    for norm in card_norms(session.events, session.scenario_timers):
        if norm.kind is NormKind.FILL:
            if RoleType.OPERATOR_112 in roles:
                yield norm
        elif norm.leg_responder == LegResponder.SCRIPTED.value:
            continue
        elif norm.leg_bound_user_id is not None:
            if norm.leg_bound_user_id == str(user_id):
                yield norm
        elif RoleType.DDS in roles:
            yield norm


def _roles_of(session: ScoredSession, user_id: UserId) -> frozenset[RoleType]:
    """`viewer_roles_of` over the session's own effective chain (`SESSION_CREATED.role_chain`)."""
    roles: set[RoleType] = set()
    for participant in session.participants:
        if participant.user_id != user_id:
            continue
        if participant.assigned_role_type is not None:
            roles.add(participant.assigned_role_type)
        else:
            roles.update(_role_chain(session))
    return frozenset(roles)


def _role_chain(session: ScoredSession) -> tuple[RoleType, ...]:
    for event in session.events:
        if event.event_type is EventType.SESSION_CREATED:
            chain = event.payload.get("role_chain")
            if isinstance(chain, list | tuple):
                return tuple(RoleType(str(role)) for role in chain if str(role) in _ROLE_VALUES)
            break
    return ()


_ROLE_VALUES = frozenset(role.value for role in RoleType)


# -- the use cases -------------------------------------------------------------------------------


class GetTraineeStatistics:
    """`getTraineeStatistics` (and, rendered, `getTraineeStatisticsCsv`)."""

    def __init__(self, reader: StatisticsReader) -> None:
        self._reader = reader

    async def __call__(
        self, query: StatisticsFilter, user: AuthenticatedUser
    ) -> TraineeStatisticsView:
        if not user.is_instructor_or_admin:
            if query.trainee_id is not None and query.trainee_id != user.user_id:
                raise ForbiddenForRoleError("a trainee may read their own statistics only")
            query = replace(query, trainee_id=user.user_id)
        if query.group_id is not None and not await self._reader.group_exists(query.group_id):
            raise StatisticsSubjectNotFoundError(f"no trainee group {query.group_id}")
        trainees = await self._reader.trainees(query)
        if query.trainee_id is not None and not trainees and user.is_instructor_or_admin:
            raise StatisticsSubjectNotFoundError(f"no trainee account {query.trainee_id}")
        sessions = await self._reader.scored_sessions(
            [trainee.user_id for trainee in trainees],
            from_utc=query.from_utc,
            to_utc=query.to_utc,
        )
        trainee_viewer = not user.is_instructor_or_admin
        rows = tuple(
            statistics_row(
                trainee,
                [
                    session
                    for session in sessions
                    if took_part(session, trainee.user_id)
                    and (not trainee_viewer or visible_to_trainee(session))
                ],
            )
            for trainee in trainees
        )
        return TraineeStatisticsView(rows=rows)


class GetMyHistory:
    """`getMyHistory`: the caller's own row and completed sessions."""

    def __init__(self, reader: StatisticsReader) -> None:
        self._reader = reader

    async def __call__(self, user: AuthenticatedUser) -> MyHistoryView:
        accounts = await self._reader.accounts([user.user_id])
        account = accounts[0] if accounts else TraineeAccount(user.user_id, str(user.user_id))
        sessions = [
            session
            for session in await self._reader.scored_sessions([user.user_id])
            if took_part(session, user.user_id)
        ]
        shown = [
            session
            for session in sessions
            if user.is_instructor_or_admin or visible_to_trainee(session)
        ]
        shown_ids = {session.session_id for session in shown}
        listed = sorted(sessions, key=lambda session: session.completed_at, reverse=True)
        return MyHistoryView(
            statistics=statistics_row(account, shown),
            sessions=tuple(
                MyHistorySessionView(
                    session_id=session.session_id,
                    lesson_id=session.lesson_id,
                    scenario_title_ru=session.scenario_title_ru,
                    completed_at=session.completed_at,
                    score_percent=(
                        session_percent(session) if session.session_id in shown_ids else None
                    ),
                    failed_rule_count=(
                        session.failed_rule_count if session.session_id in shown_ids else None
                    ),
                )
                for session in listed
            ),
        )
