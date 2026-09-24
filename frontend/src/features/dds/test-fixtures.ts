// Shared fixtures for the DDS console's component tests (not a test file itself — no `.test.` in
// the name, so vitest does not collect it as a suite). Action sets per `DDSStageState` copied
// verbatim from `docs/hld/10-domain-model.md` §10.9's `DDSModule.available_actions` table.
import type { DdsWorkItem, DDSStageState } from '@/entities/work-item';
import type { EmergencyResourceView } from '@/entities/resource';
import type { NotificationView } from '@/entities/notification';
import type { RadioMessageView } from '@/entities/radio';
import type { ActionDescriptor, CardFieldSpec, DdsLegView, ServiceStatusEntryView } from '@/shared/api';

// A v1 `field_specs` slice matching `makeWorkItem`'s default `card_values` (+ `caller.phone`, its
// default `missing_field_paths` entry) — `WorkItemPanel` renders from `field_specs` only since I3
// E3c, so a work item fixture needs one, the same shape `getDdsWorkItem` sends (I3 E3a′, §70.5.4).
export const WORK_ITEM_FIELD_SPECS: CardFieldSpec[] = [
  { field_path: 'incident.type', value_type: 'ENUM', enum_name: 'IncidentType', label_ru: 'Тип происшествия', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'address.locality', value_type: 'STRING', enum_name: null, label_ru: 'Населённый пункт', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'address.street', value_type: 'STRING', enum_name: null, label_ru: 'Улица', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'address.house', value_type: 'STRING', enum_name: null, label_ru: 'Дом', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'address.floor', value_type: 'INTEGER', enum_name: null, label_ru: 'Этаж', scoring_relevant: true, required_for_handoff: false },
  { field_path: 'description.text', value_type: 'STRING', enum_name: null, label_ru: 'Описание происшествия', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'flags.threat_to_life', value_type: 'BOOLEAN', enum_name: null, label_ru: 'Угроза жизни', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'recipients.services', value_type: 'STRING_LIST', enum_name: null, label_ru: 'Службы-получатели', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'caller.phone', value_type: 'STRING', enum_name: null, label_ru: 'Телефон заявителя', scoring_relevant: true, required_for_handoff: true },
];

/** One `field_specs` entry by `field_path`, from {@link WORK_ITEM_FIELD_SPECS} — lets `.tsx` tests
 * build expected label text from server-controlled data instead of a literal Cyrillic string
 * (`no-cyrillic-guard.test.ts` scans `.tsx` sources, not this `.ts` fixture file). */
export function workItemFieldSpec(fieldPath: string): CardFieldSpec {
  const spec = WORK_ITEM_FIELD_SPECS.find((candidate) => candidate.field_path === fieldPath);
  if (!spec) throw new Error(`no fixture field_spec for ${fieldPath}`);
  return spec;
}

// A `visible_when` fixture for the "hidden fields are omitted" test — `flags.threat_to_life` only
// shows when `address.house` reads `27`.
export const THREAT_TO_LIFE_HIDDEN_FIELD_SPEC: CardFieldSpec = {
  ...workItemFieldSpec('flags.threat_to_life'),
  visible_when: { field_path: 'address.house', op: 'EQ', value: '27' },
};

// A v2 `STRING_LIST` fixture (the «Что случилось» chips, §70.5.3) for the "option code renders as
// label_ru" test. `options[0].label_ru` is the schema's real bare numeral (`reference/card-schema/
// v2.yaml`: `{code: '1', label_ru: '101'}`) — I3 E7a carry-over fix (b) overrides it to the
// reference's own wording («Происшествие 101»), so this fixture deliberately keeps the raw '101'
// label to exercise that override rather than mask it behind a friendlier fixture label.
export const INCIDENT_TYPES_CHIP_FIELD_SPEC: CardFieldSpec = {
  field_path: 'incident.types',
  value_type: 'STRING_LIST',
  enum_name: null,
  label_ru: 'Что случилось',
  scoring_relevant: false,
  required_for_handoff: false,
  group: 'incident',
  options: [{ code: '1', label_ru: '101' }],
};

// I3 E7a carry-over fix (b): `incident.classifier_code` («Класс.:», `reference/card-schema/
// v2.yaml`, group `incident`) for the "renders the classifier value when present" test.
export const CLASSIFIER_CODE_FIELD_SPEC: CardFieldSpec = {
  field_path: 'incident.classifier_code',
  value_type: 'STRING',
  enum_name: null,
  label_ru: 'Класс.',
  scoring_relevant: true,
  required_for_handoff: false,
  group: 'incident',
};

