"""`ContextVarAuditChanges` — `AuditChangeCollector` + `AuditChangeScope` over a `ContextVar`
(I7 E43, `docs/hld/71-i4-wave4.md` §71.19.43).

The audit middleware calls `open()` before it hands a request to the application and `close()`
after the response; every use case the request runs calls `record(...)` in between. The variable
holds a *mutable list*, so a copied context — a sync dependency in the thread pool, a task group —
still appends to the same request's list. Outside an open scope (the `SimulationRunner`, the
`LessonRunner`, a CLI) the variable is `None` and `record` does nothing.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

from app.application.ports.audit_changes import AuditChange, make_change

__all__ = ["ContextVarAuditChanges"]

_CHANGES: ContextVar[list[AuditChange] | None] = ContextVar("audit_changes", default=None)


class ContextVarAuditChanges:
    """One list per open scope; the collector and the scope in one object."""

    def record(self, entity: str, field: str, before: Any, after: Any) -> None:
        changes = _CHANGES.get()
        if changes is None:
            return
        change = make_change(entity, field, before, after)
        if change is not None:
            changes.append(change)

    def record_secret(self, entity: str, field: str) -> None:
        changes = _CHANGES.get()
        if changes is not None:
            changes.append(AuditChange(field=f"{entity}.{field}", before=None, after=None))

    def open(self) -> object:
        return _CHANGES.set([])

    def close(self, token: object) -> tuple[AuditChange, ...]:
        collected = tuple(_CHANGES.get() or ())
        if isinstance(token, Token):
            try:
                _CHANGES.reset(token)
            except ValueError:  # pragma: no cover - a token from another context: just clear
                _CHANGES.set(None)
        return collected
