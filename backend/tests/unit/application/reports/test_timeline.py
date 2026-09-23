"""The report's timeline projection and its Russian per-event summary (SPEC §29 item 4).

The load-bearing test here is the **totality** one: every `EventType` must have a
`SummaryTemplate`, so the day somebody adds an event type the suite fails until its Russian
sentence exists, rather than a trainee's report quietly showing an English enum name.

I3 E0 (manager decision + addendum): every enum-valued detail renders through a Russian label
(never the raw member), and no bare id fragment (UUID, raw enum value, raw card-field path)
reaches a sentence — `test_role_type_renders_as_russian_label_not_the_enum_member` and the
`_renders_..._not_the_raw_member` tests below are the re-pinned versions of what used to assert
the raw English text.
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
from app.application.reports.timeline_labels_ru import (
    CLOSURE_REASON_LABELS_RU,
    DDS_STAGE_STATE_LABELS_RU,
    HEALTH_STATUS_LABELS_RU,
    OPERATOR_STAGE_STATE_LABELS_RU,
    RESOURCE_STATUS_LABELS_RU,
    ROLE_TYPE_LABELS_RU,
    SERVICE_TYPE_LABELS_RU,
    SESSION_MODE_LABELS_RU,
    STATUS_UPDATE_KIND_LABELS_RU,
)
from app.domain.enums import (
    ActorType,
    ClosureReason,
    DDSStageState,
    HealthStatus,
    Operator112StageState,
    ResourceStatus,
    RoleType,
    ServiceType,
    SessionMode,
    StatusUpdateKind,
)
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


# -- I3 E0: exhaustive enum-value-table coverage --------------------------------------------
# `Mapping[str, str]` gets no compile-time totality check the way the frontend's `Record<Enum,
# ...>` does — these are its runtime equivalent, one per enum `_render_detail_value` can render.


def test_role_type_label_table_covers_every_member() -> None:
    assert {member.value for member in RoleType} == set(ROLE_TYPE_LABELS_RU)


def test_session_mode_label_table_covers_every_member() -> None:
    assert {member.value for member in SessionMode} == set(SESSION_MODE_LABELS_RU)


def test_service_type_label_table_covers_every_member() -> None:
    assert {member.value for member in ServiceType} == set(SERVICE_TYPE_LABELS_RU)


def test_resource_status_label_table_covers_every_member() -> None:
    assert {member.value for member in ResourceStatus} == set(RESOURCE_STATUS_LABELS_RU)


def test_closure_reason_label_table_covers_every_member() -> None:
    assert {member.value for member in ClosureReason} == set(CLOSURE_REASON_LABELS_RU)


def test_status_update_kind_label_table_covers_every_member() -> None:
    assert {member.value for member in StatusUpdateKind} == set(STATUS_UPDATE_KIND_LABELS_RU)


def test_health_status_label_table_covers_every_member() -> None:
    assert {member.value for member in HealthStatus} == set(HEALTH_STATUS_LABELS_RU)


def test_operator_stage_state_label_table_covers_every_member() -> None:
    assert {member.value for member in Operator112StageState} == set(OPERATOR_STAGE_STATE_LABELS_RU)


def test_dds_stage_state_label_table_covers_every_member() -> None:
    assert {member.value for member in DDSStageState} == set(DDS_STAGE_STATE_LABELS_RU)


# -- I3 E0 manager decision: enums render through Russian labels, never str() ----------------


def test_role_type_renders_as_russian_label_not_the_enum_member() -> None:
    """The manager's own acceptance check: an OPERATOR_112 role sentence must say «Оператор 112»
    and must never contain the raw enum member."""
    rendered = summary_ru(EventType.ROLE_STAGE_STARTED, {"role_type": "OPERATOR_112"})
    assert "Оператор 112" in rendered
    assert "OPERATOR_112" not in rendered


def test_service_type_renders_as_russian_label_not_the_raw_member() -> None:
    rendered = summary_ru(EventType.SERVICE_SELECTED, {"service_type": "FIRE_RESCUE"})
    assert "Пожарно-спасательная служба" in rendered
    assert "FIRE_RESCUE" not in rendered


def test_session_mode_renders_as_russian_label() -> None:
    rendered = summary_ru(
        EventType.SESSION_CREATED,
        {"session_mode": "FULL_CYCLE_SINGLE_TRAINEE"},
    )
    assert "Полный цикл (один стажёр)" in rendered
    assert "FULL_CYCLE_SINGLE_TRAINEE" not in rendered


def test_closure_reason_renders_as_russian_label() -> None:
    rendered = summary_ru(EventType.DDS_INCIDENT_CLOSED, {"closure_reason": "FALSE_CALL"})
    assert "Ложный вызов" in rendered
    assert "FALSE_CALL" not in rendered


def test_new_status_dispatches_by_event_type_resource_vs_health() -> None:
    """`new_status` is `ResourceStatus` on one event type and `HealthStatus` on another — the
    same payload key must not be rendered through the wrong table."""
    resource = summary_ru(
        EventType.RESOURCE_STATUS_CHANGED,
        {"previous_status": "DISPATCHED", "new_status": "EN_ROUTE"},
    )
    assert "В пути" in resource
    assert "Направлен" in resource
    assert "EN_ROUTE" not in resource
    assert "DISPATCHED" not in resource

    health = summary_ru(
        EventType.INFERENCE_HEALTH_CHANGED,
        {"component": "llm", "new_status": "READY"},
    )
    assert "Готово" in health
    assert "READY" not in health


def test_stage_state_dispatches_by_role_type_operator_vs_dds() -> None:
    """`STAGE_STATE_CHANGED`'s `new_state` is an `Operator112StageState` or a `DDSStageState`
    depending on the event's own `role_type` — a bare state name like `RECEIVED` is not unique
    across the two machines on its own."""
    operator = summary_ru(
        EventType.STAGE_STATE_CHANGED,
        {"role_type": "OPERATOR_112", "new_state": "INTERVIEW"},
    )
    assert "Опрос" in operator
    assert "INTERVIEW" not in operator

    dds = summary_ru(
        EventType.STAGE_STATE_CHANGED,
        {"role_type": "DDS", "new_state": "RECEIVED"},
    )
    assert "Получено" in dds
    assert "RECEIVED" not in dds


def test_card_field_changed_renders_field_label_and_enum_value() -> None:
    """Re-pinned: this used to assert `"поле: incident.type"` / `"новое значение: FIRE"` — the
    raw leak the manager's addendum flagged."""
    rendered = summary_ru(
        EventType.CARD_FIELD_CHANGED, {"field_path": "incident.type", "new_value": "FIRE"}
    )
    assert rendered.startswith("Изменено поле карточки — ")
    assert "поле: Тип происшествия" in rendered
    assert "новое значение: Пожар" in rendered
    assert "incident.type" not in rendered
    assert "FIRE" not in rendered


