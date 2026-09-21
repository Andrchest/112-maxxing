// Entity: the phone widget's LiveKit media state (SPEC §15, §32, §34; D9, D12). Deliberately a
// separate Zustand store from `entities/session/call-state-store.ts` (E8-A) — that one is
// replaced wholesale from the backend's `CallStateView` (the application WebSocket / REST); this
// one is driven only by `shared/media/call-media.ts`'s callbacks (the LiveKit room itself). A
// LiveKit reconnect must flip `phase` here without ever touching the WebSocket-fed stores (D9
// DESIGN: "does not touch stores fed by the application WebSocket").
import { create } from 'zustand';
import type { MediaPhase } from '@/shared/media/call-media';

export type { MediaPhase };

interface MediaState {
  phase: MediaPhase;
  muted: boolean;
  /** 0..1 local mic level (DESIGN: the level meter reads the local mic, never the caller's
   * audio). */
  level: number;
  micPermissionDenied: boolean;
  setPhase: (phase: MediaPhase) => void;
  setMuted: (muted: boolean) => void;
  setLevel: (level: number) => void;
  setMicPermissionDenied: (denied: boolean) => void;
  /** Back to the pre-join state — called when the widget starts a fresh join and whenever it
   * leaves the room. */
  reset: () => void;
}

const INITIAL_MEDIA_STATE = {
  phase: 'idle' as MediaPhase,
  muted: false,
  level: 0,
  micPermissionDenied: false,
};

export const useMediaStateStore = create<MediaState>((set) => ({
  ...INITIAL_MEDIA_STATE,
  setPhase: (phase) => set({ phase }),
  setMuted: (muted) => set({ muted }),
  setLevel: (level) => set({ level }),
  setMicPermissionDenied: (micPermissionDenied) => set({ micPermissionDenied }),
  reset: () => set({ ...INITIAL_MEDIA_STATE }),
}));
