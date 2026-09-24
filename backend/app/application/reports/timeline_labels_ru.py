"""Russian labels for the enum-valued payload keys `timeline.py`'s `summary_ru()` renders (I3 E0
manager decision, and its addendum on UUID/raw-path leaks).

**Register.** These match `frontend/src/shared/i18n/ru.ts`'s own trainee-facing UI wording
*exactly* (the manager's explicit requirement) — e.g. `IncidentType.FIRE` -> "Пожар". This is a
different register from `app.domain.facts.value_labels_ru.ENUM_VALUE_LABELS_RU`, which gives the
simulated *caller's own spoken* wording for the same enums ("пожар", lower-case, "what the caller
would say") for a different surface (`render_value_ru`, the dialogue prompt/validator). The two
must not be merged: one is a report's Russian UI label, the other is speech the caller utters.

**Fallback.** Every lookup here degrades to the raw value on an unrecognised member — same
contract `summary_ru()` already had for a missing `SummaryTemplate` row: a report that renders one
untranslated value is better than one that crashes (SPEC §29).

**Card field values.** `card_field_value_label_ru` is the report-timeline analogue of what every
frontend feature already keeps locally for `CardFieldSpec`/`FactValue`
(`features/report/format-fact-value.ts` et al.) — routed here through the domain's own
`CARD_FIELDS` catalog (`app.domain.layers.operator_card`) instead of a second hand-copied table,
since the backend already has that catalog and the frontend does not.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.enums import (
    CallerRelationship,
    ClosureReason,
    DDSStageState,
    HealthStatus,
    IncidentType,
    Operator112StageState,
    ResourceStatus,
    RoleType,
    SessionMode,
    StatusUpdateKind,
)
from app.domain.layers.operator_card import CARD_FIELDS

__all__ = [
    "CALLER_RELATIONSHIP_LABELS_RU",
    "CLOSURE_REASON_LABELS_RU",
    "DDS_STAGE_STATE_LABELS_RU",
    "HEALTH_STATUS_LABELS_RU",
    "INCIDENT_TYPE_LABELS_RU",
    "OPERATOR_STAGE_STATE_LABELS_RU",
    "RESOURCE_STATUS_LABELS_RU",
    "ROLE_TYPE_LABELS_RU",
    "SERVICE_TYPE_LABELS_RU",
    "SESSION_MODE_LABELS_RU",
    "STATUS_UPDATE_KIND_LABELS_RU",
    "card_field_label_ru",
    "card_field_value_label_ru",
    "service_type_list_label_ru",
    "stage_state_label_ru",
]

#: Matches `ru.ts`'s `roleTypeOperator112`/`roleTypeDds`/`roleTypeEdds`.
ROLE_TYPE_LABELS_RU: Mapping[str, str] = {
    RoleType.OPERATOR_112.value: "Оператор 112",
    RoleType.DDS.value: "ДДС",
    RoleType.EDDS.value: "РЕДДС",
}

#: Matches `ru.ts`'s `instructorSessionMode*`.
SESSION_MODE_LABELS_RU: Mapping[str, str] = {
    SessionMode.SINGLE_ROLE.value: "Одна роль",
    SessionMode.FULL_CYCLE_SINGLE_TRAINEE.value: "Полный цикл (один стажёр)",
    SessionMode.MULTI_TRAINEE.value: "Несколько стажёров",
    SessionMode.ASSESSMENT.value: "Аттестация",
}

#: The six legacy service ids (`LEGACY_SERVICE_IDS`); matches `ru.ts`'s `serviceType*` and the
#: `name_ru` of their `reference/services/v1.yaml` entries. Any other catalog id is shown raw.
SERVICE_TYPE_LABELS_RU: Mapping[str, str] = {
    "FIRE_RESCUE": "Пожарно-спасательная служба",
    "POLICE": "Полиция",
    "AMBULANCE": "Скорая медицинская помощь",
    "GAS_SERVICE": "Газовая служба",
    "UTILITY_EMERGENCY": "Аварийная коммунальная служба",
    "EDDS": "РЕДДС",
}

#: Matches `ru.ts`'s `resourceStatus*`.
RESOURCE_STATUS_LABELS_RU: Mapping[str, str] = {
    ResourceStatus.AVAILABLE.value: "Свободен",
    ResourceStatus.SELECTED.value: "Выбран",
    ResourceStatus.DISPATCHED.value: "Направлен",
    ResourceStatus.EN_ROUTE.value: "В пути",
    ResourceStatus.ON_SCENE.value: "На месте",
    ResourceStatus.WORKING.value: "Работает",
    ResourceStatus.RETURNING.value: "Возвращается",
    ResourceStatus.OUT_OF_SERVICE.value: "Небоеспособен",
    ResourceStatus.UNAVAILABLE.value: "Недоступен",
}

#: Matches `ru.ts`'s `closureReason*`.
CLOSURE_REASON_LABELS_RU: Mapping[str, str] = {
    ClosureReason.RESOLVED.value: "Урегулировано",
    ClosureReason.FALSE_CALL.value: "Ложный вызов",
    ClosureReason.TRANSFERRED.value: "Передано другой службе",
    ClosureReason.CANCELLED_BY_CALLER.value: "Отменено заявителем",
}

#: Matches `ru.ts`'s `statusUpdateKind*`.
STATUS_UPDATE_KIND_LABELS_RU: Mapping[str, str] = {
    StatusUpdateKind.ACKNOWLEDGEMENT.value: "Подтверждение",
    StatusUpdateKind.EN_ROUTE_REPORT.value: "Выехали",
    StatusUpdateKind.ON_SCENE_REPORT.value: "Прибыли на место",
    StatusUpdateKind.SITUATION_UPDATE.value: "Обстановка",
    StatusUpdateKind.ADDITIONAL_FORCES_REQUESTED.value: "Запрос дополнительных сил",
    StatusUpdateKind.RESOLUTION_REPORT.value: "Происшествие урегулировано",
}

#: Matches `ru.ts`'s `readiness*` (`INFERENCE_HEALTH_CHANGED`'s `new_status`, a `HealthStatus` —
#: a different domain from `ResourceStatus`, which also has a `new_status`-named payload key on a
#: different event type; `_render_detail_value` in `timeline.py` dispatches by `event_type`).
HEALTH_STATUS_LABELS_RU: Mapping[str, str] = {
    HealthStatus.READY.value: "Готово",
    HealthStatus.WARMING.value: "Прогрев",
    HealthStatus.NOT_READY.value: "Не готово",
    HealthStatus.FATAL.value: "Ошибка",
}

#: Matches `ru.ts`'s `incidentType*` (the UI register — not the caller-spoken one).
INCIDENT_TYPE_LABELS_RU: Mapping[str, str] = {
    IncidentType.FIRE.value: "Пожар",
    IncidentType.MEDICAL.value: "Медицинский случай",
    IncidentType.CRIME.value: "Преступление",
    IncidentType.TRAFFIC_ACCIDENT.value: "ДТП",
    IncidentType.GAS_LEAK.value: "Утечка газа",
    IncidentType.UTILITY_FAILURE.value: "Коммунальная авария",
    IncidentType.RESCUE.value: "Спасательные работы",
    IncidentType.OTHER.value: "Иное",
}

#: Matches `ru.ts`'s `callerRelationship*` (the UI register).
CALLER_RELATIONSHIP_LABELS_RU: Mapping[str, str] = {
    CallerRelationship.VICTIM.value: "Пострадавший",
    CallerRelationship.WITNESS.value: "Свидетель",
    CallerRelationship.NEIGHBOUR.value: "Сосед",
    CallerRelationship.RELATIVE.value: "Родственник",
    CallerRelationship.PASSERBY.value: "Прохожий",
    CallerRelationship.OFFICIAL.value: "Должностное лицо",
    CallerRelationship.UNKNOWN.value: "Не указано",
}

#: Matches `ru.ts`'s `stageState*` (the Operator112 stage badge labels).
OPERATOR_STAGE_STATE_LABELS_RU: Mapping[str, str] = {
    Operator112StageState.WAITING_FOR_CALL.value: "Ожидание вызова",
    Operator112StageState.RINGING.value: "Звонит",
    Operator112StageState.CONNECTED.value: "На связи",
    Operator112StageState.INTERVIEW.value: "Опрос",
    Operator112StageState.HANDOFF_PREPARATION.value: "Подготовка передачи",
    Operator112StageState.HANDED_OFF.value: "Передано",
    Operator112StageState.STAGE_COMPLETED.value: "Этап завершён",
}

#: Matches `ru.ts`'s `ddsStage*`.
DDS_STAGE_STATE_LABELS_RU: Mapping[str, str] = {
    DDSStageState.RECEIVED.value: "Получено",
    DDSStageState.ACKNOWLEDGED.value: "Принято к исполнению",
    DDSStageState.RESOURCE_SELECTION.value: "Подбор сил и средств",
    DDSStageState.DISPATCHED.value: "Силы направлены",
    DDSStageState.EN_ROUTE.value: "Силы в пути",
    DDSStageState.ARRIVED.value: "Силы на месте",
    DDSStageState.WORKING.value: "Работы проводятся",
    DDSStageState.RESOLVED.value: "Происшествие урегулировано",
    DDSStageState.CLOSED.value: "Закрыто",
}


def stage_state_label_ru(role_type: str, state: str) -> str:
    """`StageState` (`Operator112StageState | DDSStageState`), labelled by the stage's own
    `role_type` — the same dispatch `frontend/features/instructor/instructor-labels.ts`'s
    `stageStateLabelRu` uses, since a bare state name (e.g. `RECEIVED`) is not unique across the
    two state machines on its own."""
    table = (
        DDS_STAGE_STATE_LABELS_RU
        if role_type == RoleType.DDS.value
        else OPERATOR_STAGE_STATE_LABELS_RU
    )
    return table.get(state, state)


def service_type_list_label_ru(values: object) -> str:
    """A `list[ServiceId]` payload value (`recipient_services`), each item labelled, joined."""
    if not isinstance(values, (list, tuple)):
        return str(values)
    return ", ".join(SERVICE_TYPE_LABELS_RU.get(str(item), str(item)) for item in values)


_CARD_FIELD_LABEL_BY_PATH: Mapping[str, str] = {
    spec.field_path: spec.label_ru for spec in CARD_FIELDS
}
_CARD_FIELD_ENUM_NAME_BY_PATH: Mapping[str, str | None] = {
    spec.field_path: spec.enum_name for spec in CARD_FIELDS
}
_ENUM_VALUE_TABLES_BY_NAME: Mapping[str, Mapping[str, str]] = {
    "IncidentType": INCIDENT_TYPE_LABELS_RU,
    "CallerRelationship": CALLER_RELATIONSHIP_LABELS_RU,
}


def card_field_label_ru(field_path: str) -> str:
    """`CARD_FIELDS[...].label_ru` for one `field_path` — the raw path itself for a field this
    static catalog does not (yet) know, never a blank label."""
    return _CARD_FIELD_LABEL_BY_PATH.get(field_path, field_path)


def card_field_value_label_ru(field_path: str, value: object) -> str:
    """One `CARD_FIELD_CHANGED` `new_value`/`previous_value`, labelled the way `CARD_FIELDS`
    says that field's values should read: `recipients.services` (a `STRING_LIST` of
    `ServiceId`) per item, an `ENUM` field through its own enum's table, a boolean as да/нет, a
    plain list joined, anything else as its own string."""
    if isinstance(value, bool):
        return "да" if value else "нет"
    if field_path == "recipients.services":
        return service_type_list_label_ru(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    enum_name = _CARD_FIELD_ENUM_NAME_BY_PATH.get(field_path)
    if enum_name:
        table = _ENUM_VALUE_TABLES_BY_NAME.get(enum_name)
        if table is not None:
            return table.get(str(value), str(value))
    return str(value)
