"""`SessionRepository` port — the session aggregate's storage (HLD `20-db-schema.md` §20.3, D5).

The aggregate is `SimulationSession` plus the `Incident`, the `RoleStage`s and the
`SessionParticipant`s it owns (§20.3): one repository, because those four tables are written and
read as one unit and a partial write of them is never meaningful.

`next_seq_no` is deliberately outside this port: the event store owns sequence allocation (§20.8),
so `save` must never touch that column. `get_for_update` is the write path — it takes the
`SELECT … FOR UPDATE` row lock on `simulation_sessions` before a state transition, so two
concurrent commands cannot both read `READY` and both start the session.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.common.ids import SessionId
from app.domain.session.session import SimulationSession

__all__ = ["SessionRepository"]


@runtime_checkable
class SessionRepository(Protocol):
    """Read and write the session aggregate as one unit (§20.3)."""

    async def add(self, session: SimulationSession) -> None:
        """Insert a brand-new aggregate: the session row, its incident, its stages and its
        participants. `next_seq_no` is left at its storage default (§20.8)."""
        ...

    async def get(self, session_id: SessionId) -> SimulationSession | None:
        """The aggregate with this id, or `None`. A plain read: no row lock is taken."""
        ...

    async def get_for_update(self, session_id: SessionId) -> SimulationSession | None:
        """The aggregate with this id under `SELECT … FOR UPDATE` on `simulation_sessions`.

        Every use case that fires a session trigger reads through this method, so the row lock is
        held for the whole Unit of Work transaction (§20.8, D5).
        """
        ...

    async def save(self, session: SimulationSession) -> None:
        """Write back an aggregate `get_for_update` returned.

        Updates `simulation_sessions`, `incidents`, `role_stages` and `session_participants`;
        never `next_seq_no`.
        """
        ...
