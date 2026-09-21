import { describe, expect, it } from 'vitest';
import { applyWorkItemEvent } from './apply-work-item-event';
import type { DdsWorkItem } from './work-item-store';
import type { components } from '@/shared/api';

type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];

function makeWorkItem(overrides: Partial<DdsWorkItem> = {}): DdsWorkItem {
  return {
    assignment_id: 'assign-1',
    incident_id: 'inc-1',
    role_stage_id: 'stage-dds-1',
    snapshot_id: 'snap-1',
    service_type: 'FIRE_RESCUE',
    state: 'ACKNOWLEDGED',
    card_values: { 'address.house': '27' },
    recipient_services: ['FIRE_RESCUE', 'AMBULANCE'],
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

function makeEvent(overrides: Partial<SessionEventEnvelope> = {}): SessionEventEnvelope {
  return {
    seq_no: 5,
    event_type: 'DDS_ACKNOWLEDGED',
    timestamp_utc: '2026-09-21T10:00:00Z',
    monotonic_offset_ms: 1000,
    payload: {},
    ...overrides,
  };
}

describe('applyWorkItemEvent', () => {
  it('returns null unchanged when there is no work item yet', () => {
    expect(applyWorkItemEvent(null, makeEvent())).toBeNull();
  });

  it('DDS_ACKNOWLEDGED patches acknowledged_at_offset_ms for the matching assignment', () => {
    const previous = makeWorkItem();
    const next = applyWorkItemEvent(previous, makeEvent({ payload: { assignment_id: 'assign-1', at_offset_ms: 2500 } }));
    expect(next?.acknowledged_at_offset_ms).toBe(2500);
  });

  it('ignores an event for a different assignment_id', () => {
    const previous = makeWorkItem();
    const next = applyWorkItemEvent(previous, makeEvent({ payload: { assignment_id: 'other', at_offset_ms: 2500 } }));
    expect(next).toBe(previous);
  });

  it('RESOURCE_SELECTED adds to selected_resource_ids, deduped', () => {
    const previous = makeWorkItem({ selected_resource_ids: ['res-1'] });
    const next = applyWorkItemEvent(
      previous,
      makeEvent({ event_type: 'RESOURCE_SELECTED', payload: { assignment_id: 'assign-1', resource_id: 'res-1', callsign: 'АЦ-1', service_type: 'FIRE_RESCUE', resource_type: 'FIRE_ENGINE', capabilities: [], at_offset_ms: 1000 } }),
    );
    expect(next?.selected_resource_ids).toEqual(['res-1']);

    const next2 = applyWorkItemEvent(
      next,
      makeEvent({ event_type: 'RESOURCE_SELECTED', payload: { assignment_id: 'assign-1', resource_id: 'res-2', callsign: 'АЦ-2', service_type: 'FIRE_RESCUE', resource_type: 'FIRE_ENGINE', capabilities: [], at_offset_ms: 1000 } }),
    );
    expect(next2?.selected_resource_ids.sort()).toEqual(['res-1', 'res-2']);
  });

  it('RESOURCE_DESELECTED removes from selected_resource_ids', () => {
    const previous = makeWorkItem({ selected_resource_ids: ['res-1', 'res-2'] });
    const next = applyWorkItemEvent(
      previous,
      makeEvent({ event_type: 'RESOURCE_DESELECTED', payload: { assignment_id: 'assign-1', resource_id: 'res-1', callsign: 'АЦ-1', at_offset_ms: 1000 } }),
    );
    expect(next?.selected_resource_ids).toEqual(['res-2']);
  });

  it('RESOURCE_DISPATCHED moves resource_ids from selected to dispatched and sets dispatched_at_offset_ms once', () => {
    const previous = makeWorkItem({ selected_resource_ids: ['res-1', 'res-2'], dispatched_resource_ids: [] });
    const next = applyWorkItemEvent(
      previous,
      makeEvent({ event_type: 'RESOURCE_DISPATCHED', payload: { assignment_id: 'assign-1', resource_ids: ['res-1'], callsigns: ['АЦ-1'], capabilities_union: [], eta_seconds_by_resource: { 'res-1': 660 }, at_offset_ms: 3000, is_additional: false } }),
    );
    expect(next?.selected_resource_ids).toEqual(['res-2']);
    expect(next?.dispatched_resource_ids).toEqual(['res-1']);
    expect(next?.dispatched_at_offset_ms).toBe(3000);

    // a second dispatch (dispatch_additional) must not overwrite the first dispatched_at_offset_ms
    const next2 = applyWorkItemEvent(
      next,
      makeEvent({ event_type: 'RESOURCE_DISPATCHED', payload: { assignment_id: 'assign-1', resource_ids: ['res-2'], callsigns: ['АЦ-2'], capabilities_union: [], eta_seconds_by_resource: { 'res-2': 660 }, at_offset_ms: 9000, is_additional: true } }),
    );
    expect(next2?.dispatched_resource_ids.sort()).toEqual(['res-1', 'res-2']);
    expect(next2?.dispatched_at_offset_ms).toBe(3000);
  });

  it('DDS_INCIDENT_CLOSED patches closed_at_offset_ms and closure_reason', () => {
    const previous = makeWorkItem({ state: 'RESOLVED' });
    const next = applyWorkItemEvent(
      previous,
      makeEvent({ event_type: 'DDS_INCIDENT_CLOSED', payload: { assignment_id: 'assign-1', closure_reason: 'RESOLVED', released_resource_ids: [], at_offset_ms: 20000, actor_user_id: 'u1' } }),
    );
    expect(next?.closed_at_offset_ms).toBe(20000);
    expect(next?.closure_reason).toBe('RESOLVED');
  });

  it('STAGE_STATE_CHANGED patches state only for the matching DDS role_stage_id', () => {
    const previous = makeWorkItem({ state: 'ACKNOWLEDGED' });
    const next = applyWorkItemEvent(
      previous,
      makeEvent({ event_type: 'STAGE_STATE_CHANGED', payload: { role_stage_id: 'stage-dds-1', role_type: 'DDS', previous_state: 'ACKNOWLEDGED', new_state: 'RESOURCE_SELECTION', trigger: 'open_resource_selection', fired_by_actor_type: 'TRAINEE', fired_by_user_id: 'u1', at_offset_ms: 1500 } }),
    );
    expect(next?.state).toBe('RESOURCE_SELECTION');

    const unrelated = applyWorkItemEvent(
      previous,
      makeEvent({ event_type: 'STAGE_STATE_CHANGED', payload: { role_stage_id: 'stage-operator-1', role_type: 'OPERATOR_112', previous_state: 'INTERVIEW', new_state: 'HANDOFF_PREPARATION', trigger: 'open_handoff_preparation', fired_by_actor_type: 'TRAINEE', fired_by_user_id: 'u1', at_offset_ms: 1500 } }),
    );
    expect(unrelated).toBe(previous);
  });

  it('HANDOFF_RECEIVED is a documented pass-through — the page re-fetches instead', () => {
    const previous = makeWorkItem();
    const next = applyWorkItemEvent(previous, makeEvent({ event_type: 'HANDOFF_RECEIVED', payload: { snapshot_id: 'snap-2', assignment_id: 'assign-2', role_stage_id: 'stage-dds-1', service_type: 'AMBULANCE', at_offset_ms: 1000 } }));
    expect(next).toBe(previous);
  });
});
