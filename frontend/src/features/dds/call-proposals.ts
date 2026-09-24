// The statuses a service head reported on a ДДС call, per leg (I3 E6c, HLD 80 §80.3.3, D24: the AI
// proposes, the trainee commits). Folded from `DDS_CALL_STATUS_PROPOSED` — live from the socket and,
// after a refresh, from `listSessionEvents {event_type: DDS_CALL_STATUS_PROPOSED}` (INV 13). The
// pencil form offers a proposal only when its status is one of the leg's own `available_actions`
// targets, so a proposal the leg has moved past simply stops being offered: nothing here decides
// what is legal, the server's actions do.
import { create } from 'zustand';
import type { components } from '@/shared/api';

type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];
type ServiceResponseStatus = components['schemas']['ServiceResponseStatus'];

export interface CallStatusProposal {
  seq_no: number;
  call_id: string;
  assignment_id: string;
  status: ServiceResponseStatus;
  order_number: string | null;
  comment_ru: string | null;
  due_offset_ms: number;
}

interface ProposedPayload {
  call_id: string;
  assignment_id: string;
  status: ServiceResponseStatus;
  order_number: string | null;
  comment_ru: string | null;
  due_offset_ms: number;
}

export const PROPOSAL_EVENT_TYPE = 'DDS_CALL_STATUS_PROPOSED';

/** Adds one `DDS_CALL_STATUS_PROPOSED` to its leg (idempotent per `seq_no`); other events pass. */
export function applyProposalEvent(
  byLeg: Record<string, CallStatusProposal[]>,
  event: SessionEventEnvelope,
): Record<string, CallStatusProposal[]> {
  if (event.event_type !== PROPOSAL_EVENT_TYPE) return byLeg;
  const payload = event.payload as unknown as ProposedPayload;
  const existing = byLeg[payload.assignment_id] ?? [];
  if (existing.some((item) => item.seq_no === event.seq_no)) return byLeg;
  const proposal: CallStatusProposal = {
    seq_no: event.seq_no,
    call_id: payload.call_id,
    assignment_id: payload.assignment_id,
    status: payload.status,
    order_number: payload.order_number ?? null,
    comment_ru: payload.comment_ru ?? null,
    due_offset_ms: payload.due_offset_ms,
  };
  return { ...byLeg, [payload.assignment_id]: [...existing, proposal] };
}

/** The newest proposal of the leg whose status is `status` (the form's target), else `null`. */
export function latestProposalFor(
  proposals: readonly CallStatusProposal[] | undefined,
  statuses: ReadonlySet<string>,
): CallStatusProposal | null {
  const matching = (proposals ?? []).filter((item) => statuses.has(item.status));
  return matching[matching.length - 1] ?? null;
}

interface CallProposalState {
  byLeg: Record<string, CallStatusProposal[]>;
  applyEvent: (event: SessionEventEnvelope) => void;
  applyEvents: (events: readonly SessionEventEnvelope[]) => void;
  reset: () => void;
}

export const useCallProposalStore = create<CallProposalState>((set) => ({
  byLeg: {},
  applyEvent: (event) => set((state) => ({ byLeg: applyProposalEvent(state.byLeg, event) })),
  applyEvents: (events) => set((state) => ({ byLeg: events.reduce(applyProposalEvent, state.byLeg) })),
  reset: () => set({ byLeg: {} }),
}));
