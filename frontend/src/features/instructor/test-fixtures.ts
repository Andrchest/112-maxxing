// Shared fixtures for `features/instructor`'s co-located tests, mirroring `features/report/test-
// fixtures.ts` / `features/dds/test-fixtures.ts`. Every factory returns a minimal-but-valid
// instance of a generated schema type, overridable per test.
import type {
  CallStateView,
  DdsWorkItem,
  EmergencyResourceView,
  GateDecisionView,
  GateTurnView,
  HandoffSnapshotView,
  HealthReadyResponse,
  InstructorSessionOverview,
  OperatorCardView,
  RoleStageView,
  SessionDetail,
  WorldTruthView,
  CallerBeliefView,
} from '@/shared/api';

export function makeSessionDetail(overrides: Partial<SessionDetail> = {}): SessionDetail {
  return {
    id: 'session-1',
    scenario_version_id: 'scenario-version-1',
    scenario_slug: 'apartment-fire',
    scenario_version: 1,
    session_mode: 'FULL_CYCLE_SINGLE_TRAINEE',
    state: 'ACTIVE',
    session_seed: 'seed',
    time_scale: 1,
    incident_id: 'incident-1',
    role_chain: ['OPERATOR_112', 'DDS'],
    stages: [],
    active_role_stage_id: 'stage-1',
    participants: [],
    created_by_user_id: 'instructor-1',
    created_at: '2026-09-21T00:00:00Z',
    started_at: '2026-09-21T00:00:01Z',
    completed_at: null,
    abort_reason: null,
    monotonic_offset_ms: 60000,
    last_seq_no: 12,
    transition_pause_seconds: 20,
    transition_continue_available_at_offset_ms: null,
    variants: {
      card_source: 'CALLER_VOICE',
      dds_mode: 'RESOURCE_PICKER',
      dds_card_check: 'OFF',
      dds_brigade_call: 'OFF',
    },
    scenario_role_chain: ['OPERATOR_112', 'DDS'],
    lesson_id: null,
    lesson_position: null,
    ...overrides,
  };
}

export function makeRoleStageView(overrides: Partial<RoleStageView> = {}): RoleStageView {
  return {
    role_stage_id: 'stage-1',
    role_type: 'OPERATOR_112',
    order_index: 0,
    state: 'INTERVIEW',
    participant_user_id: 'trainee-1',
    started_at_offset_ms: 0,
    completed_at_offset_ms: null,
    ...overrides,
  };
}

export function makeWorldTruthView(overrides: Partial<WorldTruthView> = {}): WorldTruthView {
  return {
    incident_id: 'incident-1',
    revision: 1,
    facts: { 'address.house': '27' },
    value_types: { 'address.house': 'STRING' },
    label_ru: { 'address.house': 'Дом' },
    ...overrides,
  };
}

export function makeCallerBeliefView(overrides: Partial<CallerBeliefView> = {}): CallerBeliefView {
  return {
    incident_id: 'incident-1',
    revision: 1,
    facts: { 'address.house': '72' },
    knowledge: { 'address.house': 'INCORRECT_BELIEF' },
    certainty: { 'address.house': 0.8 },
    emotion: 'WORRIED',
    stress_level: 0.6,
    revealed_fact_ids: ['address.house'],
    label_ru: { 'address.house': 'Дом' },
    ...overrides,
  };
}

export function makeGateDecision(overrides: Partial<GateDecisionView> = {}): GateDecisionView {
  return {
    fact_id: 'address.house',
    outcome: 'ALLOWED',
    reason: 'OK',
    ...overrides,
  };
}

export function makeGateTurn(overrides: Partial<GateTurnView> = {}): GateTurnView {
  return {
    turn_index: 0,
    at_offset_ms: 1000,
    decisions: [makeGateDecision()],
    allowed_fact_ids: ['address.house'],
    spontaneous_attached: [],
    withheld_count: 0,
    ...overrides,
  };
}

