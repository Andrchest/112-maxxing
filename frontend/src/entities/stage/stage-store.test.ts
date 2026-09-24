import { afterEach, describe, expect, it } from 'vitest';
import { useStageStore, hasAvailableAction, type OperatorStageView, type SessionSnapshot } from './stage-store';

function makeStageView(overrides: Partial<OperatorStageView> = {}): OperatorStageView {
  return {
    role_stage_id: 'stage-1',
    stage_state: 'INTERVIEW',
    available_actions: [{ action_id: 'edit_card', label_ru: 'test', permission: 'EDIT_CARD', trigger: null }],
    card: { card_id: 'card-1', incident_id: 'inc-1', values: {}, revision_counter: 0, field_specs: [] },
    call_state: {
      call_id: null,
      room_name: null,
      phase: 'NO_CALL',
      caller_display_ru: null,
      started_at_offset_ms: null,
      answered_at_offset_ms: null,
      ended_at_offset_ms: null,
      duration_ms: null,
      caller_speaking: false,
    },
    session_state: 'ACTIVE',
    last_seq_no: 42,
    ...overrides,
  };
}

describe('useStageStore', () => {
  afterEach(() => {
    useStageStore.getState().reset();
  });

  it('setFromStageView replaces stage_state, available_actions and last_seq_no wholesale', () => {
    useStageStore.getState().setFromStageView(makeStageView());
    const state = useStageStore.getState();
    expect(state.stageState).toBe('INTERVIEW');
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
        role_chain: ['OPERATOR_112'],
        stages: [],
        active_role_stage_id: 'stage-1',
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
          card_source: 'CALLER_VOICE',
          dds_mode: 'RESOURCE_PICKER',
          dds_card_check: 'OFF',
          dds_brigade_call: 'OFF',
        },
        scenario_role_chain: ['OPERATOR_112'],
      },
      my_role_type: 'OPERATOR_112',
      active_role_stage_id: 'stage-1',
      active_role_type: 'OPERATOR_112',
      stage_state: 'RINGING',
      available_actions: [{ action_id: 'answer', label_ru: 'Ответить', permission: 'ANSWER_CALL', trigger: 'answer' }],
      card: { card_id: 'card-1', incident_id: 'inc-1', values: {}, revision_counter: 0, field_specs: [] },
      work_item: null,
      call_state: {
        call_id: 'call-1',
        room_name: 'room-1',
        phase: 'RINGING',
        caller_display_ru: 'Абонент',
        started_at_offset_ms: 100,
        answered_at_offset_ms: null,
        ended_at_offset_ms: null,
        duration_ms: null,
        caller_speaking: false,
      },
      last_seq_no: 7,
      visible_sources: ['OPERATOR_CARD', 'CALL_STATE'],
      server_time_utc: '2026-09-21T10:00:00Z',
    };

    useStageStore.getState().setFromSnapshot(snapshot);
    const state = useStageStore.getState();
    expect(state.stageState).toBe('RINGING');
    expect(state.roleStageId).toBe('stage-1');
    expect(state.sessionState).toBe('ACTIVE');
    expect(state.lastSeqNo).toBe(7);
  });
});

describe('hasAvailableAction', () => {
  it('is true only when action_id is present', () => {
    const actions = [{ action_id: 'answer', label_ru: 'x', permission: 'ANSWER_CALL' as const, trigger: 'answer' }];
    expect(hasAvailableAction(actions, 'answer')).toBe(true);
    expect(hasAvailableAction(actions, 'edit_card')).toBe(false);
  });
});
