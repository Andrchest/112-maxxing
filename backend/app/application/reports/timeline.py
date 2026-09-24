"""`SessionReport.timeline` — the complete event timeline of SPEC §29 item 4, with a Russian
one-line summary per event (`openapi.yaml`'s `TimelineEntryView.summary_ru`).

Pure and table-driven, in the same spirit as `redaction.PAYLOAD_KEY_WHITELIST`: every `EventType`
has a row in `SUMMARY_TEMPLATES` and a totality test asserts that none is missing, so an event
type added to the catalog fails the suite until somebody writes its Russian sentence rather than
silently rendering as an English enum name in a trainee's report.

**Payload values reach the summary only through the redacted projection.** The renderer is handed
the `RealtimeEnvelope` `ReportVisibility.timeline_entry` produced, never the raw row, so a key a
role may not see cannot leak into the sentence that describes the event to them — which would be
exactly the hole D3 closes structurally everywhere else. A detail key that was redacted away (or
that the producer never wrote) is simply omitted from the sentence; the title always renders.

The catalog of payload-key labels is shared rather than repeated per row, because the same keys
(`role_type`, `field_path`, `rule_id`, …) appear in a dozen event types and a per-row label list
would drift between them.

**Enum-valued details render through Russian labels, never `str()` (I3 E0 manager decision).**
`_render_detail_value` dispatches each `detail_keys` entry to `timeline_labels_ru`'s tables —
roles, session modes, service types, resource/health status, closure reasons, status-update
kinds, DDS/Operator112 stage states, and (for `CARD_FIELD_CHANGED`) the card field's own label and
its value's enum label where the field is one. A value this module does not recognise still
renders as its raw string (the same graceful-degradation contract `summary_ru` already had for an
unknown `EventType`) — never a crash.

**No raw id fragments (I3 E0 manager addendum).** A payload key that is only ever a bare UUID with
no human-readable counterpart at hand (`transcript_segment_id`, `snapshot_id`) is not in any
template's `detail_keys` at all, rather than rendered raw. `resource_ids`/`resource_id` are
rendered as the resource's own `callsign`/`callsigns`, already sitting next to the id in the same
payload (`EVENT_PAYLOAD_CATALOG`) — never the id. `SESSION_CREATED`'s `scenario_version_id`
becomes the scenario's own title, passed in from the report-assembly call site (the one place
that already has the loaded `ScenarioVersion`, `assemble_report.compute_report`) as `summary_ru`'s
`scenario_title` keyword — omitted from the sentence entirely when the caller has none to give.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.application.realtime.redaction import RealtimeEnvelope
from app.application.reports.timeline_labels_ru import (
    CLOSURE_REASON_LABELS_RU,
    HEALTH_STATUS_LABELS_RU,
    RESOURCE_STATUS_LABELS_RU,
    ROLE_TYPE_LABELS_RU,
    SERVICE_TYPE_LABELS_RU,
    SESSION_MODE_LABELS_RU,
    STATUS_UPDATE_KIND_LABELS_RU,
    card_field_label_ru,
    card_field_value_label_ru,
    service_type_list_label_ru,
    stage_state_label_ru,
)
from app.domain.dds.card_status import CARD_STATUS_LABELS_RU
from app.domain.dds.response import SERVICE_RESPONSE_LABELS_RU
from app.domain.enums import ActorType
from app.domain.events.types import EventType

__all__ = [
    "PAYLOAD_LABELS_RU",
    "SUMMARY_TEMPLATES",
    "SummaryTemplate",
    "TimelineEntry",
    "summary_ru",
    "timeline_entry",
]

#: Russian labels for the payload keys any summary may render. One catalog, so the same key reads
#: the same way wherever it appears (§10.13's key names are the source of the left-hand side).
PAYLOAD_LABELS_RU: Mapping[str, str] = {
    "at_offset_ms": "время, мс",
    "audience_role": "адресат",
    "call_id": "вызов",
    "caller_display_ru": "абонент",
    "callsign": "позывной",
    "callsigns": "позывные",
    "closure_reason": "причина закрытия",
    "completed": "завершено",
    "component": "компонент",
    "delivered_text": "произнесено",
    "error_kind": "вид ошибки",
    "fact_ids": "факты",
    "field_path": "поле",
    "from_role_type": "из роли",
    "intent": "намерение",
    "issue_kind": "вид ошибки в карточке",
    "new_state": "новое состояние",
    "new_status": "новый статус",
    "new_value": "новое значение",
    "notification_list": "список оповещения",
    "previous_status": "прежний статус",
    "points_awarded": "баллы",
    "reason": "причина",
    "recipient_services": "службы-получатели",
    "role_type": "роль",
    "rule_id": "правило",
    "scenario_title": "сценарий",
    "service_type": "служба",
    "session_mode": "режим",
    "status": "статус",
    "text_ru": "текст",
    "title_ru": "заголовок",
    "to_role": "кому",
    "to_role_type": "в роль",
    "turn_index": "реплика",
    "update_kind": "вид доклада",
    "utterance_ru": "реплика",
    "world_event_id": "событие мира",
}


@dataclass(frozen=True, slots=True)
class SummaryTemplate:
    """One row of `SUMMARY_TEMPLATES`: the Russian sentence, plus the payload keys worth showing.

    `detail_keys` is a *preference*, not a requirement: a key the viewer's redaction removed, or
    that the event did not carry, is skipped. That is what lets one row serve the instructor's
    unredacted reading and a trainee's narrower one without two tables.
    """

    title_ru: str
    detail_keys: tuple[str, ...] = field(default=())


#: Every `EventType` of §10.13, in the enum's own order. `backend/tests/unit/application/reports/`
#: asserts totality: a new event type without a row here fails the suite.
SUMMARY_TEMPLATES: Mapping[EventType, SummaryTemplate] = {
    EventType.SESSION_CREATED: SummaryTemplate(
        "Занятие создано", ("session_mode", "scenario_title")
    ),
    EventType.SESSION_STARTED: SummaryTemplate("Занятие начато"),
    EventType.ROLE_STAGE_STARTED: SummaryTemplate("Начат этап роли", ("role_type",)),
    EventType.CALL_RINGING: SummaryTemplate("Входящий вызов", ("caller_display_ru",)),
    EventType.CALL_ANSWERED: SummaryTemplate("Вызов принят оператором"),
    EventType.USER_SPEECH_STARTED: SummaryTemplate("Оператор начал говорить", ("turn_index",)),
    EventType.USER_SPEECH_ENDED: SummaryTemplate("Оператор закончил реплику", ("turn_index",)),
    EventType.ASR_PARTIAL: SummaryTemplate("Промежуточное распознавание речи", ("turn_index",)),
    EventType.ASR_FINAL: SummaryTemplate("Речь оператора распознана", ("turn_index",)),
    EventType.CALLER_RESPONSE_PLANNED: SummaryTemplate(
        "Ответ абонента спланирован", ("turn_index", "fact_ids")
    ),
    EventType.CALLER_RESPONSE_GENERATED: SummaryTemplate(
        "Ответ абонента сформулирован", ("turn_index", "utterance_ru")
    ),
    EventType.CALLER_TTS_STARTED: SummaryTemplate("Абонент начал говорить", ("turn_index",)),
    EventType.CALLER_TTS_ENDED: SummaryTemplate(
        "Абонент закончил реплику", ("turn_index", "completed")
    ),
    EventType.CALLER_UTTERANCE_INTERRUPTED: SummaryTemplate(
        "Реплика абонента прервана оператором", ("turn_index", "delivered_text")
    ),
    EventType.CARD_FIELD_CHANGED: SummaryTemplate(
        "Изменено поле карточки", ("field_path", "new_value")
    ),
    EventType.SERVICE_SELECTED: SummaryTemplate("Выбрана служба для передачи", ("service_type",)),
    EventType.HANDOFF_CREATED: SummaryTemplate("Карточка передана в ДДС", ("recipient_services",)),
    EventType.HANDOFF_RECEIVED: SummaryTemplate("Задание получено ДДС", ("service_type",)),
    EventType.DDS_ACKNOWLEDGED: SummaryTemplate("ДДС принял задание в работу", ("service_type",)),
    EventType.RESOURCE_SELECTED: SummaryTemplate("Выбран ресурс", ("callsign",)),
    EventType.RESOURCE_DISPATCHED: SummaryTemplate("Ресурс направлен", ("callsigns",)),
    EventType.RESOURCE_STATUS_CHANGED: SummaryTemplate(
        "Изменён статус ресурса", ("previous_status", "new_status")
    ),
    EventType.WORLD_EVENT_TRIGGERED: SummaryTemplate(
        "Сработало событие обстановки", ("world_event_id",)
    ),
    EventType.ROLE_STAGE_COMPLETED: SummaryTemplate("Этап роли завершён", ("role_type",)),
    EventType.SCORING_RULE_EVALUATED: SummaryTemplate(
        "Оценено правило", ("rule_id", "points_awarded")
    ),
    EventType.SESSION_COMPLETED: SummaryTemplate("Занятие завершено"),
    EventType.MODEL_FALLBACK_USED: SummaryTemplate(
        "Использована резервная модель", ("component", "reason")
    ),
    EventType.MODEL_ERROR: SummaryTemplate("Ошибка модели", ("component", "error_kind")),
    EventType.SESSION_ABORTED: SummaryTemplate("Занятие прервано", ("reason",)),
    EventType.STAGE_STATE_CHANGED: SummaryTemplate(
        "Изменилось состояние этапа", ("role_type", "new_state")
    ),
    EventType.ROLE_TRANSITION_STARTED: SummaryTemplate(
        "Начат переход между ролями", ("from_role_type", "to_role_type")
    ),
    EventType.ROLE_TRANSITION_COMPLETED: SummaryTemplate(
        "Переход между ролями завершён", ("to_role_type",)
    ),
    EventType.SERVICE_DESELECTED: SummaryTemplate("Служба снята с передачи", ("service_type",)),
    EventType.RESOURCE_DESELECTED: SummaryTemplate("Ресурс снят с выбора", ("callsign",)),
    EventType.DDS_STATUS_UPDATE_SENT: SummaryTemplate(
        "Доклад ДДС отправлен", ("update_kind", "text_ru")
    ),
    EventType.DDS_INCIDENT_CLOSED: SummaryTemplate("Происшествие закрыто ДДС", ("closure_reason",)),
    EventType.NOTIFICATION_CREATED: SummaryTemplate(
        "Создано уведомление", ("audience_role", "title_ru")
    ),
    EventType.NOTIFICATION_ACKNOWLEDGED: SummaryTemplate(
        "Уведомление подтверждено", ("audience_role",)
    ),
    EventType.RADIO_MESSAGE_CREATED: SummaryTemplate("Радиосообщение", ("to_role", "text_ru")),
    EventType.WORLD_TRUTH_MUTATED: SummaryTemplate(
        "Изменена реальная обстановка", ("world_event_id",)
    ),
    EventType.CALLER_BELIEF_MUTATED: SummaryTemplate(
        "Изменились представления абонента", ("world_event_id",)
    ),
    EventType.CALLER_EMOTION_CHANGED: SummaryTemplate("Изменилось состояние абонента", ("reason",)),
    EventType.CALL_ENDED: SummaryTemplate("Вызов завершён", ("reason",)),
    EventType.DIALOGUE_INTERPRETED: SummaryTemplate(
        "Реплика оператора разобрана", ("turn_index", "intent")
    ),
    EventType.FACT_GATE_EVALUATED: SummaryTemplate(
        "Проверен доступ к фактам", ("turn_index", "fact_ids")
    ),
    EventType.FACTS_DELIVERED: SummaryTemplate("Факты сообщены абонентом", ("fact_ids",)),
    EventType.TRANSPORT_DISCONNECTED: SummaryTemplate("Потеряна голосовая связь", ("reason",)),
    EventType.TRANSPORT_RECONNECTED: SummaryTemplate("Голосовая связь восстановлена"),
    EventType.INFERENCE_HEALTH_CHANGED: SummaryTemplate(
        "Изменилась готовность моделей", ("component", "new_status")
    ),
    EventType.DDS_CARD_STATUS_CHANGED: SummaryTemplate(
        "Изменился статус карточки", ("new_status",)
    ),
    EventType.RECIPIENTS_RESOLVED: SummaryTemplate(
        "Определён список оповещения", ("notification_list",)
    ),
    EventType.DDS_CARD_OPENED: SummaryTemplate("ДДС открыла карточку", ("service_type",)),
    EventType.DDS_SERVICE_STATUS_SET: SummaryTemplate(
        "Статус службы изменён", ("service_type", "new_status")
    ),
    EventType.DDS_CARD_ISSUE_FLAGGED: SummaryTemplate(
        "ДДС отметила ошибку в карточке", ("issue_kind", "field_path")
    ),
}


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """`openapi.yaml`'s `TimelineEntryView` as application data."""

    seq_no: int
    event_type: EventType
    monotonic_offset_ms: int
    timestamp_utc: datetime
    actor_type: ActorType
    actor_id: UUID | None
    summary_ru: str
    payload: Mapping[str, Any]


