"""`snapshot` router — `getSessionSnapshot`, the role-filtered restore payload (SPEC §39, D3, D8).

One endpoint. `listSessionEvents` and the WebSocket are **not** here: they live in
`app.api.routers.realtime`, which owns the replay/resume protocol of
`40-realtime-protocol.md` §3-§4.

The snapshot is what makes "refresh does not lose active incident state" (SPEC §42 test 13) one
HTTP call: the active stage, its state, the caller's `available_actions`, the card their role may
see, the call state and `last_seq_no` — all read in a single transaction, so opening the WebSocket
with `{"type":"resume","after_seq_no":last_seq_no}` afterwards loses nothing and repeats nothing.

Which panel the caller gets is decided by the acting role's `DataVisibilityPolicy`, inside
`app.application.sessions.get_snapshot`, never here (D3).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ContainerDep
from app.api.schemas.snapshot import SessionSnapshotSchema, session_snapshot_schema
from app.api.security import CurrentUserDep
from app.domain.common.ids import SessionId

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.get(
    "/{session_id}/snapshot",
    operation_id="getSessionSnapshot",
    summary="Role-filtered restore snapshot (browser refresh).",
    response_model=SessionSnapshotSchema,
    status_code=200,
)
async def get_session_snapshot(
    session_id: UUID, container: ContainerDep, user: CurrentUserDep
) -> SessionSnapshotSchema:
    """The one REST call the frontend makes after a refresh (SPEC §39, §42 test 13)."""
    view = await container.get_snapshot()(SessionId(session_id), user)
    return session_snapshot_schema(view)