export function makeOperatorCardView(overrides: Partial<OperatorCardView> = {}): OperatorCardView {
  return {
    card_id: 'card-1',
    incident_id: 'incident-1',
    values: { 'address.house': '72' },
    revision_counter: 1,
    field_specs: [
      { field_path: 'address.house', value_type: 'STRING', enum_name: null, label_ru: 'Дом', scoring_relevant: true, required_for_handoff: true },
    ],
    ...overrides,
  };
}

export function makeHandoffSnapshot(overrides: Partial<HandoffSnapshotView> = {}): HandoffSnapshotView {
  return {
    snapshot_id: 'snapshot-1',
    incident_id: 'incident-1',
    card_id: 'card-1',
    card_revision_id: 'revision-1',
    card_values: { 'address.house': '72' },
    recipient_services: ['FIRE_RESCUE'],
    created_by_user_id: 'trainee-1',
    created_at_offset_ms: 5000,
    content_sha256: 'sha-abc',
    ...overrides,
  };
}

export function makeDdsWorkItem(overrides: Partial<DdsWorkItem> = {}): DdsWorkItem {
  return {
    assignment_id: 'assignment-1',
    incident_id: 'incident-1',
    role_stage_id: 'stage-2',
    snapshot_id: 'snapshot-1',
    service_type: 'FIRE_RESCUE',
    state: 'ACKNOWLEDGED',
    card_values: { 'address.house': '72' },
    recipient_services: ['FIRE_RESCUE'],
    handoff_content_sha256: 'sha-abc',
    received_at_offset_ms: 5000,
    acknowledged_at_offset_ms: 5500,
    dispatched_at_offset_ms: null,
    closed_at_offset_ms: null,
    closure_reason: null,
    selected_resource_ids: [],
    dispatched_resource_ids: [],
    missing_field_paths: [],
    ...overrides,
  };
}

export function makeEmergencyResource(overrides: Partial<EmergencyResourceView> = {}): EmergencyResourceView {
  return {
    resource_id: 'resource-1',
    service_type: 'FIRE_RESCUE',
    resource_type: 'FIRE_ENGINE',
    callsign: 'А-101',
    name_ru: 'Автоцистерна №1',
    capabilities: ['FIRE_SUPPRESSION'],
    current_status: 'AVAILABLE',
    available_from_ms: 0,
    available_until_ms: null,
    eta: {
      turnout_delay_seconds: 60,
      travel_time_seconds: 300,
      setup_seconds: 60,
      on_scene_work_seconds: 600,
      return_time_seconds: 300,
    },
    home_station_ru: 'Часть №1',
    crew_size: 4,
    selectable: true,
    ...overrides,
  };
}

export function makeCallStateView(overrides: Partial<CallStateView> = {}): CallStateView {
  return {
    call_id: 'call-1',
    room_name: 'room-1',
    phase: 'CONNECTED',
    caller_display_ru: 'Заявитель',
    started_at_offset_ms: 0,
    answered_at_offset_ms: 500,
    ended_at_offset_ms: null,
    duration_ms: null,
    caller_speaking: false,
    ...overrides,
  };
}

export function makeHealthReadyResponse(overrides: Partial<HealthReadyResponse> = {}): HealthReadyResponse {
  return {
    overall: 'READY',
    components: [],
    required_components: ['asr', 'llm', 'tts'],
    require_inference_ready: true,
    model_profile: 'DEV_3060TI',
    ...overrides,
  };
}

export function makeInstructorSessionOverview(overrides: Partial<InstructorSessionOverview> = {}): InstructorSessionOverview {
  return {
    session: makeSessionDetail(),
    stages: [makeRoleStageView(), makeRoleStageView({ role_stage_id: 'stage-2', role_type: 'DDS', order_index: 1, state: 'RECEIVED', participant_user_id: null, started_at_offset_ms: null })],
    world_truth: makeWorldTruthView(),
    caller_belief: makeCallerBeliefView(),
    gate_turns: [makeGateTurn()],
    card: makeOperatorCardView(),
    handoff: makeHandoffSnapshot(),
    assignments: [makeDdsWorkItem()],
    resources: [makeEmergencyResource()],
    call_state: makeCallStateView(),
    last_seq_no: 12,
    inference_health: makeHealthReadyResponse(),
    ...overrides,
  };
}
