"""«Грамотность и адреса» — the text-quality report section (I4 E35, HLD 71 §71.12, D35; ТЗ ¶329/
¶343 REQ-2276/2289 «…а также грамматики»).

**Report-time, read-only, no score effect** (D35; Q-E11-1 open — a scoring version would be an
11th `EvaluatorType`, a recorded SPEC §28 departure, and is not built here). Pure: a fold over the
texts the trainee actually typed, against an optional `TextCheckerPort` — the same "absence is a
real, reportable state" shape the rest of this package uses for `ReferencePort`.

**The two text sources** (§71.12's own list):

* the final 112 card — `address.street`, `description.text`, `recipients.comment`;
* the ДДС free-text comments — `DDS_SERVICE_STATUS_SET.comment_ru` (every status change, «Не
  принята»/«Отказ»'s required reason included, since it rides the same field),
  `DDS_CARD_ISSUE_FLAGGED.comment_ru` (the "reasons" a card issue was flagged) and
  `DDS_INCIDENT_CLOSED.comment_ru` (the close comment). This split of "the reasons" from the
  status comment is this module's own technical reading of §71.12's design prose — recorded here,
  not re-decided, because the design does not name the event.

`street_status` runs on `address.street` alone — "on the 112 card path only" (§71.12) — and never
on a ДДС comment, which has no street field. **Nothing here corrects a street name**: a lookup
result is attached to the field's own text, and the scenario/ticket text is never rewritten
(D-h — ticket-15-call-3's organizer-verbatim «Зверенецкая» is a `NEAR` flag here, not a fix).

`available=False` renders «Проверка недоступна: словарь/справочник не установлен» and **never**
«0 ошибок» (SPEC §27's honesty rule) — the one difference between "the checker found nothing" and
"the checker did not run".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from app.application.ports.text_checker import (
    MisspelledSpan,
    StreetLookup,
    TextCheckerPort,
)
from app.domain.common.values import FactValue
from app.domain.events.types import EventType

__all__ = [
    "TEXT_QUALITY_EVENT_TYPES",
    "UNAVAILABLE_MESSAGE_RU",
    "TextQualityField",
    "TextQualityReport",
    "TextQualitySource",
    "text_quality_report",
]

UNAVAILABLE_MESSAGE_RU = "Проверка недоступна: словарь/справочник не установлен"
"""SPEC §27's honesty rule: never «0 ошибок» when the checker did not run."""


class TextQualitySource(str, Enum):
    """Which trainee-typed field a `TextQualityField` annotates."""

    ADDRESS_STREET = "ADDRESS_STREET"
    DESCRIPTION_TEXT = "DESCRIPTION_TEXT"
    RECIPIENTS_COMMENT = "RECIPIENTS_COMMENT"
    DDS_STATUS_COMMENT = "DDS_STATUS_COMMENT"
    DDS_CARD_ISSUE_COMMENT = "DDS_CARD_ISSUE_COMMENT"
    DDS_CLOSE_COMMENT = "DDS_CLOSE_COMMENT"


_OPERATOR_SOURCES = frozenset(
    {
        TextQualitySource.ADDRESS_STREET,
        TextQualitySource.DESCRIPTION_TEXT,
        TextQualitySource.RECIPIENTS_COMMENT,
    }
)
"""The 112-card sources — gated by `visibility.shows_operator_sections` (mirrors `norms.py`)."""

_CARD_FIELDS: tuple[tuple[str, TextQualitySource], ...] = (
    ("address.street", TextQualitySource.ADDRESS_STREET),
    ("description.text", TextQualitySource.DESCRIPTION_TEXT),
    ("recipients.comment", TextQualitySource.RECIPIENTS_COMMENT),
)

TEXT_QUALITY_EVENT_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.DDS_SERVICE_STATUS_SET,
        EventType.DDS_CARD_ISSUE_FLAGGED,
        EventType.DDS_INCIDENT_CLOSED,
    }
)
"""Every event type this module reads; a caller may pass the whole log, others are ignored."""

_DDS_EVENT_SOURCES: Mapping[EventType, TextQualitySource] = {
    EventType.DDS_SERVICE_STATUS_SET: TextQualitySource.DDS_STATUS_COMMENT,
    EventType.DDS_CARD_ISSUE_FLAGGED: TextQualitySource.DDS_CARD_ISSUE_COMMENT,
    EventType.DDS_INCIDENT_CLOSED: TextQualitySource.DDS_CLOSE_COMMENT,
}


class _Event(Protocol):
    @property
    def event_type(self) -> EventType: ...

    @property
    def payload(self) -> Mapping[str, Any]: ...


def is_operator_source(source: TextQualitySource) -> bool:
    """`True` for the three 112-card sources, `False` for the three ДДС ones."""
    return source in _OPERATOR_SOURCES


@dataclass(frozen=True, slots=True)
class TextQualityField:
    """One checked text: which field, its misspellings, and — `ADDRESS_STREET` only — the street
    lookup."""

    source: TextQualitySource
    text: str
    misspellings: tuple[MisspelledSpan, ...]
    street: StreetLookup | None = None


@dataclass(frozen=True, slots=True)
class TextQualityReport:
    """«Грамотность и адреса» — `available=False` is the whole report when the data is absent."""

    available: bool
    fields: tuple[TextQualityField, ...] = ()
    dictionary_sha256: str | None = None
    street_list_sha256: str | None = None
    unavailable_message_ru: str | None = None


def text_quality_report(
    *,
    card_values: Mapping[str, FactValue] | None,
    events: Sequence[_Event],
    checker: TextCheckerPort | None,
) -> TextQualityReport:
    """The section over one session's card and ДДС texts. `None` `checker` (or `card_values` and
    no ДДС text at all) still returns a value — never raises."""
    if checker is None:
        return TextQualityReport(available=False, unavailable_message_ru=UNAVAILABLE_MESSAGE_RU)
    fields = [
        *_card_fields(card_values, checker),
        *_dds_fields(events, checker),
    ]
    return TextQualityReport(
        available=True,
        fields=tuple(fields),
        dictionary_sha256=checker.dictionary_sha256,
        street_list_sha256=checker.street_list_sha256,
    )


def _card_fields(
    card_values: Mapping[str, FactValue] | None, checker: TextCheckerPort
) -> list[TextQualityField]:
    if not card_values:
        return []
    fields: list[TextQualityField] = []
    for field_path, source in _CARD_FIELDS:
        value = card_values.get(field_path)
        if not isinstance(value, str) or not value.strip():
            continue
        is_street = source is TextQualitySource.ADDRESS_STREET
        street = checker.street_status(value) if is_street else None
        fields.append(
            TextQualityField(
                source=source,
                text=value,
                misspellings=tuple(checker.misspellings(value)),
                street=street,
            )
        )
    return fields


def _dds_fields(events: Sequence[_Event], checker: TextCheckerPort) -> list[TextQualityField]:
    fields: list[TextQualityField] = []
    for event in events:
        source = _DDS_EVENT_SOURCES.get(event.event_type)
        if source is None:
            continue
        comment = event.payload.get("comment_ru")
        if not isinstance(comment, str) or not comment.strip():
            continue
        fields.append(
            TextQualityField(
                source=source, text=comment, misspellings=tuple(checker.misspellings(comment))
            )
        )
    return fields
