"""«Грамотность и адреса» — the pure fold over a card's texts and a session's ДДС comments (I4
E35, HLD 71 §71.12, D35).

A `FakeChecker` stands in for `TextCheckerPort`, so these tests pin the module's own reading of
"which text goes where" and "what does absence look like" without paying for the real dictionary
(`test_text_checker.py`, infra, covers the real data).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.ports.text_checker import MisspelledSpan, StreetLookup, StreetStatusKind
from app.application.reports.text_quality import (
    UNAVAILABLE_MESSAGE_RU,
    TextQualitySource,
    flagged_issue_count,
    is_operator_source,
    text_quality_issue_count,
    text_quality_report,
)
from app.domain.events.types import EventType


@dataclass(frozen=True, slots=True)
class _Event:
    event_type: EventType
    payload: dict[str, Any]


class FakeChecker:
    """`misspellings` flags any word literally spelled `"ошибка"`; `street_status` is `KNOWN`
    for `"Известная улица"` and `NEAR` (one suggestion) for everything else — `UNKNOWN` with
    `suggest=False`, as the real adapter answers. Every `suggest` it was asked with is recorded."""

    dictionary_sha256 = "dict-sha"
    street_list_sha256 = "streets-sha"

    def __init__(self) -> None:
        self.suggest_args: list[bool] = []

    def misspellings(self, text: str, *, suggest: bool = True) -> tuple[MisspelledSpan, ...]:
        self.suggest_args.append(suggest)
        if "ошибка" not in text:
            return ()
        start = text.index("ошибка")
        suggestions = ("верно",) if suggest else ()
        return (MisspelledSpan(start=start, end=start + 6, word="ошибка", suggestions=suggestions),)

    def street_status(
        self, street: str, locality: str | None = None, *, suggest: bool = True
    ) -> StreetLookup:
        self.suggest_args.append(suggest)
        if street == "Известная улица":
            return StreetLookup(status=StreetStatusKind.KNOWN)
        if not suggest:
            return StreetLookup(status=StreetStatusKind.UNKNOWN)
        return StreetLookup(status=StreetStatusKind.NEAR, suggestions=("Известная улица",))


def test_no_checker_is_unavailable_and_never_raises() -> None:
    report = text_quality_report(card_values=None, events=(), checker=None)
    assert report.available is False
    assert report.fields == ()
    assert report.dictionary_sha256 is None
    assert report.street_list_sha256 is None
    assert report.unavailable_message_ru == UNAVAILABLE_MESSAGE_RU


def test_no_checker_beats_a_present_card_and_events() -> None:
    """Absence of the checker, not absence of text, is what makes the section unavailable."""
    report = text_quality_report(
        card_values={"address.street": "ошибка"},
        events=(_Event(EventType.DDS_INCIDENT_CLOSED, {"comment_ru": "ошибка"}),),
        checker=None,
    )
    assert report.available is False
    assert report.fields == ()


def test_the_three_card_fields_are_checked_and_labelled() -> None:
    card_values = {
        "address.street": "Известная улица",
        "description.text": "текст с ошибка внутри",
        "recipients.comment": "без нарушений",
        "recipients.services": ["FIRE_RESCUE"],  # not a text field: ignored, not a crash
    }
    report = text_quality_report(card_values=card_values, events=(), checker=FakeChecker())
    assert report.available is True
    by_source = {field.source: field for field in report.fields}
    assert set(by_source) == {
        TextQualitySource.ADDRESS_STREET,
        TextQualitySource.DESCRIPTION_TEXT,
        TextQualitySource.RECIPIENTS_COMMENT,
    }
    assert by_source[TextQualitySource.ADDRESS_STREET].street == StreetLookup(
        status=StreetStatusKind.KNOWN
    )
    assert by_source[TextQualitySource.DESCRIPTION_TEXT].misspellings[0].word == "ошибка"
    assert by_source[TextQualitySource.DESCRIPTION_TEXT].street is None
    assert by_source[TextQualitySource.RECIPIENTS_COMMENT].misspellings == ()


def test_a_blank_or_missing_card_field_is_skipped() -> None:
    report = text_quality_report(
        card_values={"address.street": "   ", "description.text": None},
        events=(),
        checker=FakeChecker(),
    )
    assert report.fields == ()


def test_a_seeded_misspelling_in_a_dds_comment_appears_in_the_section() -> None:
    """§71.12's own acceptance item, at this module's level."""
    events = (
        _Event(EventType.DDS_SERVICE_STATUS_SET, {"comment_ru": "ошибка в номере наряда"}),
        _Event(EventType.DDS_CARD_ISSUE_FLAGGED, {"comment_ru": "здесь ошибка тоже"}),
        _Event(EventType.DDS_INCIDENT_CLOSED, {"comment_ru": "закрыто без нарушений"}),
        _Event(EventType.DDS_INCIDENT_CLOSED, {"comment_ru": None}),  # not yet closed: skipped
        _Event(EventType.HANDOFF_RECEIVED, {"comment_ru": "ошибка"}),  # not a text-quality event
    )
    report = text_quality_report(card_values=None, events=events, checker=FakeChecker())
    by_source = {field.source: field for field in report.fields}
    assert set(by_source) == {
        TextQualitySource.DDS_STATUS_COMMENT,
        TextQualitySource.DDS_CARD_ISSUE_COMMENT,
        TextQualitySource.DDS_CLOSE_COMMENT,
    }
    assert by_source[TextQualitySource.DDS_STATUS_COMMENT].misspellings[0].word == "ошибка"
    assert by_source[TextQualitySource.DDS_CLOSE_COMMENT].misspellings == ()
    assert all(field.street is None for field in report.fields)


def test_the_data_sha_is_recorded_on_the_report() -> None:
    report = text_quality_report(card_values=None, events=(), checker=FakeChecker())
    assert report.dictionary_sha256 == "dict-sha"
    assert report.street_list_sha256 == "streets-sha"


def test_is_operator_source_splits_card_fields_from_dds_comments() -> None:
    assert is_operator_source(TextQualitySource.ADDRESS_STREET) is True
    assert is_operator_source(TextQualitySource.DESCRIPTION_TEXT) is True
    assert is_operator_source(TextQualitySource.RECIPIENTS_COMMENT) is True
    assert is_operator_source(TextQualitySource.DDS_STATUS_COMMENT) is False
    assert is_operator_source(TextQualitySource.DDS_CARD_ISSUE_COMMENT) is False
    assert is_operator_source(TextQualitySource.DDS_CLOSE_COMMENT) is False


# -- flagged_issue_count (I7 E50) --------------------------------------------------------------


def test_flagged_issue_count_is_none_when_the_checker_is_unavailable() -> None:
    report = text_quality_report(card_values=None, events=(), checker=None)
    assert flagged_issue_count(report) is None


def test_flagged_issue_count_sums_misspellings_and_non_known_streets() -> None:
    """One misspelling in `description.text`, one `NEAR` street (`address.street` is never
    `"Известная улица"` here) — mirrors `flaggedTextQualityItems`' one-row-per-item counting on
    the client (`frontend/src/entities/text-quality/format.ts`)."""
    card_values = {
        "address.street": "Незнакомая улица",
        "description.text": "текст с ошибка внутри",
        "recipients.comment": "без нарушений",
    }
    report = text_quality_report(card_values=card_values, events=(), checker=FakeChecker())
    assert flagged_issue_count(report) == 2


def test_flagged_issue_count_is_zero_with_nothing_to_flag() -> None:
    report = text_quality_report(
        card_values={"address.street": "Известная улица"}, events=(), checker=FakeChecker()
    )
    assert flagged_issue_count(report) == 0


# -- text_quality_issue_count (I7 E57) ---------------------------------------------------------


def test_the_issue_count_asks_the_checker_for_no_suggestions() -> None:
    """E57: the count is taken per session on every `getMyHistory`; the suggestion search is the
    expensive part and the count never shows it, so every checker read passes `suggest=False`."""
    checker = FakeChecker()
    count = text_quality_issue_count(
        card_values={"address.street": "Незнакомая улица", "description.text": "ошибка"},
        events=(_Event(EventType.DDS_INCIDENT_CLOSED, {"comment_ru": "ещё ошибка"}),),
        checker=checker,
    )
    assert count == 3
    # the street: spelling + directory; the description; the ДДС comment — all four without.
    assert checker.suggest_args == [False, False, False, False]


def test_the_issue_count_equals_the_full_report_s_count() -> None:
    """`NEAR` (full report) and `UNKNOWN` (no suggestions) both count one: same number."""
    card_values = {"address.street": "Незнакомая улица", "description.text": "текст с ошибка"}
    events = (_Event(EventType.DDS_SERVICE_STATUS_SET, {"comment_ru": "ошибка"}),)
    full = text_quality_report(card_values=card_values, events=events, checker=FakeChecker())
    assert text_quality_issue_count(
        card_values=card_values, events=events, checker=FakeChecker()
    ) == flagged_issue_count(full)


def test_the_issue_count_is_none_without_a_checker() -> None:
    assert text_quality_issue_count(card_values=None, events=(), checker=None) is None
