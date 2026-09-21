import { afterEach, describe, expect, it } from 'vitest';
import { useResourceStore, type EmergencyResourceView } from './resource-store';

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

describe('useResourceStore', () => {
  afterEach(() => {
    useResourceStore.getState().reset();
  });

  it('setResources replaces the board wholesale', () => {
    useResourceStore.getState().setResources([makeResource()]);
    expect(useResourceStore.getState().resources).toHaveLength(1);
    useResourceStore.getState().setResources([]);
    expect(useResourceStore.getState().resources).toHaveLength(0);
  });

  it('reset clears the board', () => {
    useResourceStore.getState().setResources([makeResource()]);
    useResourceStore.getState().reset();
    expect(useResourceStore.getState().resources).toEqual([]);
  });
});
