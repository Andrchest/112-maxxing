import { describe, expect, it } from 'vitest';
import { applyCardEvent } from './apply-card-event';
import type { OperatorCardView } from './card-store';
import type { components } from '@/shared/api';

type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];

function makeCard(overrides: Partial<OperatorCardView> = {}): OperatorCardView {
  return {
    card_id: 'card-1',
    incident_id: 'inc-1',
    values: {},
    revision_counter: 0,
    field_specs: [],
    ...overrides,
  };
}

function makeEnvelope(overrides: Partial<SessionEventEnvelope>): SessionEventEnvelope {
  return {
    seq_no: 1,
    event_type: 'CARD_FIELD_CHANGED',
    timestamp_utc: '2026-09-21T10:00:00.000Z',
    monotonic_offset_ms: 1000,
    payload: {},
    ...overrides,
  };
}

describe('applyCardEvent', () => {
  it('applies CARD_FIELD_CHANGED, converging with what a command response would set', () => {
    const previous = makeCard({ values: { 'address.house': '27' } });
    const event = makeEnvelope({
      event_type: 'CARD_FIELD_CHANGED',
      payload: { card_id: 'card-1', revision_no: 3, field_path: 'address.house', new_value: '72' },
    });

    const next = applyCardEvent(previous, event);

    expect(next?.values['address.house']).toBe('72');
    expect(next?.revision_counter).toBe(3);
  });

  it('is idempotent: applying the same CARD_FIELD_CHANGED twice yields the same value', () => {
    const previous = makeCard();
    const event = makeEnvelope({
      event_type: 'CARD_FIELD_CHANGED',
      payload: { card_id: 'card-1', revision_no: 1, field_path: 'caller.phone', new_value: '+7123' },
    });

    const once = applyCardEvent(previous, event);
    const twice = applyCardEvent(once, event);

    expect(twice?.values['caller.phone']).toBe('+7123');
    expect(twice?.revision_counter).toBe(1);
  });

  it('never regresses revision_counter behind a later command response', () => {
    // Race: the command response (revision_counter 5) already landed; a stale replayed event
    // for an earlier revision must not roll the counter back.
    const previous = makeCard({ revision_counter: 5, values: { 'address.house': '72' } });
    const staleEvent = makeEnvelope({
      event_type: 'CARD_FIELD_CHANGED',
      payload: { card_id: 'card-1', revision_no: 2, field_path: 'address.house', new_value: '27' },
    });

    const next = applyCardEvent(previous, staleEvent);

    expect(next?.revision_counter).toBe(5);
  });

  it('applies SERVICE_SELECTED to recipients.services', () => {
    const previous = makeCard();
    const event = makeEnvelope({
      event_type: 'SERVICE_SELECTED',
      payload: { card_id: 'card-1', selected_services: ['FIRE_RESCUE', 'AMBULANCE'] },
    });

    const next = applyCardEvent(previous, event);

    expect(next?.values['recipients.services']).toEqual(['FIRE_RESCUE', 'AMBULANCE']);
  });

  it('applies SERVICE_DESELECTED to recipients.services', () => {
    const previous = makeCard({ values: { 'recipients.services': ['FIRE_RESCUE', 'AMBULANCE'] } });
    const event = makeEnvelope({
      event_type: 'SERVICE_DESELECTED',
      payload: { card_id: 'card-1', selected_services: ['AMBULANCE'] },
    });

    const next = applyCardEvent(previous, event);

    expect(next?.values['recipients.services']).toEqual(['AMBULANCE']);
  });

  it('ignores an event for a different card_id', () => {
    const previous = makeCard({ values: { 'address.house': '27' } });
    const event = makeEnvelope({
      event_type: 'CARD_FIELD_CHANGED',
      payload: { card_id: 'other-card', revision_no: 9, field_path: 'address.house', new_value: '99' },
    });

    expect(applyCardEvent(previous, event)).toBe(previous);
  });

  it('ignores event types the card does not react to (e.g. ASR_FINAL — DESIGN 2)', () => {
    const previous = makeCard({ values: { 'description.text': '' } });
    const event = makeEnvelope({
      event_type: 'ASR_FINAL',
      payload: { call_id: 'call-1', turn_index: 0, text: 'пожар на улице Ленина дом 5' },
    });

    expect(applyCardEvent(previous, event)).toBe(previous);
  });

  it('returns null unchanged when there is no card yet', () => {
    const event = makeEnvelope({
      event_type: 'CARD_FIELD_CHANGED',
      payload: { card_id: 'card-1', revision_no: 1, field_path: 'address.house', new_value: '1' },
    });
    expect(applyCardEvent(null, event)).toBeNull();
  });
});