def test_card_field_changed_renders_recipients_services_list() -> None:
    rendered = summary_ru(
        EventType.CARD_FIELD_CHANGED,
        {"field_path": "recipients.services", "new_value": ["FIRE_RESCUE", "AMBULANCE"]},
    )
    assert "поле: Службы-получатели" in rendered
    assert "новое значение: Пожарно-спасательная служба, Скорая медицинская помощь" in rendered
    assert "FIRE_RESCUE" not in rendered


def test_card_field_changed_non_enum_field_renders_the_raw_value() -> None:
    """A `STRING`/`INTEGER` field has no enum table — its value renders as-is (never a crash on
    a field this catalog does not turn into a lookup)."""
    rendered = summary_ru(
        EventType.CARD_FIELD_CHANGED,
        {"field_path": "address.street", "new_value": "улица Николаева"},
    )
    assert "поле: Улица" in rendered
    assert "новое значение: улица Николаева" in rendered


def test_card_field_changed_unknown_field_path_falls_back_to_the_raw_path() -> None:
    """A `field_path` the static `CARD_FIELDS` catalog does not know still renders — the raw
    path, never a crash and never a blank label."""
    rendered = summary_ru(
        EventType.CARD_FIELD_CHANGED,
        {"field_path": "not.a.real.field", "new_value": "x"},
    )
    assert "поле: not.a.real.field" in rendered


