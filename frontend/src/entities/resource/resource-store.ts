// Entity: the DDS resource board (SPEC §11; D3, D12). Fed ONLY by server data — every DDS
// command's `DdsStageView.resources`, `listDdsResources`, and the `RESOURCE_STATUS_CHANGED`
// WS event fold in `apply-resource-event.ts`. `selectable` is the backend's own hint (openapi.yaml
// `EmergencyResourceView.selectable`); this store never recomputes it (D12 design decision #1).
import { create } from 'zustand';
import type { components } from '@/shared/api';

export type EmergencyResourceView = components['schemas']['EmergencyResourceView'];
export type ResourceStatus = components['schemas']['ResourceStatus'];
export type ResourceType = components['schemas']['ResourceType'];
export type ResourceCapability = components['schemas']['ResourceCapability'];
export type EtaProfileView = components['schemas']['EtaProfileView'];

interface ResourceStoreState {
  resources: EmergencyResourceView[];
  /** Replaces the board wholesale with the server's latest list (D12 design decision #1) — every
   * `listDdsResources` call and every `DdsStageView.resources` from a command response. */
  setResources: (resources: EmergencyResourceView[]) => void;
  reset: () => void;
}

export const useResourceStore = create<ResourceStoreState>((set) => ({
  resources: [],
  setResources: (resources) => set({ resources }),
  reset: () => set({ resources: [] }),
}));
