"""Session-lifecycle use cases (E5/E7, HLD `10-domain-model.md` §10.8, §10.10, D3, D5, D6, D8).

`CreateSession`, `StartSession` and `AbortSession` — one Unit of Work transaction each (D5) — plus
`build_guard_runtime`, the pure projection of `GuardRuntime` from a session's event log,
`authorisation` (D8's first gate: `resolve_participant` / `can_observe`) and `queries` (the
`listSessions` / `getSession` read path and the `SessionDetail` assembler every command returns),
plus `get_snapshot` (the role-filtered restore payload of SPEC §39, E7-B).

Completing a session is not here: `app.application.handoff.complete_session` owns
`SESSION_COMPLETED.total_events` and runs inside the transaction of whichever stage command
finished the last `role_chain` entry (E9). `start_session` reaches the other way for the same
reason — a `role_chain` of `[DDS]` has its prefab handoff materialised as the session starts.
"""

from __future__ import annotations

from app.application.sessions.abort_session import AbortSession
from app.application.sessions.authorisation import (
    ParticipantNotAssignedError,
    can_observe,
    resolve_participant,
)
from app.application.sessions.create_session import (
    CreateSession,
    CreateSessionCommand,
    ScenarioVersionNotFoundError,
)
from app.application.sessions.get_snapshot import GetSnapshot, SessionSnapshotView
from app.application.sessions.guard_context import build_guard_runtime
from app.application.sessions.queries import (
    ForbiddenForRoleError,
    GetSession,
    ListSessions,
    ParticipantView,
    SessionDetailView,
    assemble_session_detail,
)
from app.application.sessions.start_session import (
    InferenceNotReadyError,
    SessionNotFoundError,
    StartSession,
)

__all__ = [
    "AbortSession",
    "CreateSession",
    "CreateSessionCommand",
    "ForbiddenForRoleError",
    "GetSession",
    "GetSnapshot",
    "InferenceNotReadyError",
    "ListSessions",
    "ParticipantNotAssignedError",
    "ParticipantView",
    "ScenarioVersionNotFoundError",
    "SessionDetailView",
    "SessionNotFoundError",
    "SessionSnapshotView",
    "StartSession",
    "assemble_session_detail",
    "build_guard_runtime",
    "can_observe",
    "resolve_participant",
]