// I3 E7a (manager review): a `q_fire`-grouped field (`reference/card-schema/v2.yaml`'s
// `q.fire.where`) for the "dark bar renders values only, titled by the selected incident type"
// test — `label_ru` deliberately differs from any option's own label, so a test can tell whether
// the rendered text is the field's label (must NOT appear under the bar) or its value.
export const Q_FIRE_WHERE_FIELD_SPEC: CardFieldSpec = {
  field_path: 'q.fire.where',
  value_type: 'STRING_LIST',
  enum_name: null,
  label_ru: 'Где',
  scoring_relevant: true,
  required_for_handoff: false,
  group: 'q_fire',
  options: [{ code: 'на улице', label_ru: 'Улица' }],
};

export function makeWorkItem(overrides: Partial<DdsWorkItem> = {}): DdsWorkItem {
  return {
    assignment_id: 'assign-1',
    incident_id: 'inc-1',
    role_stage_id: 'stage-dds-1',
    snapshot_id: 'snap-1',
    service_type: 'FIRE_RESCUE',
    state: 'RECEIVED',
    card_values: {
      'incident.type': 'FIRE',
      'address.locality': 'Smolensk',
      'address.street': 'Nikolaeva St',
      'address.house': '72',
      'address.floor': 5,
      'description.text': 'Fire in the apartment',
      'flags.threat_to_life': true,
      'recipients.services': ['FIRE_RESCUE', 'AMBULANCE'],
    },
    recipient_services: ['FIRE_RESCUE', 'AMBULANCE'],
    handoff_content_sha256: 'sha-1',
    received_at_offset_ms: 1000,
    acknowledged_at_offset_ms: null,
    dispatched_at_offset_ms: null,
    closed_at_offset_ms: null,
    closure_reason: null,
    selected_resource_ids: [],
    dispatched_resource_ids: [],
    missing_field_paths: ['caller.phone'],
    card_schema: 'v1',
    field_specs: WORK_ITEM_FIELD_SPECS,
    ...overrides,
  };
}

export function makeResource(overrides: Partial<EmergencyResourceView> = {}): EmergencyResourceView {
  return {
    resource_id: 'res-ac1',
    service_type: 'FIRE_RESCUE',
    resource_type: 'FIRE_ENGINE',
    callsign: 'AC-1',
    name_ru: 'Engine 1',
    capabilities: ['FIRE_SUPPRESSION'],
    current_status: 'AVAILABLE',
    available_from_ms: 0,
    available_until_ms: null,
    eta: { turnout_delay_seconds: 60, travel_time_seconds: 300, setup_seconds: 60, on_scene_work_seconds: 600, return_time_seconds: 300 },
    home_station_ru: 'Station 1',
    crew_size: 4,
    selectable: true,
    ...overrides,
  };
}

export function makeNotification(overrides: Partial<NotificationView> = {}): NotificationView {
  return {
    notification_id: 'notif-1',
    incident_id: 'inc-1',
    audience_role: 'DDS',
    severity: 'WARNING',
    title_ru: 'Fire spreading',
    body_ru: 'Fire moved to the next room.',
    created_at_offset_ms: 1000,
    acknowledged_at_offset_ms: null,
    ...overrides,
  };
}

// -- I3 E5c: the memo's per-leg blocks (`legs-panel.tsx`, `service-leg-block.tsx`) --------------
export function makeStatusEntry(overrides: Partial<ServiceStatusEntryView> = {}): ServiceStatusEntryView {
  return {
    event_id: 'entry-1',
    previous_status: 'ADDED',
    new_status: 'RECEIVED',
    order_number: null,
    comment_ru: null,
    completion_reason: null,
    source: 'SYSTEM',
    actor_user_id: null,
    actor_display_ru: 'Система',
    at_offset_ms: 1000,
    ...overrides,
  };
}

export function makeLeg(overrides: Partial<DdsLegView> = {}): DdsLegView {
  return {
    assignment_id: 'assign-1',
    service_type: 'FIRE_RESCUE',
    service_name_ru: 'Пожарно-спасательная служба',
    response_status: 'RECEIVED',
    response_status_at_offset_ms: 1000,
    order_number: null,
    last_comment_ru: null,
    accept_missed: false,
    responder: 'TRAINEE',
    bound_user_id: null,
    is_mine: true,
    history: [makeStatusEntry()],
    available_actions: [
      { action_id: 'accept', label_ru: 'Принята', permission: 'SET_SERVICE_STATUS', trigger: 'accept' },
      { action_id: 'decline', label_ru: 'Не принята', permission: 'SET_SERVICE_STATUS', trigger: 'decline' },
    ],
    ...overrides,
  };
}

