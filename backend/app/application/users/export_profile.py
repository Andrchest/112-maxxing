"""`ExportUserProfile` — `exportUserProfile` (I5 E37, Q-E16-4, ТЗ ¶363 «JSON для хранения профилей
пользователей»).

**Who may ask.** The account itself, or `ADMIN` — deliberately narrower than the read access
Q-E14-1 gives `ADMIN` elsewhere (`is_instructor_or_admin`): an `INSTRUCTOR` may read a trainee's
statistics and reports, but not download another account's profile file (the manager's brief:
"Allowed for the user themself and ADMIN"). `403 FORBIDDEN_FOR_ROLE` otherwise.

**What it returns.** `UserProfileView` — the account fields `openapi.yaml`'s `UserAccountI4`
already carries (`id`≡`user_id`, `username`, `display_name_ru`, `user_role`, `is_active`,
`created_at`) and nothing else off `StoredUser`: never `password_hash`, never `sip_ha1` (SPEC §41)
— there is no field on this dataclass to accidentally serialize either.

**The E33 history summary.** `history` is the caller's or the target's own
`TraineeStatisticsRowView` (`app.application.statistics.trainee_statistics`, D11 — read, never
re-scored) for a `TRAINEE` account, `None` for an `INSTRUCTOR`/`ADMIN` account (the statistic
answers "how did this trainee do", which does not apply to an account that does not train).
Visibility of the underlying sessions follows the same rule `GetMyHistory`/`GetTraineeStatistics`
already apply: a `TRAINEE` viewing their own profile sees only the sessions whose report is
visible to them; `ADMIN` viewing anyone's profile sees every session (Q-E14-1 — an admin already
reads everything, this is not a new widening).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.ports.user_repository import UserRole
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.statistics.ports import StatisticsFilter, StatisticsReader
from app.application.statistics.trainee_statistics import (
    TraineeStatisticsRowView,
    statistics_row,
    took_part,
    visible_to_trainee,
)
from app.application.users.errors import UserNotFoundError
from app.domain.common.ids import UserId

__all__ = ["ExportUserProfile", "UserProfileView"]


@dataclass(frozen=True, slots=True)
class UserProfileView:
    """`UserProfileExport` — never the password hash or the SIP HA1 (SPEC §41)."""

    user_id: UserId
    username: str
    display_name_ru: str
    user_role: UserRole
    is_active: bool
    created_at: datetime
    history: TraineeStatisticsRowView | None


class ExportUserProfile:
    """`exportUserProfile`: the caller's own profile, or `ADMIN` reading anyone's."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, statistics: StatisticsReader) -> None:
        self._unit_of_work = unit_of_work
        self._statistics = statistics

    async def __call__(self, target_user_id: UserId, viewer: AuthenticatedUser) -> UserProfileView:
        if viewer.user_id != target_user_id and viewer.user_role is not UserRole.ADMIN:
            raise ForbiddenForRoleError(
                "a profile may be exported by its own account or by ADMIN only"
            )
        async with self._unit_of_work() as uow:
            target = await uow.users.get(target_user_id)
            await uow.commit()
        if target is None:
            raise UserNotFoundError(target_user_id)
        history = await self._history(target_user_id, target.user_role, viewer)
        return UserProfileView(
            user_id=target.user_id,
            username=target.username,
            display_name_ru=target.display_name_ru,
            user_role=target.user_role,
            is_active=target.is_active,
            created_at=target.created_at,
            history=history,
        )

    async def _history(
        self, target_user_id: UserId, role: UserRole, viewer: AuthenticatedUser
    ) -> TraineeStatisticsRowView | None:
        if role is not UserRole.TRAINEE:
            return None
        trainees = await self._statistics.trainees(StatisticsFilter(trainee_id=target_user_id))
        if not trainees:
            return None
        sessions = await self._statistics.scored_sessions([target_user_id])
        restricted = viewer.user_id == target_user_id and not viewer.is_instructor_or_admin
        shown = [
            session
            for session in sessions
            if took_part(session, target_user_id)
            and (not restricted or visible_to_trainee(session))
        ]
        return statistics_row(trainees[0], shown)
