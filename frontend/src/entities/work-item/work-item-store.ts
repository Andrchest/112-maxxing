// Entity: the DDS trainee's transition surface + incoming work item (SPEC §10, §11, §32, §39;
// D3, D12 design decision #1). The DDS analogue of `entities/stage` + `entities/card` combined
// into one store, because `DdsStageView` (D8) already bundles `work_item`, `stage_state` (mirrored
// on `work_item.state` per §10.7 — one `DDSStageState` per role stage) and `available_actions`
// into a single materialized view, and `DdsWorkItem` is manager-ruled to be ONE stage-wide item
// (never "N work items", several recipient services and unioned resource-id lists inside it).
// Replaced wholesale on every command response and on every snapshot fetch (D12 design decision
// #1) — `work_item` alone is additionally folded from WS events between refreshes
// (`apply-work-item-event.ts`), exactly as `entities/card`'s `applyCardEvent` does for the
// operator card.
import { create } from 'zustand';
import type { components } from '@/shared/api';

export type DdsWorkItem = components['schemas']['DdsWorkItem'];
export type DDSStageState = components['schemas']['DDSStageState'];
export type ActionDescriptor = components['schemas']['ActionDescriptor'];
export type SessionState = components['schemas']['SessionState'];
export type DdsStageView = components['schemas']['DdsStageView'];
export type SessionSnapshot = components['schemas']['SessionSnapshot'];

interface WorkItemStoreState {
  roleStageId: string | null;
  workItem: DdsWorkItem | null;
  availableActions: ActionDescriptor[];
  sessionState: SessionState | null;
  lastSeqNo: number;
  /** Every `/dds/*` command returns a `DdsStageView` — replace wholesale. The caller (the DDS
   * console page) is also responsible for feeding `view.resources` into `entities/resource`
   * (D12 design decision #1 mirrors `entities/stage`'s `setFromStageView` split). */
  setFromStageView: (view: DdsStageView) => void;
  /** `getSessionSnapshot` restore path (SPEC §39, §42 test 13). `snapshot.work_item` is present
   * for `DDS` only, built solely from the `HandoffSnapshot` (D3). */
  setFromSnapshot: (snapshot: SessionSnapshot) => void;
  setWorkItem: (workItem: DdsWorkItem | null) => void;
  reset: () => void;
}

export const useWorkItemStore = create<WorkItemStoreState>((set) => ({
  roleStageId: null,
  workItem: null,
  availableActions: [],
  sessionState: null,
  lastSeqNo: 0,
  setFromStageView: (view) =>
    set({
      roleStageId: view.role_stage_id,
      workItem: view.work_item,
      availableActions: view.available_actions,
      sessionState: view.session_state,
      lastSeqNo: view.last_seq_no,
    }),
  setFromSnapshot: (snapshot) =>
    set({
      roleStageId: snapshot.active_role_stage_id,
      workItem: snapshot.work_item,
      availableActions: snapshot.available_actions,
      sessionState: snapshot.session.state,
      lastSeqNo: snapshot.last_seq_no,
    }),
  setWorkItem: (workItem) => set({ workItem }),
  reset: () => set({ roleStageId: null, workItem: null, availableActions: [], sessionState: null, lastSeqNo: 0 }),
}));

/** Whether `actionId` is currently offered by the server (D12 design decision #1) — identical
 * contract to `entities/stage`'s `hasAvailableAction`, duplicated here because DDS never imports
 * the Operator-console-only `entities/stage` module. */
export function hasAvailableAction(actions: readonly ActionDescriptor[], actionId: string): boolean {
  return actions.some((action) => action.action_id === actionId);
}
