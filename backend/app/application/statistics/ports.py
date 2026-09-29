"""`StatisticsReader` — the one read the statistics need (I4 E33, HLD 71 §71.10).

A read model over what is already stored, never a second scorer (D11): the completed sessions a
set of trainees took part in, each with its **stored** score totals and failed-rule counts per
category (`score_results`), its participants, and the few events the norms fold over
(`norms.NORM_EVENT_TYPES`). Nothing is re-evaluated; the adapter only sums stored rows.

It is its own port rather than a Unit of Work repository because it spans half the schema and
belongs to no aggregate — the same shape as E25's `AuditReader`. The adapter is
`app.infrastructure.persistence.statistics_reader.SqlAlchemyStatisticsReader`, a few set-based
queries per call, which is what keeps ¶165's 30 seconds at a class's volume.

`scoped_session_ids` + `typical_errors` (I7 E54, G11, ТЗ ¶233) are the same reading, narrower:
«Типичные ошибки» needs only session ids and a `GROUP BY rule_id` over `score_results`, never the
full `ScoredSession` shape `scored_sessions` builds for the trainee statistics page.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.domain.common.ids import LessonId, SessionId, TraineeGroupId, UserId
from app.domain.common.values import FactValue
from app.domain.dds.card_status import CardTimers
from app.domain.enums import RoleType, SessionMode
from app.domain.events.types import EventType

__all__ = [
    "ScoredSession",
    "StatisticsEvent",
    "StatisticsFilter",
    "StatisticsParticipant",
    "StatisticsReader",
    "TraineeAccount",
    "TypicalErrorRow",
]


@dataclass(frozen=True, slots=True)
class StatisticsFilter:
    """`getTraineeStatistics`' query: one trainee, one group's members, and a `completed_at`
    window (`from` inclusive, `to` exclusive, UTC). Every part optional."""

    trainee_id: UserId | None = None
    group_id: TraineeGroupId | None = None
    from_utc: datetime | None = None
    to_utc: datetime | None = None


@dataclass(frozen=True, slots=True)
class TraineeAccount:
    """A row's who: a `TRAINEE` account (blocked ones too — their history stays)."""

    user_id: UserId
    display_name_ru: str
    username: str = ""
    """(I5 E36, Q-E12-3) The login «рабочее место» — the statistics CSV's own column."""


@dataclass(frozen=True, slots=True)
class StatisticsParticipant:
    """One `session_participants` row."""

    user_id: UserId
    assigned_role_type: RoleType | None


@dataclass(frozen=True, slots=True)
class StatisticsEvent:
    """One `session_events` row of `norms.NORM_EVENT_TYPES`, as `card_norms` reads it."""

    event_type: EventType
    payload: Mapping[str, Any]
    monotonic_offset_ms: int


@dataclass(frozen=True, slots=True)
class ScoredSession:
    """A `COMPLETED` session with stored score results — the unit every statistic counts."""

    session_id: SessionId
    lesson_id: LessonId | None
    session_mode: SessionMode
    completed_at: datetime
    report_released: bool
    """An instructor released its report (`simulation_sessions.report_released_at`)."""
    scenario_title_ru: str
    scenario_timers: CardTimers
    """The version's own `timers` — the norm of a log that records none (`norms`)."""
    participants: tuple[StatisticsParticipant, ...]
    total_points: float
    total_max_points: float
    failed_by_category: Mapping[str, int]
    """`ScoringCategory` value → stored results that did not pass (absent = none failed)."""
    failed_rule_count: int
    critical_error_count: int
    events: tuple[StatisticsEvent, ...] = field(default=())
    """`norms.NORM_EVENT_TYPES` plus `text_quality.TEXT_QUALITY_EVENT_TYPES`, in `seq_no` order."""
    card_values: Mapping[str, FactValue] | None = None
    """ADDITIVE (I7 E50): the session's final 112 card (`incident_cards.values`), `None` when the
    incident never had one — `getMyHistory`'s `text_quality_issue_count` reuses the same
    `text_quality_report` fold `getSessionReport` uses, over this and `events` (D11: still no
    evaluator runs here, only the stored/folded values it was already reading)."""


@dataclass(frozen=True, slots=True)
class TypicalErrorRow:
    """One set-based `score_results` row (I7 E54, G11): a rule some sessions in scope failed."""

    rule_id: str
    category: str
    name_ru: str
    failed_session_count: int


class StatisticsReader(Protocol):
    """The statistics' reads (adapter: `SqlAlchemyStatisticsReader`)."""

    async def trainees(self, query: StatisticsFilter) -> tuple[TraineeAccount, ...]:
        """`TRAINEE` accounts, narrowed by `query.trainee_id` / `query.group_id`, by name."""
        ...

    async def accounts(self, user_ids: Sequence[UserId]) -> tuple[TraineeAccount, ...]:
        """These accounts, whatever their role (`getMyHistory`'s caller)."""
        ...

    async def group_exists(self, group_id: TraineeGroupId) -> bool:
        """Whether `trainee_groups` has this id."""
        ...

    async def scored_sessions(
        self,
        user_ids: Sequence[UserId],
        *,
        from_utc: datetime | None = None,
        to_utc: datetime | None = None,
    ) -> tuple[ScoredSession, ...]:
        """Every scored session one of `user_ids` took part in, completed in the window."""
        ...

    async def scoped_session_ids(
        self,
        *,
        user_ids: Sequence[UserId] | None = None,
        lesson_id: LessonId | None = None,
        owner_id: UserId | None = None,
        from_utc: datetime | None = None,
        to_utc: datetime | None = None,
    ) -> tuple[SessionId, ...]:
        """`COMPLETED`, scored session ids in scope (I7 E54, G11): `user_ids`' sessions, or one
        `lesson_id`'s, further narrowed to `owner_id`'s own lessons when given (an INSTRUCTOR sees
        only lessons they created; `None` is an ADMIN's unrestricted read, `GetTypicalErrors`'s
        own reading). Lighter than `scored_sessions`: ids only, for `typical_errors` below."""
        ...

    async def typical_errors(
        self, session_ids: Sequence[SessionId], *, limit: int = 10
    ) -> tuple[TypicalErrorRow, ...]:
        """The `limit` rules most of `session_ids` failed, worst (most failed sessions) first,
        ties broken by `rule_id` (I7 E54, G11) — one `GROUP BY`, no evaluator, D11."""
        ...