export function makeRadioMessage(overrides: Partial<RadioMessageView> = {}): RadioMessageView {
  return {
    radio_message_id: 'radio-1',
    seq_no: 1,
    incident_id: 'inc-1',
    from_callsign: 'AC-2',
    to_role: 'DDS',
    text_ru: 'En route to the address.',
    resource_id: 'res-ac2',
    created_at_offset_ms: 1000,
    ...overrides,
  };
}

// `label_ru` values here are deliberately English placeholders, not real Russian, mirroring
// `features/operator/test-fixtures.ts`'s own `ACTIONS_BY_STAGE_STATE` — a fixture's `label_ru` is
// server-controlled wire data the component renders verbatim, not a string this frontend owns, so
// its exact text is irrelevant to what these tests check; keeping it non-Cyrillic here is what
// keeps this fixture importable from `.tsx` test files without tripping
// `src/app/no-cyrillic-guard.test.ts` (which scans hard-coded Cyrillic literals, not runtime data).
export const ACTIONS_BY_DDS_STAGE_STATE: Record<DDSStageState, ActionDescriptor[]> = {
  RECEIVED: [{ action_id: 'acknowledge', label_ru: 'Acknowledge', permission: 'ACKNOWLEDGE_ASSIGNMENT', trigger: 'acknowledge' }],
  ACKNOWLEDGED: [
    { action_id: 'open_resource_selection', label_ru: 'Open resource selection', permission: 'SELECT_RESOURCES', trigger: 'open_resource_selection' },
    { action_id: 'send_status_update', label_ru: 'Send status update', permission: 'SEND_STATUS_UPDATE', trigger: null },
  ],
  RESOURCE_SELECTION: [
    { action_id: 'select_resource', label_ru: 'Select', permission: 'SELECT_RESOURCES', trigger: 'select' },
    { action_id: 'deselect_resource', label_ru: 'Deselect', permission: 'SELECT_RESOURCES', trigger: 'deselect' },
    { action_id: 'dispatch', label_ru: 'Dispatch', permission: 'DISPATCH_RESOURCES', trigger: 'dispatch' },
    { action_id: 'back_to_acknowledged', label_ru: 'Back', permission: 'SELECT_RESOURCES', trigger: 'back_to_acknowledged' },
    { action_id: 'send_status_update', label_ru: 'Send status update', permission: 'SEND_STATUS_UPDATE', trigger: null },
  ],
  DISPATCHED: [
    { action_id: 'open_resource_selection', label_ru: 'Add more forces', permission: 'SELECT_RESOURCES', trigger: 'open_resource_selection' },
    { action_id: 'send_status_update', label_ru: 'Send status update', permission: 'SEND_STATUS_UPDATE', trigger: null },
  ],
  EN_ROUTE: [
    { action_id: 'select_resource', label_ru: 'Select', permission: 'SELECT_RESOURCES', trigger: 'select' },
    { action_id: 'deselect_resource', label_ru: 'Deselect', permission: 'SELECT_RESOURCES', trigger: 'deselect' },
    { action_id: 'dispatch_additional', label_ru: 'Dispatch additional', permission: 'DISPATCH_RESOURCES', trigger: 'dispatch_additional' },
    { action_id: 'send_status_update', label_ru: 'Send status update', permission: 'SEND_STATUS_UPDATE', trigger: null },
  ],
  ARRIVED: [
    { action_id: 'select_resource', label_ru: 'Select', permission: 'SELECT_RESOURCES', trigger: 'select' },
    { action_id: 'deselect_resource', label_ru: 'Deselect', permission: 'SELECT_RESOURCES', trigger: 'deselect' },
    { action_id: 'dispatch_additional', label_ru: 'Dispatch additional', permission: 'DISPATCH_RESOURCES', trigger: 'dispatch_additional' },
    { action_id: 'send_status_update', label_ru: 'Send status update', permission: 'SEND_STATUS_UPDATE', trigger: null },
  ],
  WORKING: [
    { action_id: 'select_resource', label_ru: 'Select', permission: 'SELECT_RESOURCES', trigger: 'select' },
    { action_id: 'deselect_resource', label_ru: 'Deselect', permission: 'SELECT_RESOURCES', trigger: 'deselect' },
    { action_id: 'dispatch_additional', label_ru: 'Dispatch additional', permission: 'DISPATCH_RESOURCES', trigger: 'dispatch_additional' },
    { action_id: 'send_status_update', label_ru: 'Send status update', permission: 'SEND_STATUS_UPDATE', trigger: null },
  ],
  RESOLVED: [
    { action_id: 'close', label_ru: 'Close incident', permission: 'CLOSE_INCIDENT', trigger: 'close' },
    { action_id: 'send_status_update', label_ru: 'Send status update', permission: 'SEND_STATUS_UPDATE', trigger: null },
  ],
  CLOSED: [],
};