def summary_ru(
    event_type: EventType,
    payload: Mapping[str, Any],
    *,
    scenario_title: str | None = None,
) -> str:
    """The Russian one-line summary of one event, from the redacted payload only.

    An event type with no row is a bug the totality test catches; at runtime it degrades to the
    enum name rather than raising, because a report that fails to render is worse than a report
    with one untranslated line (SPEC §29 asks for the timeline, not for a crash).

    `scenario_title` is the one detail that does not live in the payload at all (§40.2's realtime
    envelope only ever carries `scenario_version_id`, a raw id with no Russian counterpart of its
    own) — the caller passes the scenario's own title when it has one at hand
    (`assemble_report.compute_report`, which already loaded the `ScenarioVersion`); `SESSION_
    CREATED`'s synthetic `"scenario_title"` detail key reads it from here, never from `payload`,
    and is simply omitted when the caller has none to give (never a raw id fallback).
    """
    template = SUMMARY_TEMPLATES.get(event_type)
    if template is None:  # pragma: no cover - the totality test forbids this
        return event_type.value
    details: list[str] = []
    for key in template.detail_keys:
        if key == "scenario_title":
            if scenario_title:
                details.append(f"{PAYLOAD_LABELS_RU.get(key, key)}: {scenario_title}")
            continue
        if key not in payload or payload[key] is None or payload[key] == []:
            continue
        rendered_value = _render_detail_value(event_type, key, payload[key], payload)
        details.append(f"{PAYLOAD_LABELS_RU.get(key, key)}: {rendered_value}")
    return template.title_ru if not details else f"{template.title_ru} — {'; '.join(details)}"


