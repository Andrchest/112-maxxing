"""`getTraineeStatistics` and `getMyHistory` (I4 E33, HLD 71 §71.10; I5 E36; ТЗ ¶101 REQ-2092,
¶138 REQ-2122, ¶225 REQ-2189, ¶232 REQ-2194, ¶252 REQ-2210, ¶265/266 REQ-2220/2221).

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
* `fill_deviation_ms_avg` — the mean `FILL` deviation of the 112 cards **this trainee filled**;
* `reaction_to_open_ms_avg` / `reaction_to_status_ms_avg` (I5 E36, Q-E12-1) — the mean of the two
  reaction times (`norms.card_reaction_times`) over the same legs `accept_deviation_ms_avg`
  attributes to this trainee — no `DDS_FILL` deviation average: it measures the same moment as
  `ACCEPT` against a different limit, so a third average of it would repeat, not add, information.
* `pass_count` / `pass_rate` (I5 E38, Q-E9b-3) — the sessions whose «сдал / не сдал» verdict
  (`pass_verdict.session_pass_verdict`: the session's recorded criteria over its stored totals and
  counters) is «сдал», and their share of `session_count` in percent (`None` without a session).
  Derived, like every number here — no evaluator runs, nothing is stored.

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
from typing import Literal

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.text_checker import TextCheckerPort
from app.application.reports.norms import (
    CardNorm,
    LegReactionTime,
    NormKind,
    card_norms,
    card_reaction_times,
)
from app.application.reports.pass_verdict import session_pass_verdict
from app.application.reports.text_quality import flagged_issue_count, text_quality_report
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
from app.domain.session.pass_criteria import PassVerdict, score_percent
from app.domain.session.policy import SESSION_POLICIES

__all__ = [
    "GetMyHistory",
    "GetTraineeStatistics",
    "MyHistorySessionView",
    "MyHistoryView",
    "StatisticsSubjectNotFoundError",
    "TraineeStatisticsRowView",
    "TraineeStatisticsView",
    "session_pass",
    "session_percent",
    "statistics_row",
    "took_part",
    "visible_to_trainee",
]


class StatisticsSubjectNotFoundError(DomainError):
    """No such trainee account or trainee group (`404 NOT_FOUND`)."""

    code = "NOT_FOUND"


@dataclass(frozen=True, slots=True)
class TraineeStatisticsRowView:
    """`TraineeStatisticsRow` as application data."""

    trainee_user_id: UserId
    display_name_ru: str
    username: str
    """(I5 E36, Q-E12-3) The login «рабочее место» — the statistics CSV's own column, not part of
    the JSON `TraineeStatisticsRow` (item 4's decision names only the CSVs and the lesson report
    table)."""
    session_count: int
    lesson_count: int
    average_percent: float | None
    failed_rules_by_category: Mapping[str, int]
    accept_deviation_ms_avg: float | None
    fill_deviation_ms_avg: float | None
    reaction_to_open_ms_avg: float | None
    """(I5 E36, Q-E12-1) The mean delivery → `DDS_CARD_OPENED`, over the legs this trainee
    played."""
    reaction_to_status_ms_avg: float | None
    """(I5 E36, Q-E12-1) The mean delivery → the leg's first primary decision."""
    pass_count: int = 0
    """(I5 E38, Q-E9b-3) The sessions whose verdict is «сдал»."""
    pass_rate: float | None = None
    """(I5 E38) `100 · pass_count / session_count`; `None` without a session."""


@dataclass(frozen=True, slots=True)
class TraineeStatisticsView:
    """`TraineeStatistics`."""

    rows: tuple[TraineeStatisticsRowView, ...]


@dataclass(frozen=True, slots=True)
class MyHistorySessionView:
    """`MyHistorySession`: every field below is `None` until the report is visible to the
    caller, exactly like `score_percent` / `failed_rule_count` (I5 E38, ТЗ ¶265)."""

    session_id: SessionId
    lesson_id: LessonId | None
    scenario_title_ru: str
    completed_at: datetime
    score_percent: float | None
    failed_rule_count: int | None
    passed: bool | None = None
    """ADDITIVE (I7 E50): `session_pass(session).passed` — the same verdict `pass_count` sums."""
    reaction_open_ms: int | None = None
    """ADDITIVE (I7 E50): the mean of `_attributed_reaction_times`' `to_open_ms` over this one
    session, `None` without a measured leg."""
    reaction_first_status_ms: int | None = None
    """ADDITIVE (I7 E50): the mean of `_attributed_reaction_times`' `to_first_status_ms`, same
    rule."""
    text_quality_issue_count: int | None = None
    """ADDITIVE (I7 E50): `text_quality.flagged_issue_count` of this session's
    `text_quality_report`, `None` when the checker is unavailable."""


@dataclass(frozen=True, slots=True)
class MyHistoryView:
    """`MyHistory`."""

    statistics: TraineeStatisticsRowView
    sessions: tuple[MyHistorySessionView, ...]


# -- the pure part -------------------------------------------------------------------------------


