// Shared fixtures for the DDS console's component tests (not a test file itself — no `.test.` in
// the name, so vitest does not collect it as a suite). Action sets per `DDSStageState` copied
// verbatim from `docs/hld/10-domain-model.md` §10.9's `DDSModule.available_actions` table.
import type { DdsWorkItem, DDSStageState } from '@/entities/work-item';
import type { EmergencyResourceView } from '@/entities/resource';
import type { NotificationView } from '@/entities/notification';
import type { RadioMessageView } from '@/entities/radio';
import type { ActionDescriptor } from '@/shared/api';

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