def timeline_entry(
    envelope: RealtimeEnvelope,
    *,
    actor_id: UUID | None,
    scenario_title: str | None = None,
) -> TimelineEntry:
    """One redacted envelope as a `TimelineEntryView`.

    `actor_id` comes from the `session_events` row rather than the envelope: §40.2's realtime
    frame carries `actor_type` only, and the report shows *who*, which is one of the things a
    post-session review is for (SPEC §29 item 4). `scenario_title` is forwarded to `summary_ru`
    unchanged — see its own docstring.
    """
    return TimelineEntry(
        seq_no=envelope.seq_no,
        event_type=envelope.event_type,
        monotonic_offset_ms=envelope.monotonic_offset_ms,
        timestamp_utc=envelope.timestamp_utc,
        actor_type=envelope.actor_type,
        actor_id=actor_id,
        summary_ru=summary_ru(envelope.event_type, envelope.payload, scenario_title=scenario_title),
        payload=dict(envelope.payload),
    )


#: Payload keys whose Russian rendering does not depend on which event type carries them (every
#: other enum-valued key needs the event type too — `new_value`/`field_path` need `CARD_FIELD_
#: CHANGED`'s own `field_path`, `new_state` needs `STAGE_STATE_CHANGED`'s own `role_type`, and
#: `new_status` is `ResourceStatus` on one event type and `HealthStatus` on another).
_SIMPLE_KEY_TABLES: Mapping[str, Mapping[str, str]] = {
    "role_type": ROLE_TYPE_LABELS_RU,
    "from_role_type": ROLE_TYPE_LABELS_RU,
    "to_role_type": ROLE_TYPE_LABELS_RU,
    "to_role": ROLE_TYPE_LABELS_RU,
    "audience_role": ROLE_TYPE_LABELS_RU,
    "service_type": SERVICE_TYPE_LABELS_RU,
    "session_mode": SESSION_MODE_LABELS_RU,
    "previous_status": RESOURCE_STATUS_LABELS_RU,  # only RESOURCE_STATUS_CHANGED carries this key
    "closure_reason": CLOSURE_REASON_LABELS_RU,
    "update_kind": STATUS_UPDATE_KIND_LABELS_RU,
}


