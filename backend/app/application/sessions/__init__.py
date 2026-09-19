"""Session-lifecycle use cases (E5, HLD `10-domain-model.md` §10.8, §10.10, D3, D5, D6).

`CreateSession`, `StartSession` and `AbortSession` — one Unit of Work transaction each (D5) — plus
`build_guard_runtime`, the pure projection of `GuardRuntime` from a session's event log.

Completing a session is not here: the completing use case owns `SESSION_COMPLETED.total_events`
and is first needed by the Operator-112 single-role flow — TODO(E7).
"""

from __future__ import annotations

from app.application.sessions.abort_session import AbortSession
from app.application.sessions.create_session import (
    CreateSession,
    CreateSessionCommand,
    ScenarioVersionNotFoundError,
)
from app.application.sessions.guard_context import build_guard_runtime
from app.application.sessions.start_session import SessionNotFoundError, StartSession

__all__ = [
    "AbortSession",
    "CreateSession",
    "CreateSessionCommand",
    "ScenarioVersionNotFoundError",
    "SessionNotFoundError",
    "StartSession",
    "build_guard_runtime",
]
