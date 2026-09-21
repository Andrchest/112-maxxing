// Shared fixtures for the operator console's component tests (not a test file itself — no
// `.test.` in the name, so vitest does not collect it as a suite).
import type { CardFieldSpec, OperatorCardView } from '@/entities/card';
import type { CallStateView } from '@/entities/session';
import type { ActionDescriptor } from '@/entities/stage';

export const CARD_FIELD_SPECS: CardFieldSpec[] = [
  { field_path: 'incident.type', value_type: 'ENUM', enum_name: 'IncidentType', label_ru: 'incident.type', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'address.locality', value_type: 'STRING', enum_name: null, label_ru: 'address.locality', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'address.street', value_type: 'STRING', enum_name: null, label_ru: 'address.street', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'address.house', value_type: 'STRING', enum_name: null, label_ru: 'address.house', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'address.floor', value_type: 'INTEGER', enum_name: null, label_ru: 'address.floor', scoring_relevant: true, required_for_handoff: false },
  { field_path: 'caller.phone', value_type: 'STRING', enum_name: null, label_ru: 'caller.phone', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'caller.relationship', value_type: 'ENUM', enum_name: 'CallerRelationship', label_ru: 'caller.relationship', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'people.children_present', value_type: 'BOOLEAN', enum_name: null, label_ru: 'people.children_present', scoring_relevant: true, required_for_handoff: false },
  { field_path: 'description.text', value_type: 'STRING', enum_name: null, label_ru: 'description.text', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'flags.threat_to_life', value_type: 'BOOLEAN', enum_name: null, label_ru: 'flags.threat_to_life', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'recipients.services', value_type: 'STRING_LIST', enum_name: null, label_ru: 'recipients.services', scoring_relevant: true, required_for_handoff: true },
];

export function makeCard(overrides: Partial<OperatorCardView> = {}): OperatorCardView {
  return {
    card_id: 'card-1',
    incident_id: 'inc-1',
    values: {},
    revision_counter: 0,
    field_specs: CARD_FIELD_SPECS,
    ...overrides,
  };
}

export function makeCallState(overrides: Partial<CallStateView> = {}): CallStateView {
  return {
    call_id: null,
    room_name: null,
    phase: 'NO_CALL',
    caller_display_ru: null,
    started_at_offset_ms: null,
    answered_at_offset_ms: null,
    ended_at_offset_ms: null,
    duration_ms: null,
    caller_speaking: false,
    ...overrides,
  };
}

export const ACTIONS_BY_STAGE_STATE: Record<string, ActionDescriptor[]> = {
  WAITING_FOR_CALL: [],
  RINGING: [{ action_id: 'answer', label_ru: 'Answer', permission: 'ANSWER_CALL', trigger: 'answer' }],
  CONNECTED: [{ action_id: 'end_call', label_ru: 'End call', permission: 'END_CALL', trigger: null }],
  INTERVIEW: [
    { action_id: 'edit_card', label_ru: 'Edit card', permission: 'EDIT_CARD', trigger: null },
    { action_id: 'select_services', label_ru: 'Select services', permission: 'SELECT_SERVICES', trigger: null },
    { action_id: 'end_call', label_ru: 'End call', permission: 'END_CALL', trigger: null },
    { action_id: 'open_handoff_preparation', label_ru: 'Prepare handoff', permission: 'EDIT_CARD', trigger: 'open_handoff_preparation' },
  ],
  HANDOFF_PREPARATION: [
    { action_id: 'edit_card', label_ru: 'Edit card', permission: 'EDIT_CARD', trigger: null },
    { action_id: 'select_services', label_ru: 'Select services', permission: 'SELECT_SERVICES', trigger: null },
    { action_id: 'back_to_interview', label_ru: 'Back to interview', permission: 'EDIT_CARD', trigger: 'back_to_interview' },
    { action_id: 'create_handoff', label_ru: 'Create handoff', permission: 'CREATE_HANDOFF', trigger: 'create_handoff' },
  ],
  HANDED_OFF: [
    { action_id: 'complete_stage', label_ru: 'Complete stage', permission: 'EDIT_CARD', trigger: 'complete_stage' },
  ],
  STAGE_COMPLETED: [],
};
