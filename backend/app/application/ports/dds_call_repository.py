"""`DdsCallRepository` port — the `dds_calls` read model (I3 E6b, HLD `80-telephony.md` §80.3.1,
§80.7, D23).

One table, one domain type, and — like every DDS port — nothing that reaches `WorldTruth`,
`CallerBelief` or the live `OperatorCard` (SPEC §42 test 3). A row is written in the same Unit of
Work as the `DDS_CALL_*` event it mirrors and is rebuildable from those events
(`app.domain.dds.call.fold_dds_calls`, INV 13), so the table is a cache of the log, never an
authority the log could disagree with.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from app.domain.common.ids import SessionId, UserId
from app.domain.dds.call import DdsCall

__all__ = ["DdsCallRepository"]


@runtime_checkable
class DdsCallRepository(Protocol):
    """`dds_calls` (migration `0014_dds_calls`)."""

    async def add(self, call: DdsCall, *, started_event_id: UUID) -> None:
        """Insert a call just started; `started_event_id` is its stored `DDS_CALL_STARTED`."""
        ...

    async def save(self, call: DdsCall) -> None:
        """Write a moved call back (state, answer, end). Identity columns never change."""
        ...

    async def get(self, session_id: SessionId, call_id: UUID) -> DdsCall | None:
        """One call of this session, or `None`."""
        ...

    async def list_for_session(self, session_id: SessionId) -> list[DdsCall]:
        """Every call of the session, newest first (`listDdsCalls`)."""
        ...

    async def list_live(self, session_id: SessionId) -> list[DdsCall]:
        """The session's calls not `ENDED`, oldest first (the call-flow hook's worklist)."""
        ...

    async def live_for_user(self, session_id: SessionId, user_id: UserId) -> DdsCall | None:
        """The user's non-`ENDED` call in the session — one line per workstation (§80.3.2)."""
        ...
