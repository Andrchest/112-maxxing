"""The API's routers (D8).

Eight modules, one per group of `openapi.yaml` operations: `auth` and `users` (D8's accounts),
`health`, `scenarios`, `sessions`, `operator` (the Operator 112 commands), `snapshot`
(`getSessionSnapshot`) and `realtime` (`listSessionEvents` and the WebSocket). Every one of them
is included by `create_app`, and the contract test walks the registered routes, so an operation
added to an existing module needs no change to `create_app` and is checked against the contract
automatically.

Every module here may import `app.application` and `app.api` only. Never `app.infrastructure`,
never `app.db`, and never a domain *layer* type from `app.domain.layers` — a response is an
`app.api.schemas` model built by an explicit mapping function (D2, D3).
`backend/tests/api/test_router_layering.py` scans this package and fails on any of them.
"""

from __future__ import annotations

from app.api.routers import (
    auth,
    health,
    operator,
    realtime,
    scenarios,
    sessions,
    snapshot,
    users,
)

__all__ = [
    "auth",
    "health",
    "operator",
    "realtime",
    "scenarios",
    "sessions",
    "snapshot",
    "users",
]
