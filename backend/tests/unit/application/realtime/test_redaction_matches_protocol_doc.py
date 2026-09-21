"""`redact` agrees with the §40.4 tables — parsed from the markdown, never retyped here.

`40-realtime-protocol.md` §40.4 is the specification of `app.application.realtime.redaction`, so
this test reads that document at test time and asserts, for every one of the 49 event types and
both trainee roles, that the function's verdict matches the row:

* `—` → `redact` returns `None`: "the push loop never serialises it for that connection";
* `✔` → the full catalog payload, `redacted_keys == []`;
* `◆` → withheld when `SessionPolicy.show_asr_partials` is false (`ASSESSMENT`), full otherwise;
* `▲` → pushed with exactly the keys the row's "Redaction for trainee roles" column leaves, and
  `redacted_keys` naming exactly what it removes. The column is parsed in its own two dialects —
  "trainee receives only `{a, b, c}`" and "drop `a`, `b`" — and a row that names a delivery
  condition ("pushed only when `k` equals the connection's role") is additionally asserted to
  return `None` when that key names the *other* role.

The `INSTRUCTOR` column is asserted as its own invariant: every type, every key, no redaction.

Nothing here restates §40.4. Changing the document without changing `redaction.py` fails this
test, and changing `redaction.py` without changing the document fails it too — which is what
makes the doc the specification rather than a description.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.application.realtime.effective_role import INSTRUCTOR
from app.application.realtime.redaction import SourceEvent, redact
from app.domain.enums import ActorType, RoleType, SessionMode
from app.domain.events.catalog import EVENT_PAYLOAD_CATALOG
from app.domain.events.types import EventType
from app.domain.session.policy import SESSION_POLICIES

PROTOCOL_DOC_PATH = Path(__file__).resolve().parents[5] / "docs" / "hld" / "40-realtime-protocol.md"

_ROW_RE = re.compile(
    r"^\|\s*\d+\s*\|\s*`(?P<event_type>[A-Z_]+)`\s*\|\s*(?P<operator>[^|]*?)\s*\|"
    r"\s*(?P<dds>[^|]*?)\s*\|\s*(?P<instructor>[^|]*?)\s*\|\s*(?P<redaction>[^|]*?)\s*\|\s*$",
    re.MULTILINE,
)
_RECEIVES_ONLY_RE = re.compile(r"receives only\s*`?\{(?P<keys>[^}]*)\}`?")
_DROP_RE = re.compile(r"drops?\s+(?P<keys>(?:`[a-z_0-9]+`[,/]?\s*(?:and\s*)?)+)")
_DELIVERY_RE = re.compile(r"pushed only when\s*`(?P<key>[a-z_]+)`\s*equals")
_BACKTICKED = re.compile(r"`([a-z_0-9]+)`")

#: Two modes, differing only in `show_asr_partials` (§10.10) — §40.4's one `◆` row needs both.
_PARTIALS_ON = SESSION_POLICIES[SessionMode.MULTI_TRAINEE]
_PARTIALS_OFF = SESSION_POLICIES[SessionMode.ASSESSMENT]


@dataclass(frozen=True)
class _Row:
    event_type: EventType
    cells: dict[RoleType, str]
    redaction: str


def _parse() -> dict[EventType, _Row]:
    text = PROTOCOL_DOC_PATH.read_text(encoding="utf-8")
    header = re.search(
        r"^\|\s*#\s*\|\s*Event type\s*\|\s*OPERATOR_112\s*\|\s*DDS\s*\|\s*INSTRUCTOR\s*\|"
        r"\s*Redaction for trainee roles\s*\|",
        text,
        re.MULTILINE,
    )
    assert header is not None, "§40.4 table header shape changed — update this parser"
    rows: dict[EventType, _Row] = {}
    for match in _ROW_RE.finditer(text):
        event_type = EventType(match.group("event_type"))
        rows[event_type] = _Row(
            event_type=event_type,
            cells={
                RoleType.OPERATOR_112: match.group("operator").strip(),
                RoleType.DDS: match.group("dds").strip(),
            },
            redaction=match.group("redaction").strip(),
        )
    return rows


ROWS = _parse()
TRAINEE_ROLES = (RoleType.OPERATOR_112, RoleType.DDS)


def _delivery_key(row: _Row) -> str | None:
    """The payload key §40.4 says this row's delivery is filtered on, or `None`."""
    match = _DELIVERY_RE.search(row.redaction)
    return None if match is None else match.group("key")


#: The (role, event type) pairs whose §40.4 row can be observed *in the negative*: the row is
#: delivered to that trainee role at all, and its delivery is filtered on a payload key.
#:
#: Built as a list rather than generated for every one of the 98 combinations and skipped: a
#: skipped case asserts nothing and hides rot behind a number nobody reads, so the cases that
#: have nothing to assert are simply not generated. `test_the_delivery_filtered_cases_are_the_
#: three_documented_rows` below is what keeps that list honest.
DELIVERY_FILTERED_CASES: tuple[tuple[RoleType, EventType], ...] = tuple(
    (role, event_type)
    for role in TRAINEE_ROLES
    for event_type in EventType
    if ROWS[event_type].cells[role] != "—" and _delivery_key(ROWS[event_type]) is not None
)


def _expected_removed(row: _Row) -> frozenset[str]:
    """The keys §40.4's redaction column says a trainee does **not** receive."""
    keys = frozenset(EVENT_PAYLOAD_CATALOG[row.event_type].payload_keys)
    only = _RECEIVES_ONLY_RE.search(row.redaction)
    if only is not None:
        kept = frozenset(name.strip() for name in only.group("keys").split(",") if name.strip())
        assert kept <= keys, f"{row.event_type}: §40.4 keeps a key the catalog has not got"
        return keys - kept
    dropped = _DROP_RE.search(row.redaction)
    if dropped is None:
        return frozenset()
    return frozenset(_BACKTICKED.findall(dropped.group("keys")))


