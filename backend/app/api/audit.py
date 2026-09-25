"""What an endpoint tells the audit middleware (I4 E25, `71-i4-wave4.md` §71.2, D31).

The middleware (`app.api.main.AuditMiddleware`) writes its entry **after** the response, from the
ASGI scope alone: the route's path template and operationId, the path parameters, the status. Three
facts are known only inside the endpoint, and each is left on the connection's `state` (which is
the scope's own `state` dict, so the middleware reads it back):

* `remember_user` — who the caller is. `get_current_user` and the WebSocket's token check call it,
  so every authenticated request carries its `user_id` and role without the middleware decoding a
  token a second time;
* `mark_recorded` — the endpoint wrote its own entry (`loginUser`: `LOGIN_SUCCEEDED` /
  `LOGIN_FAILED`), so the middleware writes none and every request stays exactly one entry;
* `mark_ws_refused` — the WebSocket was accepted only to deliver a §40.1 `44xx` close code, so the
  connect is a refusal, not a `WS_CONNECTED`.

Nothing here reads or stores a body, a header or a token (SPEC §41).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from starlette.requests import HTTPConnection

from app.application.auth.get_current_user import AuthenticatedUser

__all__ = [
    "AUDIT_RECORDED_KEY",
    "AUDIT_USER_KEY",
    "AUDIT_WS_REFUSED_KEY",
    "mark_recorded",
    "mark_ws_refused",
    "remember_user",
]

AUDIT_USER_KEY = "audit_user"
AUDIT_RECORDED_KEY = "audit_recorded"
AUDIT_WS_REFUSED_KEY = "audit_ws_refused"


def remember_user(connection: HTTPConnection, user: AuthenticatedUser) -> None:
    """The authenticated caller of this request or socket."""
    setattr(connection.state, AUDIT_USER_KEY, user)


def mark_recorded(connection: HTTPConnection) -> None:
    """This endpoint wrote its own audit entry; the middleware must not add another."""
    setattr(connection.state, AUDIT_RECORDED_KEY, True)


def mark_ws_refused(connection: HTTPConnection, close_code: int) -> None:
    """This socket is accepted only to be closed with `close_code` (§40.1)."""
    setattr(connection.state, AUDIT_WS_REFUSED_KEY, close_code)


def scope_state(scope: Mapping[str, Any]) -> Mapping[str, Any]:
    """The scope's `state` dict (what `connection.state` wraps), or an empty mapping."""
    state = scope.get("state")
    return state if isinstance(state, Mapping) else {}