def session_percent(session: ScoredSession) -> float | None:
    """`100 · total_points / total_max_points`, clamped to 0…100; `None` for a zero maximum
    (`pass_criteria.score_percent` — the one percent the verdict reads too, I5 E38)."""
    return score_percent(session.total_points, session.total_max_points)


def session_pass(session: ScoredSession) -> PassVerdict:
    """(I5 E38) The session's «сдал / не сдал»: its recorded criteria over its stored numbers."""
    return session_pass_verdict(
        session.events,
        total_points=session.total_points,
        total_max_points=session.total_max_points,
        failed_rule_count=session.failed_rule_count,
        critical_error_count=session.critical_error_count,
    )


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
    to_open: list[int] = []
    to_status: list[int] = []
    for session in sessions:
        for category, count in session.failed_by_category.items():
            failed[category] = failed.get(category, 0) + count
        for norm in _attributed_norms(session, trainee.user_id):
            if norm.deviation_ms is None:
                continue
            (accept if norm.kind is NormKind.ACCEPT else fill).append(norm.deviation_ms)
        for reaction in _attributed_reaction_times(session, trainee.user_id):
            if reaction.to_open_ms is not None:
                to_open.append(reaction.to_open_ms)
            if reaction.to_first_status_ms is not None:
                to_status.append(reaction.to_first_status_ms)
    lessons = {session.lesson_id for session in sessions if session.lesson_id is not None}
    passes = sum(1 for session in sessions if session_pass(session).passed)
    return TraineeStatisticsRowView(
        trainee_user_id=trainee.user_id,
        display_name_ru=trainee.display_name_ru,
        username=trainee.username,
        session_count=len(sessions),
        lesson_count=len(lessons),
        average_percent=fmean(percents) if percents else None,
        failed_rules_by_category=dict(sorted(failed.items())),
        accept_deviation_ms_avg=fmean(accept) if accept else None,
        fill_deviation_ms_avg=fmean(fill) if fill else None,
        reaction_to_open_ms_avg=fmean(to_open) if to_open else None,
        reaction_to_status_ms_avg=fmean(to_status) if to_status else None,
        pass_count=passes,
        pass_rate=100.0 * passes / len(sessions) if sessions else None,
    )


def _attributed_norms(session: ScoredSession, user_id: UserId) -> Iterable[CardNorm]:
    """The norms of `session` this participant is answerable for (module doc). Only `ACCEPT` and
    `FILL` feed the deviation averages (I5 E36's `DDS_FILL` measures the same moment as `ACCEPT`
    against a different limit, so it would double it, not add information)."""
    roles = _roles_of(session, user_id)
    for norm in card_norms(session.events, session.scenario_timers):
        if norm.kind is NormKind.DDS_FILL:
            continue
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


def _attributed_reaction_times(
    session: ScoredSession, user_id: UserId
) -> Iterable[LegReactionTime]:
    """(I5 E36, Q-E12-1) This participant's own legs' reaction times — the same attribution as
    `_attributed_norms`'s `ACCEPT` branch (a leg's `bound_user_id`, or any DDS participant for an
    unbound leg; a `SCRIPTED` leg is nobody's)."""
    roles = _roles_of(session, user_id)
    for reaction in card_reaction_times(session.events):
        if reaction.leg_responder == LegResponder.SCRIPTED.value:
            continue
        if reaction.leg_bound_user_id is not None:
            if reaction.leg_bound_user_id == str(user_id):
                yield reaction
        elif RoleType.DDS in roles:
            yield reaction


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

    def __init__(
        self, reader: StatisticsReader, text_checker: TextCheckerPort | None = None
    ) -> None:
        self._reader = reader
        # (I7 E50) `None` when the lexicon/street data is absent — `text_quality_report` (and this
        # class's `text_quality_issue_count`) read that as "unavailable", never raise, exactly like
        # `GetSessionReport`'s own `self._text_checker`.
        self._text_checker = text_checker

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
                    passed=(
                        session_pass(session).passed if session.session_id in shown_ids else None
                    ),
                    reaction_open_ms=(
                        _mean_reaction(session, user.user_id, "to_open_ms")
                        if session.session_id in shown_ids
                        else None
                    ),
                    reaction_first_status_ms=(
                        _mean_reaction(session, user.user_id, "to_first_status_ms")
                        if session.session_id in shown_ids
                        else None
                    ),
                    text_quality_issue_count=(
                        flagged_issue_count(
                            text_quality_report(
                                card_values=session.card_values,
                                events=session.events,
                                checker=self._text_checker,
                            )
                        )
                        if session.session_id in shown_ids
                        else None
                    ),
                )
                for session in listed
            ),
        )


def _mean_reaction(
    session: ScoredSession, user_id: UserId, field_name: Literal["to_open_ms", "to_first_status_ms"]
) -> int | None:
    """(I7 E50) The mean of this one session's `_attributed_reaction_times` for `field_name`,
    `None` without a measured leg — the same attribution `reaction_to_open_ms_avg` /
    `reaction_to_status_ms_avg` use, narrowed from "every session" to just this one."""
    values = [
        value
        for reaction in _attributed_reaction_times(session, user_id)
        if (value := getattr(reaction, field_name)) is not None
    ]
    return round(fmean(values)) if values else None
