// Test fixture: one `DdsCallView` as the server sends it (I3 E6b), overridable per test.
import type { DdsCallView } from './dds-call-store';

export function makeDdsCall(overrides: Partial<DdsCallView> = {}): DdsCallView {
  return {
    call_id: 'call-1',
    session_id: 'sess-1',
    kind: 'CLAIMANT',
    direction: 'OUTBOUND',
    assignment_id: null,
    service_type: null,
    dialed: '79161234567',
    endpoint: 'BROWSER',
    room_name: 'dds-sess-1-call-1',
    persona_id: null,
    persona_title_ru: null,
    actor_user_id: 'user-1',
    state: 'RINGING',
    answered_by: null,
    started_at_offset_ms: 1000,
    answered_at_offset_ms: null,
    ended_at_offset_ms: null,
    end_reason: null,
    available_actions: [{ action_id: 'hang_up', label_ru: 'Hang up', permission: 'PLACE_DDS_CALL', trigger: 'hang_up' }],
    ...overrides,
  };
}
