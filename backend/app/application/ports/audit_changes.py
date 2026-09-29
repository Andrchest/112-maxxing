"""`AuditChangeCollector` port — the «было → стало» half of the audit (I7 E43, Q-E15-3, ТЗ ¶246,
¶296; `docs/hld/71-i4-wave4.md` §71.19.43).

E25's `audit_log` row says *who* ran *which* operation on *which* target. The owner asked for the
values as well: «Иванов изменил оценку с 42 на 50». A mutating use case outside the event-sourced
session flow reports each field it changed here, as `(entity, field, before, after)`; the audit
middleware reads what one request collected and writes it into that request's single row
(`audit_log.changes`, migration `0019_audit_changes`) — the row is still written once, after the
response, so the table stays append-only.

Three rules every caller gets for free:

* **Only a change is kept.** A pair whose normalised `before == after` is dropped, so a create
  records only the fields it set and an idempotent repeat records nothing.
* **A secret never is.** `record_secret` (a password, a hash, an HA1, a token, a key) keeps the
  field with `before`/`after` both `None` — the journal shows «изменён» and nothing else — and
  `record` itself refuses to carry a value for a field whose name looks secret
  (`is_secret_field`), whatever the caller passed.
* **Values become JSON** (`audit_value`): an enum its value, an id or a date its string, a pydantic
  model its JSON dump, a collection a list.

The adapter (`app.infrastructure.audit.context_change_collector`) keeps one list per request in a
`ContextVar`; outside a request (a background runner, a CLI) there is no list and `record` is a
no-op. `NO_AUDIT_CHANGES` is the null object a use case defaults to, so a use case built without
the port (a unit test) behaves exactly as before.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

__all__ = [
    "NO_AUDIT_CHANGES",
    "AuditChange",
    "AuditChangeCollector",
    "AuditChangeScope",
    "JsonValue",
    "audit_value",
    "is_secret_field",
    "make_change",
]

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None

#: Name parts that mark a field whose value must never reach the journal.
_SECRET_PARTS = frozenset(
    {"password", "passwd", "hash", "ha1", "token", "tokens", "secret", "key", "keys", "credential"}
)
_NAME_SPLIT = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class AuditChange:
    """One changed field: `field` is `"<entity>.<field>"` (e.g. `"user.user_role"`,
    `"lesson.weight[2]"`); `before`/`after` are both `None` for a secret («изменён»)."""

    field: str
    before: JsonValue
    after: JsonValue


def is_secret_field(entity: str, field: str) -> bool:
    """True when the entity or field name contains a secret-marking part (`password_hash`, …).

    A `[qualifier]` suffix (a card position, a rule id) is data, not the field's name: it is not
    looked at.
    """
    name = field.split("[", 1)[0]
    parts = set(_NAME_SPLIT.split(f"{entity}.{name}".lower()))
    return bool(parts & _SECRET_PARTS)


def audit_value(value: Any) -> JsonValue:
    """`value` as plain JSON — the only shape a change is stored in."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Enum):
        return audit_value(value.value)
    if isinstance(value, UUID | Decimal):
        return str(value) if isinstance(value, UUID) else float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return audit_value(model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): audit_value(item) for key, item in value.items()}
    if isinstance(value, set | frozenset):
        return sorted((audit_value(item) for item in value), key=str)
    if isinstance(value, Sequence):
        return [audit_value(item) for item in value]
    return str(value)


def make_change(entity: str, field: str, before: Any, after: Any) -> AuditChange | None:
    """The `AuditChange` to keep for this pair, or `None` when nothing changed.

    A secret-looking field keeps its name and loses both values, whatever was passed.
    """
    name = f"{entity}.{field}"
    if is_secret_field(entity, field):
        return AuditChange(field=name, before=None, after=None)
    normalised_before, normalised_after = audit_value(before), audit_value(after)
    if normalised_before == normalised_after:
        return None
    return AuditChange(field=name, before=normalised_before, after=normalised_after)


@runtime_checkable
class AuditChangeCollector(Protocol):
    """What a mutating use case reports into (the current request's list, if any)."""

    def record(self, entity: str, field: str, before: Any, after: Any) -> None:
        """One field of `entity` went from `before` to `after` (dropped when equal)."""
        ...

    def record_secret(self, entity: str, field: str) -> None:
        """A secret field changed: kept as «изменён», never with a value."""
        ...


@runtime_checkable
class AuditChangeScope(Protocol):
    """The middleware's side: open a fresh list for one request, take it back at the end."""

    def open(self) -> object:
        """Start collecting for the current request; returns a token for `close`."""
        ...

    def close(self, token: object) -> tuple[AuditChange, ...]:
        """Stop collecting and return what this request recorded, in order."""
        ...


class _NoAuditChanges:
    """The null collector: records nothing (a use case built without the port)."""

    def record(self, entity: str, field: str, before: Any, after: Any) -> None:
        return None

    def record_secret(self, entity: str, field: str) -> None:
        return None


NO_AUDIT_CHANGES: AuditChangeCollector = _NoAuditChanges()
