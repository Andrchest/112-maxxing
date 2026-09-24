import { afterEach, describe, expect, it } from 'vitest';
import { useWorkItemStore, hasAvailableAction, type DdsWorkItem, type DdsStageView, type SessionSnapshot } from './work-item-store';

function makeWorkItem(overrides: Partial<DdsWorkItem> = {}): DdsWorkItem {
  return {
    assignment_id: 'assign-1',
    incident_id: 'inc-1',
    role_stage_id: 'stage-dds-1',
    snapshot_id: 'snap-1',
    service_type: 'FIRE_RESCUE',
    state: 'RECEIVED',
    card_values: {},
    recipient_services: ['FIRE_RESCUE'],
    handoff_content_sha256: 'sha',
    received_at_offset_ms: 1000,
    acknowledged_at_offset_ms: null,
    dispatched_at_offset_ms: null,
    closed_at_offset_ms: null,
    closure_reason: null,
    selected_resource_ids: [],
    dispatched_resource_ids: [],
    missing_field_paths: [],
    ...overrides,
  };
}

describe('useWorkItemStore', () => {
  afterEach(() => {
    useWorkItemStore.getState().reset();
  });

  it('setFromStageView replaces work_item/available_actions/last_seq_no wholesale', () => {
    const view: DdsStageView = {
      role_stage_id: 'stage-dds-1',
      stage_state: 'RECEIVED',
      available_actions: [{ action_id: 'acknowledge', label_ru: 'Принять к исполнению', permission: 'ACKNOWLEDGE_ASSIGNMENT', trigger: 'acknowledge' }],
      work_item: makeWorkItem(),
      resources: [],
      unacknowledged_notification_count: 0,
      session_state: 'ACTIVE',
      last_seq_no: 42,
    };
    useWorkItemStore.getState().setFromStageView(view);
    const state = useWorkItemStore.getState();
    expect(state.workItem?.assignment_id).toBe('assign-1');
    expect(state.availableActions).toHaveLength(1);
    expect(state.lastSeqNo).toBe(42);
    expect(state.sessionState).toBe('ACTIVE');
  });

  it('setFromSnapshot hydrates from the refresh-restore payload', () => {
    const snapshot: SessionSnapshot = {
      session: {
        id: 'sess-1',
        scenario_version_id: 'v1',
        scenario_slug: 'apartment-fire',
        scenario_version: 1,
        session_mode: 'SINGLE_ROLE',
        state: 'ACTIVE',
        session_seed: 'seed',
        time_scale: 1,
        incident_id: 'inc-1',
        role_chain: ['DDS'],
        stages: [],
        active_role_stage_id: 'stage-dds-1',
        participants: [],
        created_by_user_id: 'instr-1',
        created_at: '2026-09-21T00:00:00Z',
        started_at: '2026-09-21T00:00:00Z',
        completed_at: null,
        abort_reason: null,
        monotonic_offset_ms: 1000,
        last_seq_no: 7,
        transition_pause_seconds: 0,
        transition_continue_available_at_offset_ms: null,
        variants: {
          card_source: 'GENERATED_CARD',
          dds_mode: 'RESOURCE_PICKER',
          dds_card_check: 'OFF',
          dds_brigade_call: 'OFF',
        },
        scenario_role_chain: ['DDS'],
        lesson_id: null,
        lesson_position: null,
      },
      my_role_type: 'DDS',
      active_role_stage_id: 'stage-dds-1',
      active_role_type: 'DDS',
      stage_state: 'RECEIVED',
      available_actions: [{ action_id: 'acknowledge', label_ru: 'Принять к исполнению', permission: 'ACKNOWLEDGE_ASSIGNMENT', trigger: 'acknowledge' }],
      card: null,
      work_item: makeWorkItem(),
      call_state: { call_id: null, room_name: null, phase: 'NO_CALL', caller_display_ru: null, started_at_offset_ms: null, answered_at_offset_ms: null, ended_at_offset_ms: null, duration_ms: null, caller_speaking: false },
      last_seq_no: 7,
      visible_sources: ['HANDOFF_SNAPSHOT', 'DDS_ASSIGNMENT'],
      server_time_utc: '2026-09-21T10:00:00Z',
    };

    useWorkItemStore.getState().setFromSnapshot(snapshot);
    const state = useWorkItemStore.getState();
    expect(state.roleStageId).toBe('stage-dds-1');
    expect(state.workItem?.assignment_id).toBe('assign-1');
    expect(state.sessionState).toBe('ACTIVE');
    expect(state.lastSeqNo).toBe(7);
  });
});

describe('hasAvailableAction', () => {
  it('is true only when action_id is present', () => {
    const actions = [{ action_id: 'acknowledge', label_ru: 'x', permission: 'ACKNOWLEDGE_ASSIGNMENT' as const, trigger: 'acknowledge' }];
    expect(hasAvailableAction(actions, 'acknowledge')).toBe(true);
    expect(hasAvailableAction(actions, 'dispatch')).toBe(false);
  });
});
