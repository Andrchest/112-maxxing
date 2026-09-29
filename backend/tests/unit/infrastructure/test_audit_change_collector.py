"""The «было → стало» collector (I7 E43): `app.application.ports.audit_changes` and its
`ContextVar` adapter — no database, no request.

* a pair that did not change is dropped; values become JSON (enum, id, date, model, collection);
* a secret never carries a value — `record_secret`, and `record` on a secret-looking field name
  whatever the caller passed; a `[qualifier]` is data, not part of the name;
* outside an open scope nothing is kept; scopes do not leak into each other, and a copied context
  (a thread-pool dependency, a task) still appends to its request's list.
"""

from __future__ import annotations

import asyncio
import contextvars
from datetime import UTC, datetime
from enum import Enum
from uuid import UUID

import pytest
from app.application.ports.audit_changes import (
    NO_AUDIT_CHANGES,
    AuditChange,
    AuditChangeCollector,
    AuditChangeScope,
    audit_value,
    is_secret_field,
    make_change,
)
from app.infrastructure.audit import ContextVarAuditChanges
from pydantic import BaseModel


class _Role(str, Enum):
    ADMIN = "ADMIN"


class _Timers(BaseModel):
    accept_within_ms: int
    fill_within_ms: int | None = None


def test_values_become_json() -> None:
    identifier = UUID("3f6c1a20-0e1a-4b1e-9d2a-0a7c5b2f1d11")
    assert audit_value(_Role.ADMIN) == "ADMIN"
    assert audit_value(identifier) == str(identifier)
    assert audit_value(datetime(2026, 9, 29, tzinfo=UTC)) == "2026-09-29T00:00:00+00:00"
    assert audit_value(_Timers(accept_within_ms=5)) == {
        "accept_within_ms": 5,
        "fill_within_ms": None,
    }
    assert audit_value((1, identifier)) == [1, str(identifier)]
    assert audit_value(frozenset({"b", "a"})) == ["a", "b"]
    assert audit_value({"k": _Role.ADMIN}) == {"k": "ADMIN"}


def test_an_unchanged_pair_is_dropped() -> None:
    assert make_change("user", "user_role", _Role.ADMIN, "ADMIN") is None
    assert make_change("user", "user_role", "TRAINEE", "ADMIN") == AuditChange(
        field="user.user_role", before="TRAINEE", after="ADMIN"
    )


@pytest.mark.parametrize(
    ("entity", "field"),
    [
        ("user", "password"),
        ("user", "password_hash"),
        ("user", "sip_ha1"),
        ("voice", "token"),
        ("livekit", "api_key"),
        ("settings", "jwt_secret"),
    ],
)
def test_a_secret_field_never_keeps_a_value(entity: str, field: str) -> None:
    assert is_secret_field(entity, field)
    assert make_change(entity, field, "old-secret", "new-secret") == AuditChange(
        field=f"{entity}.{field}", before=None, after=None
    )


def test_a_qualifier_is_not_part_of_the_name() -> None:
    assert not is_secret_field("score", "rule_points[ask_key_question]")
    assert not is_secret_field("scenario_version", "content_sha256")
    assert not is_secret_field("lesson", "weight[2]")


def test_the_adapter_implements_both_ports_and_the_null_one_records_nothing() -> None:
    changes = ContextVarAuditChanges()
    assert isinstance(changes, AuditChangeCollector)
    assert isinstance(changes, AuditChangeScope)
    NO_AUDIT_CHANGES.record("user", "user_role", "A", "B")
    NO_AUDIT_CHANGES.record_secret("user", "password")


def test_outside_a_scope_nothing_is_kept() -> None:
    changes = ContextVarAuditChanges()
    changes.record("user", "user_role", "A", "B")
    token = changes.open()
    assert changes.close(token) == ()


def test_a_scope_collects_in_order_and_secrets_without_values() -> None:
    changes = ContextVarAuditChanges()
    token = changes.open()
    changes.record("user", "display_name_ru", None, "Иванов")
    changes.record("user", "user_role", "ADMIN", "ADMIN")  # unchanged: dropped
    changes.record("user", "password_hash", None, "argon2$digest")  # a secret by name
    changes.record_secret("user", "password")
    assert changes.close(token) == (
        AuditChange(field="user.display_name_ru", before=None, after="Иванов"),
        AuditChange(field="user.password_hash", before=None, after=None),
        AuditChange(field="user.password", before=None, after=None),
    )
    changes.record("user", "user_role", "A", "B")  # the scope is closed
    assert changes.close(changes.open()) == ()


async def test_concurrent_requests_do_not_share_a_list_and_copies_share_theirs() -> None:
    changes = ContextVarAuditChanges()

    async def request(name: str) -> tuple[AuditChange, ...]:
        token = changes.open()
        await asyncio.sleep(0)
        changes.record("group", "name_ru", None, name)
        # a copied context (FastAPI's thread pool, a task group) appends to the same list
        contextvars.copy_context().run(changes.record, "group", "members", None, [name])
        await asyncio.to_thread(changes.record, "comment", "text", None, name)
        await asyncio.sleep(0)
        return changes.close(token)

    first, second = await asyncio.gather(request("A"), request("B"))
    assert [change.after for change in first] == ["A", ["A"], "A"]
    assert [change.after for change in second] == ["B", ["B"], "B"]
