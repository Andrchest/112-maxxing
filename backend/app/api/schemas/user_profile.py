"""`UserProfileExport` (I5 E37, Q-E16-4) — `exportUserProfile`'s wire shape.

Property names copied literally from `docs/hld/openapi.yaml`'s `UserProfileExport`: the same
account fields `UserAccountI4` already carries, plus `history` — `TraineeStatisticsRow`
(`app.api.schemas.statistics`), `null` for an `INSTRUCTOR`/`ADMIN` account. Never `password_hash`,
never `sip_ha1` (SPEC §41) — `UserProfileView` does not carry either field, so there is nothing
here to accidentally serialize.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.api.schemas.common import ApiModel
from app.api.schemas.statistics import TraineeStatisticsRowSchema, trainee_statistics_row_schema
from app.application.ports.user_repository import UserRole
from app.application.users.export_profile import UserProfileView

__all__ = ["UserProfileExportSchema", "user_profile_export_schema"]


class UserProfileExportSchema(ApiModel):
    """`UserProfileExport`."""

    id: UUID
    username: str
    display_name_ru: str
    user_role: UserRole
    is_active: bool
    created_at: datetime
    history: TraineeStatisticsRowSchema | None


def user_profile_export_schema(view: UserProfileView) -> UserProfileExportSchema:
    return UserProfileExportSchema(
        id=UUID(str(view.user_id)),
        username=view.username,
        display_name_ru=view.display_name_ru,
        user_role=view.user_role,
        is_active=view.is_active,
        created_at=view.created_at,
        history=None if view.history is None else trainee_statistics_row_schema(view.history),
    )