def test_resource_events_render_callsigns_not_uuids() -> None:
    """`RESOURCE_SELECTED`/`RESOURCE_DESELECTED` carry `callsign`, `RESOURCE_DISPATCHED` carries
    `callsigns` — both already sit next to the resource id in the payload, so the raw id is
    never the thing rendered."""
    assert (
        summary_ru(EventType.RESOURCE_SELECTED, {"callsign": "АЦ-1"})
        == "Выбран ресурс — позывной: АЦ-1"
    )
    assert (
        summary_ru(EventType.RESOURCE_DESELECTED, {"callsign": "АЦ-1"})
        == "Ресурс снят с выбора — позывной: АЦ-1"
    )
    assert (
        summary_ru(EventType.RESOURCE_DISPATCHED, {"callsigns": ["АЦ-1", "АГС-1"]})
        == "Ресурс направлен — позывные: АЦ-1, АГС-1"
    )


def test_session_created_uses_the_scenario_title_not_the_version_id() -> None:
    """The one detail not sourced from `payload` at all — `summary_ru`'s own `scenario_title`
    keyword, passed by the report-assembly call site."""
    rendered = summary_ru(
        EventType.SESSION_CREATED,
        {
            "session_mode": "SINGLE_ROLE",
            "scenario_version_id": "3f6c1a20-0e1a-4b1e-9d2a-0a7c5b2f1d11",
        },
        scenario_title="Пожар в квартире, Смоленск, ул. Николаева, 27",
    )
    assert "сценарий: Пожар в квартире, Смоленск, ул. Николаева, 27" in rendered
    assert "3f6c1a20" not in rendered


def test_session_created_omits_the_scenario_detail_when_no_title_is_given() -> None:
    """No raw id fallback: when the caller has no title to give, the detail is simply absent."""
    rendered = summary_ru(EventType.SESSION_CREATED, {"session_mode": "SINGLE_ROLE"})
    assert rendered == "Занятие создано — режим: Одна роль"


def test_an_unrecognised_enum_member_falls_back_to_the_raw_value_not_a_crash() -> None:
    """SPEC §29: a report that fails to render is worse than one untranslated value."""
    rendered = summary_ru(EventType.SERVICE_SELECTED, {"service_type": "NOT_A_REAL_SERVICE"})
    assert rendered == "Выбрана служба для передачи — служба: NOT_A_REAL_SERVICE"


def test_a_summary_omits_a_detail_the_redaction_removed() -> None:
    """Payload values reach the sentence only through the redacted projection: a key that is not
    in the payload this viewer got is simply not mentioned, and the title still renders."""
    assert summary_ru(EventType.CARD_FIELD_CHANGED, {}) == "Изменено поле карточки"
    assert (
        summary_ru(EventType.CARD_FIELD_CHANGED, {"field_path": "incident.type"})
        == "Изменено поле карточки — поле: Тип происшествия"
    )


def test_a_summary_with_no_detail_keys_is_just_the_title() -> None:
    assert summary_ru(EventType.SESSION_COMPLETED, {"total_events": 42}) == "Занятие завершено"


def test_lists_and_booleans_render_readably() -> None:
    rendered = summary_ru(EventType.RESOURCE_DISPATCHED, {"callsigns": ["a", "b"]})
    assert rendered == "Ресурс направлен — позывные: a, b"
    assert summary_ru(EventType.CALLER_TTS_ENDED, {"completed": False}).endswith("завершено: нет")


def test_an_empty_list_detail_is_not_rendered() -> None:
    assert summary_ru(EventType.RESOURCE_DISPATCHED, {"callsigns": []}) == "Ресурс направлен"


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


def test_timeline_entry_forwards_scenario_title_to_summary_ru() -> None:
    envelope = RealtimeEnvelope(
        seq_no=1,
        event_type=EventType.SESSION_CREATED,
        timestamp_utc=FIXED_TIME,
        monotonic_offset_ms=0,
        payload={"session_mode": "SINGLE_ROLE"},
        actor_type=ActorType.INSTRUCTOR,
    )
    entry = timeline_entry(envelope, actor_id=None, scenario_title="Пожар в квартире")
    assert entry.summary_ru == "Занятие создано — режим: Одна роль; сценарий: Пожар в квартире"
