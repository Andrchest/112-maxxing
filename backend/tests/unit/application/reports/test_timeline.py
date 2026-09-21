"""The report's timeline projection and its Russian per-event summary (SPEC §29 item 4).

The load-bearing test here is the **totality** one: every `EventType` must have a
`SummaryTemplate`, so the day somebody adds an event type the suite fails until its Russian
sentence exists, rather than a trainee's report quietly showing an English enum name.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.application.realtime.redaction import RealtimeEnvelope
from app.application.reports.timeline import (
    PAYLOAD_LABELS_RU,
    SUMMARY_TEMPLATES,
    summary_ru,
    timeline_entry,
)
from app.domain.enums import ActorType
from app.domain.events.types import EventType

from tests.unit.domain.session._builders import user

FIXED_TIME = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)


def test_every_event_type_has_a_russian_summary() -> None:
    """Totality: `SUMMARY_TEMPLATES` covers `EventType` exactly — no gaps, no strays."""
    missing = sorted(member.value for member in EventType if member not in SUMMARY_TEMPLATES)
    assert missing == [], f"no Russian summary template for {missing}"
    stray = sorted(str(key) for key in SUMMARY_TEMPLATES if key not in set(EventType))
    assert stray == []


def test_every_title_is_russian_and_non_empty() -> None:
    """A template that fell back to the enum name would pass the totality test and fail a
    trainee, so the *content* is asserted too: Cyrillic, and no bare ASCII identifier."""
    for event_type, template in SUMMARY_TEMPLATES.items():
        assert template.title_ru.strip(), event_type.value
        assert any("Ѐ" <= character <= "ӿ" for character in template.title_ru), (
            f"{event_type.value}: summary_ru must be Russian, got {template.title_ru!r}"
        )


def test_every_detail_key_has_a_russian_label() -> None:
    """The label catalog is shared; a template naming a key nobody labelled would render the raw
    English key name to a trainee."""
    for event_type, template in SUMMARY_TEMPLATES.items():
        for key in template.detail_keys:
            assert key in PAYLOAD_LABELS_RU, f"{event_type.value}: no Russian label for {key!r}"


def test_a_summary_renders_the_details_it_was_given() -> None:
    rendered = summary_ru(
        EventType.CARD_FIELD_CHANGED, {"field_path": "incident.type", "new_value": "FIRE"}
    )
    assert rendered.startswith("Изменено поле карточки — ")
    assert "поле: incident.type" in rendered
    assert "новое значение: FIRE" in rendered


def test_a_summary_omits_a_detail_the_redaction_removed() -> None:
    """Payload values reach the sentence only through the redacted projection: a key that is not
    in the payload this viewer got is simply not mentioned, and the title still renders."""
    assert summary_ru(EventType.CARD_FIELD_CHANGED, {}) == "Изменено поле карточки"
    assert (
        summary_ru(EventType.CARD_FIELD_CHANGED, {"field_path": "incident.type"})
        == "Изменено поле карточки — поле: incident.type"
    )


def test_a_summary_with_no_detail_keys_is_just_the_title() -> None:
    assert summary_ru(EventType.SESSION_COMPLETED, {"total_events": 42}) == "Занятие завершено"


def test_lists_and_booleans_render_readably() -> None:
    rendered = summary_ru(EventType.RESOURCE_DISPATCHED, {"resource_ids": ["a", "b"]})
    assert rendered == "Ресурс направлен — ресурсы: a, b"
    assert summary_ru(EventType.CALLER_TTS_ENDED, {"completed": False}).endswith("завершено: нет")


def test_an_empty_list_detail_is_not_rendered() -> None:
    assert summary_ru(EventType.RESOURCE_DISPATCHED, {"resource_ids": []}) == "Ресурс направлен"


@pytest.mark.parametrize("actor_id", [None, user("op")], ids=["system", "trainee"])
def test_timeline_entry_carries_the_actor_id_from_the_row(actor_id: object) -> None:
    """§40.2's realtime envelope has no `actor_id`; the report shows *who*, so the entry takes it
    from the `session_events` row (SPEC §29 item 4)."""
    envelope = RealtimeEnvelope(
        seq_no=7,
        event_type=EventType.CALL_ANSWERED,
        timestamp_utc=FIXED_TIME,
        monotonic_offset_ms=1234,
        payload={"call_id": "c"},
        actor_type=ActorType.TRAINEE,
    )
    entry = timeline_entry(envelope, actor_id=actor_id)  # type: ignore[arg-type]
    assert entry.seq_no == 7
    assert entry.actor_id == actor_id
    assert entry.monotonic_offset_ms == 1234
    assert entry.summary_ru == "Вызов принят оператором"
    assert entry.payload == {"call_id": "c"}
