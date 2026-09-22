import { describe, expect, it } from 'vitest';
import { applyRadioMessageEvent } from './apply-radio-event';
import type { RadioMessageView } from './radio-store';
import type { components } from '@/shared/api';

type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];

function makeMessage(overrides: Partial<RadioMessageView> = {}): RadioMessageView {
  return {
    radio_message_id: 'radio-1',
    seq_no: 3,
    incident_id: 'inc-1',
    from_callsign: 'АЦ-2',
    to_role: 'DDS',
    text_ru: 'Выехали.',
    resource_id: 'res-ac2',
    created_at_offset_ms: 1000,
    ...overrides,
  };
}

function makeEvent(overrides: Partial<SessionEventEnvelope> = {}): SessionEventEnvelope {
  return {
    seq_no: 8,
    event_type: 'RADIO_MESSAGE_CREATED',
    timestamp_utc: '2026-09-21T10:00:00Z',
    monotonic_offset_ms: 6000,
    payload: { radio_message_id: 'radio-2', from_callsign: 'АЦ-2', to_role: 'DDS', text_ru: 'Авария, требуется замена.', resource_id: 'res-ac2', source_world_event_id: 'ac2_breakdown', at_offset_ms: 6000 },
    ...overrides,
  };
}

const CTX = { incidentId: 'inc-1' };

describe('applyRadioMessageEvent', () => {
  it('appends a new message, using the envelope seq_no', () => {
    const previous = [makeMessage()];
    const next = applyRadioMessageEvent(previous, makeEvent(), CTX);
    expect(next).toHaveLength(2);
    expect(next[1]?.radio_message_id).toBe('radio-2');
    expect(next[1]?.seq_no).toBe(8);
    expect(next[1]?.incident_id).toBe('inc-1');
  });

  it('keeps log order (sorted by seq_no) even if events arrive out of order', () => {
    const previous = [makeMessage({ radio_message_id: 'radio-9', seq_no: 9 })];
    const next = applyRadioMessageEvent(previous, makeEvent({ seq_no: 8 }), CTX);
    expect(next.map((m) => m.seq_no)).toEqual([8, 9]);
  });

  it('is idempotent by radio_message_id', () => {
    const previous = [makeMessage({ radio_message_id: 'radio-2', seq_no: 8 })];
    const next = applyRadioMessageEvent(previous, makeEvent(), CTX);
    expect(next).toBe(previous);
  });

  it('ignores unrelated event types', () => {
    const previous = [makeMessage()];
    const next = applyRadioMessageEvent(previous, makeEvent({ event_type: 'NOTIFICATION_CREATED', payload: {} }), CTX);
    expect(next).toBe(previous);
  });
});
