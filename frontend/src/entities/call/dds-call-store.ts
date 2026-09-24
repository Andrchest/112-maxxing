// Entity: the ДДС phone line's calls, one entry per `call_id` (I3 E6b, HLD 80 §80.3, §80.6.1).
// The 112 call keeps its own singular `CallStateView` store (`entities/session`); a ДДС call is
// never folded into it (80 §80.3.6: "a DDS call never writes `session:{id}:call_state`"). This
// store is replaced from the server's `DdsCallView`s (`listDdsCalls`, `startDdsCall`,
// `hangUpDdsCall`) and nudged between refetches by the three `DDS_CALL_*` events — every field it
// writes is copied from a server payload, never inferred.
import { create } from 'zustand';
import type { components } from '@/shared/api';

export type DdsCallView = components['schemas']['DdsCallView'];
type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];

interface DdsCallAnsweredPayload {
  call_id: string;
  answered_by: DdsCallView['answered_by'];
  at_offset_ms: number;
}
interface DdsCallEndedPayload {
  call_id: string;
  reason: DdsCallView['end_reason'];
  at_offset_ms: number;
}

/** The phone-line event types this store folds (the refetch trigger for the widget too). */
export const DDS_CALL_EVENT_TYPES: ReadonlySet<string> = new Set(['DDS_CALL_STARTED', 'DDS_CALL_ANSWERED', 'DDS_CALL_ENDED']);

/** Folds one `DDS_CALL_ANSWERED` / `DDS_CALL_ENDED` onto the call it names. `DDS_CALL_STARTED`
 * carries no `DdsCallView` (the view is the read model's), so a new call arrives by refetch. */
export function applyDdsCallEvent(calls: Record<string, DdsCallView>, event: SessionEventEnvelope): Record<string, DdsCallView> {
  if (event.event_type === 'DDS_CALL_ANSWERED') {
    const payload = event.payload as unknown as DdsCallAnsweredPayload;
    const call = calls[payload.call_id];
    if (!call) return calls;
    return {
      ...calls,
      [payload.call_id]: { ...call, state: 'CONNECTED', answered_by: payload.answered_by, answered_at_offset_ms: payload.at_offset_ms },
    };
  }
  if (event.event_type === 'DDS_CALL_ENDED') {
    const payload = event.payload as unknown as DdsCallEndedPayload;
    const call = calls[payload.call_id];
    if (!call) return calls;
    return {
      ...calls,
      [payload.call_id]: {
        ...call,
        state: 'ENDED',
        end_reason: payload.reason,
        ended_at_offset_ms: payload.at_offset_ms,
        available_actions: [],
      },
    };
  }
  return calls;
}

/** The call the widget shows: the newest live one, else the newest one, else `null`. */
export function currentDdsCall(calls: Record<string, DdsCallView>): DdsCallView | null {
  const all = Object.values(calls).sort((a, b) => b.started_at_offset_ms - a.started_at_offset_ms);
  return all.find((call) => call.state !== 'ENDED') ?? all[0] ?? null;
}

interface DdsCallState {
  calls: Record<string, DdsCallView>;
  setCalls: (views: DdsCallView[]) => void;
  upsertCall: (view: DdsCallView) => void;
  applyEvent: (event: SessionEventEnvelope) => void;
  reset: () => void;
}

export const useDdsCallStore = create<DdsCallState>((set) => ({
  calls: {},
  setCalls: (views) => set({ calls: Object.fromEntries(views.map((view) => [view.call_id, view])) }),
  upsertCall: (view) => set((state) => ({ calls: { ...state.calls, [view.call_id]: view } })),
  applyEvent: (event) => set((state) => ({ calls: applyDdsCallEvent(state.calls, event) })),
  reset: () => set({ calls: {} }),
}));
