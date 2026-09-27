"""`StatisticsReader` — the one read the statistics need (I4 E33, HLD 71 §71.10).

A read model over what is already stored, never a second scorer (D11): the completed sessions a
set of trainees took part in, each with its **stored** score totals and failed-rule counts per
category (`score_results`), its participants, and the few events the norms fold over
(`norms.NORM_EVENT_TYPES`). Nothing is re-evaluated; the adapter only sums stored rows.

It is its own port rather than a Unit of Work repository because it spans half the schema and
belongs to no aggregate — the same shape as E25's `AuditReader`. The adapter is
`app.infrastructure.persistence.statistics_reader.SqlAlchemyStatisticsReader`, a few set-based
queries per call, which is what keeps ¶165's 30 seconds at a class's volume.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.domain.common.ids import LessonId, SessionId, TraineeGroupId, UserId
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
    """`norms.NORM_EVENT_TYPES` only, in `seq_no` order."""


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