#: `DDS_CARD_STATUS_CHANGED.new_status` (I3 E4a) — the memo's card-status labels (HLD 70 §70.4.6).
_CARD_STATUS_LABELS_RU: Mapping[str, str] = {
    status.value: label for status, label in CARD_STATUS_LABELS_RU.items()
}

#: `DDS_SERVICE_STATUS_SET.new_status` (I3 E5a) — the memo's per-service labels (HLD 70 §70.4.1).
_RESPONSE_STATUS_LABELS_RU: Mapping[str, str] = {
    status.value: label for status, label in SERVICE_RESPONSE_LABELS_RU.items()
}


def _render_detail_value(
    event_type: EventType, key: str, value: object, payload: Mapping[str, Any]
) -> str:
    """One `detail_keys` value, through a Russian label where `timeline_labels_ru` has one for
    it — the raw value (via `_render`) otherwise, never a crash on an unrecognised member."""
    if event_type is EventType.CARD_FIELD_CHANGED:
        if key == "field_path":
            return card_field_label_ru(str(value))
        if key == "new_value":
            field_path = payload.get("field_path")
            if field_path is not None:
                return card_field_value_label_ru(str(field_path), value)
    if key in ("recipient_services", "notification_list"):
        return service_type_list_label_ru(value)
    if key == "new_state" and event_type is EventType.STAGE_STATE_CHANGED:
        return stage_state_label_ru(str(payload.get("role_type", "")), str(value))
    if key == "new_status":
        status_table: Mapping[str, str] = RESOURCE_STATUS_LABELS_RU
        if event_type is EventType.INFERENCE_HEALTH_CHANGED:
            status_table = HEALTH_STATUS_LABELS_RU
        elif event_type is EventType.DDS_CARD_STATUS_CHANGED:
            status_table = _CARD_STATUS_LABELS_RU
        elif event_type is EventType.DDS_SERVICE_STATUS_SET:
            status_table = _RESPONSE_STATUS_LABELS_RU
        return status_table.get(str(value), _render(value))
    simple_table = _SIMPLE_KEY_TABLES.get(key)
    if simple_table is not None:
        return simple_table.get(str(value), _render(value))
    return _render(value)


def _render(value: object) -> str:
    """A payload value as one short human string; lists are joined, never repr'd."""
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, (list, tuple)):
        return ", ".join(_render(item) for item in value)
    return str(value)
