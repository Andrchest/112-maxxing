"""Ruling R6 of this task's brief: `DataVisibilityPolicy.visible_event_types` (per `RoleModule`)
and `EventSpec.visible_to` (`events/catalog.py`) must agree with the OPERATOR_112/DDS/INSTRUCTOR
columns of `docs/hld/40-realtime-protocol.md` §40.4 — "this table and `EVENT_PAYLOAD_CATALOG` are
one fact expressed twice" (§40.4's own "Consistency rule for implementers").

Nothing here is retyped: the two §40.4 markdown tables are parsed at test time. A cell is "visible"
when it is not the em dash `—` (a `✔`/`▲`/`◆` all count — the `▲` redaction and the `◆`
`show_asr_partials` gate are *payload*/*delivery* concerns applied downstream of this whitelist,
per the module docstrings of `roles/operator112.py`/`roles/dds.py`/`events/catalog.py`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest
from app.domain.enums import RoleType
from app.domain.events.catalog import EVENT_PAYLOAD_CATALOG
from app.domain.events.types import EventType
from app.domain.roles.dds import DDSModule
from app.domain.roles.operator112 import Operator112Module

PROTOCOL_DOC_PATH = Path(__file__).resolve().parents[5] / "docs" / "hld" / "40-realtime-protocol.md"

# One row: "| 12 | `CALLER_TTS_STARTED` | ▲ | — | ✔ | ... |" — captures the event-type name and the
# OPERATOR_112 / DDS / INSTRUCTOR cells (in that order, per the header row §40.4 actually prints).
_ROW_RE = re.compile(
    r"^\|\s*\d+\s*\|\s*`(?P<event_type>[A-Z_]+)`\s*\|\s*(?P<operator>[^|]+?)\s*\|"
    r"\s*(?P<dds>[^|]+?)\s*\|\s*(?P<instructor>[^|]+?)\s*\|",
    re.MULTILINE,
)


@dataclass(frozen=True)
class _Row:
    event_type: EventType
    operator_visible: bool
    dds_visible: bool
    instructor_visible: bool


def _cell_visible(cell: str) -> bool:
    return cell.strip() != "—"


def _parse_protocol_table() -> dict[EventType, _Row]:
    text = PROTOCOL_DOC_PATH.read_text(encoding="utf-8")
    # Confirm the column order against the header row itself — nothing here is hardcoded past it.
    header_match = re.search(
        r"^\|\s*#\s*\|\s*Event type\s*\|\s*OPERATOR_112\s*\|\s*DDS\s*\|\s*INSTRUCTOR\s*\|",
        text,
        re.MULTILINE,
    )
    assert header_match is not None, "§40.4 table header shape changed — update this parser"

    rows: dict[EventType, _Row] = {}
    for match in _ROW_RE.finditer(text):
        event_type = EventType(match.group("event_type"))
        rows[event_type] = _Row(
            event_type=event_type,
            operator_visible=_cell_visible(match.group("operator")),
            dds_visible=_cell_visible(match.group("dds")),
            instructor_visible=_cell_visible(match.group("instructor")),
        )
    return rows


_PARSED_ROWS = _parse_protocol_table()


def test_protocol_table_parses_all_49_event_types() -> None:
    assert frozenset(_PARSED_ROWS) == frozenset(EventType)


def test_instructor_column_is_ticked_for_every_row() -> None:
    """Sanity check on the parser itself: every §40.4 row's INSTRUCTOR cell is `✔` (§10.13:
    "INSTRUCTOR" never absent from a "Visible to" set)."""
    for row in _PARSED_ROWS.values():
        assert row.instructor_visible, row.event_type


def test_operator_112_visible_event_types_matches_the_protocol_table_column() -> None:
    expected = {event_type for event_type, row in _PARSED_ROWS.items() if row.operator_visible}
    actual = Operator112Module().visibility_policy.visible_event_types
    assert actual == expected


def test_dds_visible_event_types_matches_the_protocol_table_column() -> None:
    expected = {event_type for event_type, row in _PARSED_ROWS.items() if row.dds_visible}
    actual = DDSModule().visibility_policy.visible_event_types
    assert actual == expected


@pytest.mark.parametrize("event_type", list(EventType))
def test_event_spec_visible_to_matches_the_protocol_table_row(event_type: EventType) -> None:
    row = _PARSED_ROWS[event_type]
    expected: set[RoleType | str] = set()
    if row.operator_visible:
        expected.add(RoleType.OPERATOR_112)
    if row.dds_visible:
        expected.add(RoleType.DDS)
    if row.instructor_visible:
        expected.add("INSTRUCTOR")

    actual = EVENT_PAYLOAD_CATALOG[event_type].visible_to
    assert actual == expected, f"{event_type}: catalog visible_to disagrees with §40.4"
