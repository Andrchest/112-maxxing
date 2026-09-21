// Pure reducer: folds one realtime `SessionEventEnvelope` onto the current `CallStateView`
// (SPEC §32/§34; D12: the phone widget's states come from `CallStateView.phase`, and
// `caller_speaking` from events). The store itself (`entities/session/call-state-store.ts`, owned
// by E8-A) is "replaced wholesale by the latest CallStateView the backend sends" — this function
// is what builds that wholesale replacement from an event payload instead of a REST response, so
// the phone widget can react to `CALL_RINGING`/`CALL_ANSWERED`/`CALL_ENDED`/`CALLER_TTS_*`
// without waiting for a poll. Every field written here is copied verbatim from the event payload
// (`docs/hld/10-domain-model.md` §10.13) — nothing is inferred or guessed.
import type { components } from '@/shared/api';

export type CallStateView = components['schemas']['CallStateView'];
type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];

interface CallRingingPayload {
  call_id: string;
  room_name: string;
  caller_display_ru: string;
  at_offset_ms: number;
}
interface CallAnsweredPayload {
  call_id: string;
  at_offset_ms: number;
}
interface CallEndedPayload {
  call_id: string;
  at_offset_ms: number;
  duration_ms: number;
}

export function applyCallEvent(
  previous: CallStateView | null,
  event: SessionEventEnvelope,
): CallStateView | null {
  switch (event.event_type) {
    case 'CALL_RINGING': {
      const payload = event.payload as unknown as CallRingingPayload;
      return {
        call_id: payload.call_id,
        room_name: payload.room_name,
        phase: 'RINGING',
        caller_display_ru: payload.caller_display_ru,
        started_at_offset_ms: payload.at_offset_ms,
        answered_at_offset_ms: null,
        ended_at_offset_ms: null,
        duration_ms: null,
        caller_speaking: false,
      };
    }
    case 'CALL_ANSWERED': {
      if (previous === null) return previous;
      const payload = event.payload as unknown as CallAnsweredPayload;
      if (payload.call_id !== previous.call_id) return previous;
      return { ...previous, phase: 'CONNECTED', answered_at_offset_ms: payload.at_offset_ms };
    }
    case 'CALL_ENDED': {
      if (previous === null) return previous;
      const payload = event.payload as unknown as CallEndedPayload;
      if (payload.call_id !== previous.call_id) return previous;
      return {
        ...previous,
        phase: 'ENDED',
        ended_at_offset_ms: payload.at_offset_ms,
        duration_ms: payload.duration_ms,
        caller_speaking: false,
      };
    }
    // HLD gap (see report): `docs/hld/10-domain-model.md` §10.13 lists CALLER_TTS_STARTED/ENDED
    // as INSTRUCTOR-only, but `docs/hld/40-realtime-protocol.md` §40.4 row 12-13 says OPERATOR_112
    // receives both, redacted to `{call_id, turn_index, at_offset_ms[, completed]}` — exactly
    // enough to drive `caller_speaking` (D12 design decision #3). Trusting §40.4 as the wire
    // contract.
    case 'CALLER_TTS_STARTED': {
      if (previous === null) return previous;
      return { ...previous, caller_speaking: true };
    }
    case 'CALLER_TTS_ENDED':
    case 'CALLER_UTTERANCE_INTERRUPTED': {
      if (previous === null) return previous;
      return { ...previous, caller_speaking: false };
    }
    default:
      return previous;
  }
}
