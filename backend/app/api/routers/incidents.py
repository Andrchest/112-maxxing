"""`incidents` router — `listMyIncidents` (HLD 70 §70.3.6, `i3-openapi-delta.yaml`, I3 E4a).

The caller's cross-session incident list: the ДДС «Список/Поиск происшествий» and the 112
«реестр». A pure read: rows carry the materialised `card_status` and the deadline offsets, and the
client renders countdowns from `session_offset_ms` — it never decides a status.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ContainerDep
from app.api.schemas.common import PageSchema
from app.api.schemas.lessons import IncidentListItemSchema, incident_list_item_schema
from app.api.security import CurrentUserDep
from app.domain.common.ids import LessonId
from app.domain.dds.card_status import CardStatus
from app.domain.enums import RoleType

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


IncidentPage = PageSchema[IncidentListItemSchema]
"""`{items, total}` of `listMyIncidents` — the list is not paged, so `total` is its length."""


@router.get(
    "",
    operation_id="listMyIncidents",
    summary="The caller's cross-session incident list (ДДС «Список происшествий», 112 «реестр»).",
    response_model=IncidentPage,
    status_code=200,
)
async def list_my_incidents(
    container: ContainerDep,
    user: CurrentUserDep,
    lesson_id: UUID | None = None,
    role_type: RoleType | None = None,
    card_status: CardStatus | None = None,
    q: str | None = None,
) -> IncidentPage:
    items = await container.list_my_incidents()(
        viewer=user,
        lesson_id=None if lesson_id is None else LessonId(lesson_id),
        role_type=role_type,
        card_status=card_status,
        q=q,
    )
    return IncidentPage(items=[incident_list_item_schema(item) for item in items], total=len(items))
