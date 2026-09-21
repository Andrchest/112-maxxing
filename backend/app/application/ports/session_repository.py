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

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import SessionId, UserId
from app.domain.enums import RoleType, SessionMode, SessionState
from app.domain.session.session import SimulationSession

__all__ = [
    "ReportRelease",
    "SessionRepository",
    "StoredParticipant",
    "StoredSessionListing",
]


class StoredSessionListing(BaseModel):
    """One row of `listSessions` — `openapi.yaml`'s `SessionListItem`, property names literal.

    `scenario_slug` and `scenario_version` live on `scenarios` / `scenario_versions`, and
    `my_role_type` is the viewer's own `session_participants.assigned_role_type`: all three are
    joins the adapter does in one statement, so listing N sessions costs one query rather than
    3N. `my_role_type` is `null` when the viewer only observes the session, exactly as the schema
    says.
    """

    model_config = ConfigDict(frozen=True)

    session_id: SessionId
    scenario_slug: str
    scenario_version: int
    session_mode: SessionMode
    state: SessionState
    created_at: datetime
    created_by_user_id: UserId
    my_role_type: RoleType | None = None


class StoredParticipant(BaseModel):
    """One `session_participants` row including `joined_at` (§20.3).

    The domain's `SessionParticipant` deliberately has no `joined_at` — it is a storage default no
    rule reads — but `openapi.yaml`'s `SessionParticipantView` renders it, so the read path needs
    this second projection rather than a new field on the aggregate.
    """

    model_config = ConfigDict(frozen=True)

    user_id: UserId
    assigned_role_type: RoleType | None
    joined_at: datetime


class ReportRelease(BaseModel):
    """`simulation_sessions.report_released_at` / `.report_released_by_user_id` (E16, D6, D11).

    Its existence *is* the release: `openapi.yaml`'s `ReportReleaseView.released` is
    "a `ReportRelease` was found". Releasing changes no score — it is a visibility flag, not a
    scoring operation (D11) — which is why it lives on the session row rather than anywhere near
    `score_results`.
    """

    model_config = ConfigDict(frozen=True)

    session_id: SessionId
    released_at: datetime
    released_by_user_id: UserId


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

    async def list_active_session_ids(self) -> list[SessionId]:
        """Every `ACTIVE` session's id, ordered by id.

        This is the `SimulationRunner`'s adoption read (D7, `40-realtime-protocol.md` "Backend
        restart"): on start the backend re-adopts every ACTIVE session from PostgreSQL. It reads
        ids only — the runner loads each aggregate under its own row lock when it ticks it.
        """
        ...

    async def list_sessions(
        self,
        *,
        viewer_user_id: UserId,
        mine_only: bool,
        state: SessionState | None,
        limit: int,
        offset: int,
    ) -> tuple[list[StoredSessionListing], int]:
        """One page of sessions, newest first, plus the unpaged total (`listSessions`).

        `mine_only` is `openapi.yaml`'s `scope=MINE`: the sessions `viewer_user_id` participates
        in **or** created. It is pushed into the statement rather than applied above it, because
        filtering after pagination would make `total` and the page disagree. `scope=ALL` passes
        `mine_only=False` and is refused for a `TRAINEE` before it ever reaches this port.

        `viewer_user_id` is read even when `mine_only` is false: it is what `my_role_type` is
        resolved against.
        """
        ...

    async def get_listing(
        self, session_id: SessionId, *, viewer_user_id: UserId
    ) -> StoredSessionListing | None:
        """The listing row of one session, or `None`.

        `SessionDetail` needs three facts the pure aggregate deliberately does not carry —
        `created_at` (a storage default), `scenario_slug` and `scenario_version` (columns of two
        other tables) — and they are exactly the joins `list_sessions` already performs. Rather
        than a fourth projection, `getSession` reads this one for a single id.
        """
        ...

    async def list_participants(self, session_id: SessionId) -> list[StoredParticipant]:
        """This session's participants with their `joined_at`, in join order (§20.3)."""
        ...

    async def get_report_release(self, session_id: SessionId) -> ReportRelease | None:
        """This session's release record, or `None` when the report has not been released.

        A plain read: `getSessionReport` needs it for `released`, and `getAudioSegment` needs it
        for the same visibility decision.
        """
        ...

    async def release_report(
        self, session_id: SessionId, *, released_by_user_id: UserId, released_at: datetime
    ) -> ReportRelease:
        """Release the report to this session's trainees, **idempotently**.

        A second call returns the first release unchanged — the conditional
        `UPDATE … WHERE report_released_at IS NULL` is what makes that a property of the
        statement rather than of a read-then-write two callers could interleave inside. The
        caller has already checked that the session is `COMPLETED`.
        """
        ...

    async def save(self, session: SimulationSession) -> None:
        """Write back an aggregate `get_for_update` returned.

        Updates `simulation_sessions`, `incidents`, `role_stages` and `session_participants`;
        never `next_seq_no`.
        """
        ...