def _payload(event_type: EventType, role: RoleType) -> dict[str, object]:
    """A full catalog payload whose role discriminators, if any, name `role`."""
    payload: dict[str, object] = {}
    for key in EVENT_PAYLOAD_CATALOG[event_type].payload_keys:
        if key in ("role_type", "audience_role", "to_role"):
            payload[key] = role.value
        else:
            payload[key] = f"<{key}>"
    return payload


def _event(event_type: EventType, payload: dict[str, object]) -> SourceEvent:
    return SourceEvent(
        seq_no=7,
        event_type=event_type,
        timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
        monotonic_offset_ms=1234,
        actor_type=ActorType.SIMULATION,
        payload=payload,
    )


def test_the_parser_sees_all_49_rows() -> None:
    """A guard on the guard: a parser that silently matched nothing would pass every test."""
    assert frozenset(ROWS) == frozenset(EventType)


@pytest.mark.parametrize("event_type", list(EventType))
@pytest.mark.parametrize("role", TRAINEE_ROLES)
def test_trainee_verdict_matches_the_protocol_table(event_type: EventType, role: RoleType) -> None:
    row = ROWS[event_type]
    cell = row.cells[role]
    payload = _payload(event_type, role)
    envelope = redact(_event(event_type, payload), role, _PARTIALS_ON)

    if cell == "—":
        assert envelope is None, f"§40.4 withholds {event_type} from {role.value}"
        return

    assert envelope is not None, f"§40.4 pushes {event_type} to {role.value}"
    removed = _expected_removed(row)
    assert frozenset(payload) - frozenset(envelope.payload) == removed
    assert tuple(envelope.redacted_keys) == tuple(sorted(removed))


def test_the_delivery_filtered_cases_are_the_three_documented_rows() -> None:
    """A guard on the case list: the parametrisation below must not quietly become empty.

    §40.4 has exactly three delivery-filtered rows — 30 `STAGE_STATE_CHANGED.role_type`,
    37 `NOTIFICATION_CREATED.audience_role` and 39 `RADIO_MESSAGE_CREATED.to_role` — and each is
    pushed to both trainee roles, so the list is six pairs. Row 38
    (`NOTIFICATION_ACKNOWLEDGED`) is deliberately absent: its payload carries no audience key
    (TODO(E9) in `redaction.py`), so the document states no condition to parse.
    """
    assert {event_type for _, event_type in DELIVERY_FILTERED_CASES} == {
        EventType.STAGE_STATE_CHANGED,
        EventType.NOTIFICATION_CREATED,
        EventType.RADIO_MESSAGE_CREATED,
    }
    assert len(DELIVERY_FILTERED_CASES) == 6


@pytest.mark.parametrize(("role", "event_type"), DELIVERY_FILTERED_CASES)
def test_delivery_filtered_rows_withhold_the_other_roles_event(
    role: RoleType, event_type: EventType
) -> None:
    """§40.4's "pushed only when `k` equals the connection's role" rows, in the negative."""
    key = _delivery_key(ROWS[event_type])
    assert key is not None
    other = RoleType.DDS if role is RoleType.OPERATOR_112 else RoleType.OPERATOR_112
    payload = _payload(event_type, role) | {key: other.value}
    assert redact(_event(event_type, payload), role, _PARTIALS_ON) is None


@pytest.mark.parametrize("event_type", list(EventType))
def test_instructor_receives_every_type_unredacted(event_type: EventType) -> None:
    """§40.2: `redacted_keys` "is always `[]` for the `INSTRUCTOR` role"."""
    payload = _payload(event_type, RoleType.OPERATOR_112)
    envelope = redact(_event(event_type, payload), INSTRUCTOR, _PARTIALS_ON)
    assert envelope is not None
    assert dict(envelope.payload) == payload
    assert envelope.redacted_keys == ()


def test_asr_partial_is_withheld_when_show_asr_partials_is_false() -> None:
    """§40.4's one `◆` row: "the whole event is withheld in `ASSESSMENT`" (§10.10)."""
    payload = _payload(EventType.ASR_PARTIAL, RoleType.OPERATOR_112)
    event = _event(EventType.ASR_PARTIAL, payload)
    assert redact(event, RoleType.OPERATOR_112, _PARTIALS_ON) is not None
    assert redact(event, RoleType.OPERATOR_112, _PARTIALS_OFF) is None
    # The instructor still sees it: the `◆` gate is a trainee-side policy, not a suppression.
    assert redact(event, INSTRUCTOR, _PARTIALS_OFF) is not None


def test_an_unwhitelisted_payload_key_is_hidden_from_trainees_and_named() -> None:
    """D3's failure direction: a key nobody whitelisted is hidden, not leaked.

    A payload key added to the catalog later — or invented by a producer — must be absent for a
    trainee and present for the instructor, with `redacted_keys` telling the UI it exists.
    """
    payload = _payload(EventType.CARD_FIELD_CHANGED, RoleType.OPERATOR_112)
    payload["invented_by_a_future_epic"] = "secret"
    event = _event(EventType.CARD_FIELD_CHANGED, payload)

    trainee = redact(event, RoleType.OPERATOR_112, _PARTIALS_ON)
    assert trainee is not None
    assert "invented_by_a_future_epic" not in trainee.payload
    assert "invented_by_a_future_epic" in trainee.redacted_keys

    instructor = redact(event, INSTRUCTOR, _PARTIALS_ON)
    assert instructor is not None
    assert instructor.payload["invented_by_a_future_epic"] == "secret"
