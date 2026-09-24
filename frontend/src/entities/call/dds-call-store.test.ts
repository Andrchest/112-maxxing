import { afterEach, describe, expect, it } from 'vitest';
import { applyDdsCallEvent, currentDdsCall, useDdsCallStore } from './dds-call-store';
import { formatDialedRu } from './format';
import { makeDdsCall } from './test-fixtures';
import type { components } from '@/shared/api';

type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];

function event(eventType: string, payload: Record<string, unknown>): SessionEventEnvelope {
  return {
    seq_no: 9,
    event_type: eventType as SessionEventEnvelope['event_type'],
    timestamp_utc: '2026-01-01T00:00:00Z',
    monotonic_offset_ms: 5000,
    payload,
    actor_type: 'SIMULATION',
    correlation_id: null,
    redacted_keys: [],
  };
}

describe('the ДДС phone line store — one entry per call_id (I3 E6b, 80 §80.3)', () => {
  afterEach(() => useDdsCallStore.getState().reset());

  it('folds DDS_CALL_ANSWERED and DDS_CALL_ENDED onto the call they name, verbatim', () => {
    const calls = { 'call-1': makeDdsCall() };
    const answered = applyDdsCallEvent(calls, event('DDS_CALL_ANSWERED', { call_id: 'call-1', answered_by: 'AI', at_offset_ms: 5000 }));
    expect(answered['call-1']).toMatchObject({ state: 'CONNECTED', answered_by: 'AI', answered_at_offset_ms: 5000 });
    const ended = applyDdsCallEvent(answered, event('DDS_CALL_ENDED', { call_id: 'call-1', reason: 'HANGUP', duration_ms: 3000, at_offset_ms: 8000 }));
    expect(ended['call-1']).toMatchObject({ state: 'ENDED', end_reason: 'HANGUP', ended_at_offset_ms: 8000, available_actions: [] });
  });

  it('ignores an event of another call and every non-phone event', () => {
    const calls = { 'call-1': makeDdsCall() };
    expect(applyDdsCallEvent(calls, event('DDS_CALL_ENDED', { call_id: 'other', reason: 'BUSY', at_offset_ms: 1 }))).toBe(calls);
    expect(applyDdsCallEvent(calls, event('CALL_ENDED', { call_id: 'call-1', reason: 'X', at_offset_ms: 1 }))).toBe(calls);
  });

  it('shows the newest live call, else the newest call', () => {
    const old = makeDdsCall({ call_id: 'old', state: 'ENDED', started_at_offset_ms: 100 });
    const live = makeDdsCall({ call_id: 'live', state: 'CONNECTED', started_at_offset_ms: 50 });
    expect(currentDdsCall({ old, live })?.call_id).toBe('live');
    expect(currentDdsCall({ old })?.call_id).toBe('old');
    expect(currentDdsCall({})).toBeNull();
  });

  it('formats the claimant number the way a phone shows it', () => {
    expect(formatDialedRu('79161234567')).toBe('+7 (916) 123-45-67');
    expect(formatDialedRu('101')).toBe('101');
  });
});
