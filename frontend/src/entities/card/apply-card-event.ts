// Pure reducer: folds one realtime `SessionEventEnvelope` onto the current `OperatorCardView`
// (D12 design decision #5: "CARD_FIELD_CHANGED from the log and the command response must
// converge to the same value"). Input and output are both server-shaped data — the event payload
// keys are copied verbatim from `docs/hld/10-domain-model.md` §10.13; nothing here invents or
// infers a value the backend did not send, so this is not the "autofill from ASR" SPEC §9
// forbids (that prohibition is about inferring a fact from the transcript, not about applying a
// server-confirmed mutation of the same field the trainee is already editing).
//
// Applying the same CARD_FIELD_CHANGED twice (the replay/live seam, HLD §40.3) is a no-op because
// it just overwrites `values[field_path]` with the same `new_value` again — idempotent by
// construction, no seq_no bookkeeping needed here (the session-events store already de-dupes by
// seq_no for the log itself).
import type { OperatorCardView, FactValue } from './card-store';
import type { components } from '@/shared/api';

type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];
type ServiceId = components['schemas']['ServiceCatalogEntry']['id'];

interface CardFieldChangedPayload {
  card_id: string;
  revision_no: number;
  field_path: string;
  new_value: FactValue;
}

interface ServiceSelectionChangedPayload {
  card_id: string;
  selected_services: ServiceId[];
}

/** Folds one event onto `previous`. Returns `previous` unchanged for any event type this card
 * does not react to, or when the event belongs to a different card (defensive; should not happen
 * within one session). */
export function applyCardEvent(
  previous: OperatorCardView | null,
  event: SessionEventEnvelope,
): OperatorCardView | null {
  if (previous === null) {
    return previous;
  }
  switch (event.event_type) {
    case 'CARD_FIELD_CHANGED': {
      const payload = event.payload as unknown as CardFieldChangedPayload;
      if (payload.card_id !== previous.card_id) {
        return previous;
      }
      return {
        ...previous,
        values: { ...previous.values, [payload.field_path]: payload.new_value },
        revision_counter: Math.max(previous.revision_counter, payload.revision_no),
      };
    }
    case 'SERVICE_SELECTED':
    case 'SERVICE_DESELECTED': {
      const payload = event.payload as unknown as ServiceSelectionChangedPayload;
      if (payload.card_id !== previous.card_id) {
        return previous;
      }
      return {
        ...previous,
        values: { ...previous.values, 'recipients.services': payload.selected_services },
      };
    }
    default:
      return previous;
  }
}
