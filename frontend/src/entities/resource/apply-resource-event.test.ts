import { describe, expect, it } from 'vitest';
import { applyResourceEvent } from './apply-resource-event';
import type { EmergencyResourceView } from './resource-store';
import type { components } from '@/shared/api';

type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];

function makeResource(overrides: Partial<EmergencyResourceView> = {}): EmergencyResourceView {
  return {
    resource_id: 'res-1',
    service_type: 'FIRE_RESCUE',
    resource_type: 'FIRE_ENGINE',
    callsign: 'АЦ-1',
    name_ru: 'Автоцистерна 1',
    capabilities: ['FIRE_SUPPRESSION'],
    current_status: 'AVAILABLE',
    available_from_ms: 0,
    available_until_ms: null,
    eta: { turnout_delay_seconds: 60, travel_time_seconds: 300, setup_seconds: 60, on_scene_work_seconds: 600, return_time_seconds: 300 },
    home_station_ru: 'ПЧ-1',
    crew_size: 4,
    selectable: true,
    ...overrides,
  };
}

function makeEvent(overrides: Partial<SessionEventEnvelope> = {}): SessionEventEnvelope {
  return {
    seq_no: 5,
    event_type: 'RESOURCE_STATUS_CHANGED',
    timestamp_utc: '2026-09-21T10:00:00Z',
    monotonic_offset_ms: 1000,
    payload: { resource_id: 'res-1', callsign: 'АЦ-1', previous_status: 'AVAILABLE', new_status: 'SELECTED', trigger: 'select', assignment_id: 'assign-1', source_world_event_id: null, at_offset_ms: 1000 },
    ...overrides,
  };
}

describe('applyResourceEvent', () => {
  it('patches current_status from RESOURCE_STATUS_CHANGED, leaving everything else untouched', () => {
    const previous = [makeResource()];
    const next = applyResourceEvent(previous, makeEvent());
    expect(next[0]?.current_status).toBe('SELECTED');
    expect(next[0]?.callsign).toBe('АЦ-1');
    expect(next).not.toBe(previous);
  });

  it('handles a breakdown to OUT_OF_SERVICE the same way as any other transition', () => {
    const previous = [makeResource({ current_status: 'EN_ROUTE' })];
    const next = applyResourceEvent(
      previous,
      makeEvent({ payload: { resource_id: 'res-1', callsign: 'АЦ-1', previous_status: 'EN_ROUTE', new_status: 'OUT_OF_SERVICE', trigger: 'breakdown', assignment_id: null, source_world_event_id: 'ac2_breakdown', at_offset_ms: 5000 } }),
    );
    expect(next[0]?.current_status).toBe('OUT_OF_SERVICE');
  });

  it('is idempotent: applying the same event twice yields the same result', () => {
    const previous = [makeResource()];
    const once = applyResourceEvent(previous, makeEvent());
    const twice = applyResourceEvent(once, makeEvent());
    expect(twice).toEqual(once);
  });

  it('is a no-op for an unrelated resource_id', () => {
    const previous = [makeResource({ resource_id: 'other' })];
    const next = applyResourceEvent(previous, makeEvent());
    expect(next).toBe(previous);
  });

  it('ignores event types that are not RESOURCE_STATUS_CHANGED (e.g. RESOURCE_SELECTED)', () => {
    const previous = [makeResource()];
    const next = applyResourceEvent(
      previous,
      makeEvent({ event_type: 'RESOURCE_SELECTED', payload: { assignment_id: 'assign-1', resource_id: 'res-1', callsign: 'АЦ-1', service_type: 'FIRE_RESCUE', resource_type: 'FIRE_ENGINE', capabilities: ['FIRE_SUPPRESSION'], at_offset_ms: 1000 } }),
    );
    expect(next).toBe(previous);
  });
});
