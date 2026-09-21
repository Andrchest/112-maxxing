// Entity: the phone widget's call state (D12, SPEC §32/§34). A separate Zustand store from
// session events because call state is its own realtime concern (D12: "one Zustand store per
// realtime concern (session events, call state)") — it is replaced wholesale by the latest
// `CallStateView` the backend sends (snapshot, or a future call-state push), never computed from
// events locally. The phone widget itself lands in E11; this is the store it will read.
import { create } from 'zustand';
import type { components } from '@/shared/api';

export type CallStateView = components['schemas']['CallStateView'];

interface CallStateStore {
  callState: CallStateView | null;
  setCallState: (callState: CallStateView | null) => void;
}

export const useCallStateStore = create<CallStateStore>((set) => ({
  callState: null,
  setCallState: (callState) => set({ callState }),
}));
