// Entity: the realtime session-event log (D12, D5, `docs/hld/40-realtime-protocol.md`). Holds
// exactly what the server sent — a REST snapshot's `last_seq_no` plus the events the WebSocket
// client (`shared/realtime/ws-client.ts`) has applied since. No component computes a stage
// transition, a score or a card value from this data (D12 design decision #3); it is a log, not
// a derived model.
import { create } from 'zustand';
import type { components } from '@/shared/api';

export type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];

interface SessionEventsState {
  sessionId: string | null;
  lastSeqNo: number;
  events: SessionEventEnvelope[];
  live: boolean;
  /** Starts a fresh log for `sessionId`, seeded with the REST snapshot's `last_seq_no`
   * (`docs/hld/40-realtime-protocol.md` §40.5 step 2-3). */
  reset: (sessionId: string, lastSeqNo: number) => void;
  /** Idempotent by `seq_no` (HLD §40.3 at-least-once delivery): applying the same event twice —
   * the replay/live seam duplicate — is a no-op. */
  applyEvent: (event: SessionEventEnvelope) => void;
  setLive: (live: boolean) => void;
}

export const useSessionEventsStore = create<SessionEventsState>((set, get) => ({
  sessionId: null,
  lastSeqNo: 0,
  events: [],
  live: false,
  reset: (sessionId, lastSeqNo) => set({ sessionId, lastSeqNo, events: [], live: false }),
  applyEvent: (event) => {
    const { events } = get();
    if (events.some((existing) => existing.seq_no === event.seq_no)) {
      return;
    }
    const nextEvents = [...events, event].sort((a, b) => a.seq_no - b.seq_no);
    set({ events: nextEvents, lastSeqNo: Math.max(get().lastSeqNo, event.seq_no) });
  },
  setLive: (live) => set({ live }),
}));
