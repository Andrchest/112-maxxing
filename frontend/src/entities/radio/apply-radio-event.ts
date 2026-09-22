// Pure reducer: folds one realtime `RADIO_MESSAGE_CREATED` event onto the current radio log
// (`docs/hld/10-domain-model.md` §10.13 payload catalog). The payload lacks `incident_id`
// (`RadioMessageView` requires it) — `incidentId` is passed in as context, same treatment as
// `entities/notification`'s `apply-notification-event.ts`. `seq_no` is the envelope's own
// `seq_no` — `RadioMessageView.seq_no` is documented as "the log position it was read from"
// (openapi.yaml), which for a live event is exactly this envelope's position.
//
// INV 3: `source_world_event_id` is neither read nor stored — see `apply-notification-event.ts`.
//
// Idempotent by `radio_message_id` (a duplicate delivery is a no-op) and kept sorted by `seq_no`
// (log order), matching `listRadioMessages`' own contract.
import type { RadioMessageView } from './radio-store';
import type { components } from '@/shared/api';

type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];
type RoleType = components['schemas']['RoleType'];

interface RadioMessageCreatedPayload {
  radio_message_id: string;
  from_callsign: string;
  to_role: RoleType;
  text_ru: string;
  resource_id: string | null;
  at_offset_ms: number;
}

export interface ApplyRadioEventContext {
  incidentId: string;
}

export function applyRadioMessageEvent(
  previous: RadioMessageView[],
  event: SessionEventEnvelope,
  context: ApplyRadioEventContext,
): RadioMessageView[] {
  if (event.event_type !== 'RADIO_MESSAGE_CREATED') {
    return previous;
  }
  const payload = event.payload as unknown as RadioMessageCreatedPayload;
  if (previous.some((message) => message.radio_message_id === payload.radio_message_id)) {
    return previous;
  }
  const created: RadioMessageView = {
    radio_message_id: payload.radio_message_id,
    seq_no: event.seq_no,
    incident_id: context.incidentId,
    from_callsign: payload.from_callsign,
    to_role: payload.to_role,
    text_ru: payload.text_ru,
    resource_id: payload.resource_id,
    created_at_offset_ms: payload.at_offset_ms,
  };
  return [...previous, created].sort((a, b) => a.seq_no - b.seq_no);
}
