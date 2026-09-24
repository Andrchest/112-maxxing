"""`SqlAlchemyDdsCallRepository` over `dds_calls` (I3 E6b, HLD `80-telephony.md` §80.7, D23).

One table, one class, and — as with every DDS adapter — imports that name the ДДС call and nothing
else, so no holder of it gains a path to `WorldTruth`, `CallerBelief` or the live `OperatorCard`
(SPEC §42 test 3). ORM rows never leave this module (D2).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dds import DdsCall as DdsCallRow
from app.domain.common.ids import AssignmentId, SessionId, UserId
from app.domain.dds.call import (
    CallAnsweredBy,
    CallEndpoint,
    CallSelectionReason,
    DdsCall,
    DdsCallDirection,
    DdsCallEndReason,
    DdsCallKind,
    DdsCallState,
)
from app.domain.enums import ServiceId

__all__ = ["SqlAlchemyDdsCallRepository"]

_CALLS = DdsCallRow.__table__
_MUTABLE = (
    "state",
    "answered_by",
    "answered_at_offset_ms",
    "ended_at_offset_ms",
    "end_reason",
    "endpoint",
)


class SqlAlchemyDdsCallRepository:
    """`DdsCallRepository` over `dds_calls`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, call: DdsCall, *, started_event_id: UUID) -> None:
        await self._session.execute(
            sa.insert(_CALLS).values(**_row_values(call), started_event_id=started_event_id)
        )

    async def save(self, call: DdsCall) -> None:
        values = _row_values(call)
        await self._session.execute(
            sa.update(_CALLS)
            .where(_CALLS.c.id == call.call_id)
            .values(**{key: values[key] for key in _MUTABLE})
        )

    async def get(self, session_id: SessionId, call_id: UUID) -> DdsCall | None:
        result = await self._session.execute(
            sa.select(_CALLS).where(
                _CALLS.c.id == UUID(str(call_id)), _CALLS.c.session_id == UUID(str(session_id))
            )
        )
        row = result.first()
        return None if row is None else _from_row(row._mapping)

    async def list_for_session(self, session_id: SessionId) -> list[DdsCall]:
        result = await self._session.execute(
            sa.select(_CALLS)
            .where(_CALLS.c.session_id == UUID(str(session_id)))
            .order_by(_CALLS.c.started_at_offset_ms.desc(), _CALLS.c.id)
        )
        return [_from_row(row._mapping) for row in result.all()]

    async def list_live(self, session_id: SessionId) -> list[DdsCall]:
        result = await self._session.execute(
            sa.select(_CALLS)
            .where(
                _CALLS.c.session_id == UUID(str(session_id)),
                _CALLS.c.state != DdsCallState.ENDED.value,
            )
            .order_by(_CALLS.c.started_at_offset_ms, _CALLS.c.id)
        )
        return [_from_row(row._mapping) for row in result.all()]

    async def live_for_user(self, session_id: SessionId, user_id: UserId) -> DdsCall | None:
        result = await self._session.execute(
            sa.select(_CALLS)
            .where(
                _CALLS.c.session_id == UUID(str(session_id)),
                _CALLS.c.actor_user_id == UUID(str(user_id)),
                _CALLS.c.state != DdsCallState.ENDED.value,
            )
            .order_by(_CALLS.c.started_at_offset_ms)
            .limit(1)
        )
        row = result.first()
        return None if row is None else _from_row(row._mapping)


def _row_values(call: DdsCall) -> dict[str, Any]:
    return {
        "id": call.call_id,
        "session_id": UUID(str(call.session_id)),
        "kind": call.kind.value,
        "direction": call.direction.value,
        "assignment_id": None if call.assignment_id is None else UUID(str(call.assignment_id)),
        "service_type": call.service_type,
        "dialed": call.dialed,
        "endpoint": call.endpoint.value,
        "room": call.room,
        "persona_id": call.persona_id,
        "actor_user_id": None if call.actor_user_id is None else UUID(str(call.actor_user_id)),
        "state": call.state.value,
        "answered_by": None if call.answered_by is None else call.answered_by.value,
        "selection_reason": call.selection_reason.value,
        "started_at_offset_ms": call.started_at_offset_ms,
        "answered_at_offset_ms": call.answered_at_offset_ms,
        "ended_at_offset_ms": call.ended_at_offset_ms,
        "end_reason": None if call.end_reason is None else call.end_reason.value,
    }


def _from_row(row: Mapping[str, Any]) -> DdsCall:
    assignment = row["assignment_id"]
    actor = row["actor_user_id"]
    answered_by = row["answered_by"]
    end_reason = row["end_reason"]
    service_type = row["service_type"]
    return DdsCall(
        call_id=UUID(str(row["id"])),
        session_id=SessionId(UUID(str(row["session_id"]))),
        kind=DdsCallKind(row["kind"]),
        direction=DdsCallDirection(row["direction"]),
        assignment_id=None if assignment is None else AssignmentId(UUID(str(assignment))),
        service_type=None if service_type is None else ServiceId(service_type),
        dialed=row["dialed"],
        endpoint=CallEndpoint(row["endpoint"]),
        room=row["room"],
        persona_id=row["persona_id"],
        actor_user_id=None if actor is None else UserId(UUID(str(actor))),
        selection_reason=CallSelectionReason(row["selection_reason"]),
        state=DdsCallState(row["state"]),
        answered_by=None if answered_by is None else CallAnsweredBy(answered_by),
        started_at_offset_ms=int(row["started_at_offset_ms"]),
        answered_at_offset_ms=row["answered_at_offset_ms"],
        ended_at_offset_ms=row["ended_at_offset_ms"],
        end_reason=None if end_reason is None else DdsCallEndReason(end_reason),
    )
