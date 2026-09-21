// Entity: the Operator 112 stage's transition surface (D12 design decision #1 — "the frontend
// never decides. Every button's presence/enabled state comes from the last `available_actions`
// the server sent (command response or snapshot)"). This store holds exactly that: the current
// `stage_state`, `available_actions` and the session-level bookkeeping every operator command
// response and the refresh snapshot both carry. It is replaced wholesale on every command
// response and on every snapshot fetch — never computed locally, never updated from a WebSocket
// event (unlike `entities/call`, no HLD table describes a stage-state realtime push the frontend
// may trust as authoritative for `available_actions`; a `STAGE_STATE_CHANGED` event is instead
// treated as "go re-fetch the snapshot", which still only ever writes this store from a REST
// response).
import { create } from 'zustand';
import type { components } from '@/shared/api';

export type Operator112StageState = components['schemas']['Operator112StageState'];
export type ActionDescriptor = components['schemas']['ActionDescriptor'];
export type SessionState = components['schemas']['SessionState'];
export type OperatorStageView = components['schemas']['OperatorStageView'];
export type SessionSnapshot = components['schemas']['SessionSnapshot'];

interface StageStoreState {
  roleStageId: string | null;
  stageState: Operator112StageState | null;
  availableActions: ActionDescriptor[];
  sessionState: SessionState | null;
  lastSeqNo: number;
  /** Every `/operator/*` command returns an `OperatorStageView` — replace wholesale. */
  setFromStageView: (view: OperatorStageView) => void;
  /** `getSessionSnapshot` restore path (SPEC §39, §42 test 13). */
  setFromSnapshot: (snapshot: SessionSnapshot) => void;
  reset: () => void;
}

export const useStageStore = create<StageStoreState>((set) => ({
  roleStageId: null,
  stageState: null,
  availableActions: [],
  sessionState: null,
  lastSeqNo: 0,
  setFromStageView: (view) =>
    set({
      roleStageId: view.role_stage_id,
      stageState: view.stage_state,
      availableActions: view.available_actions,
      sessionState: view.session_state,
      lastSeqNo: view.last_seq_no,
    }),
  setFromSnapshot: (snapshot) =>
    set({
      roleStageId: snapshot.active_role_stage_id,
      // The snapshot's `stage_state` is a `StageState` (Operator112StageState | DDSStageState);
      // this store is Operator-console-only, so a DDS-shaped value here would mean the caller
      // opened the wrong console for this session (guarded in the console page, not here).
      stageState: snapshot.stage_state as Operator112StageState | null,
      availableActions: snapshot.available_actions,
      sessionState: snapshot.session.state,
      lastSeqNo: snapshot.last_seq_no,
    }),
  reset: () => set({ roleStageId: null, stageState: null, availableActions: [], sessionState: null, lastSeqNo: 0 }),
}));

/** Whether `actionId` is currently offered by the server (D12 design decision #1). Every button
 * and every field-level permission check goes through this — never a hard-coded stage_state
 * switch. */
export function hasAvailableAction(actions: readonly ActionDescriptor[], actionId: string): boolean {
  return actions.some((action) => action.action_id === actionId);
}
