import { describe, expect, it } from 'vitest';
import { applyCallEvent, type CallStateView } from './apply-call-event';
import { formatCallDurationMs } from './format';
import type { components } from '@/shared/api';

type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];

function makeEnvelope(overrides: Partial<SessionEventEnvelope>): SessionEventEnvelope {
  return {
    seq_no: 1,
    event_type: 'CALL_RINGING',
    timestamp_utc: '2026-09-21T10:00:00.000Z',
    monotonic_offset_ms: 1000,
    payload: {},
    ...overrides,
  };
}

function connectedCall(overrides: Partial<CallStateView> = {}): CallStateView {
  return {
    call_id: 'call-1',
    room_name: 'room-1',
    phase: 'CONNECTED',
    caller_display_ru: 'Абонент',
    started_at_offset_ms: 0,
    answered_at_offset_ms: 500,
    ended_at_offset_ms: null,
    duration_ms: null,
    caller_speaking: false,
    ...overrides,
  };
}

describe('applyCallEvent', () => {
  it('CALL_RINGING starts a fresh NO_CALL -> RINGING call state', () => {
    const event = makeEnvelope({
      event_type: 'CALL_RINGING',
      payload: { call_id: 'call-1', room_name: 'room-1', caller_display_ru: 'Абонент', at_offset_ms: 100 },
    });

    const next = applyCallEvent(null, event);

    expect(next).toEqual({
      call_id: 'call-1',
      room_name: 'room-1',
      phase: 'RINGING',
      caller_display_ru: 'Абонент',
      started_at_offset_ms: 100,
      answered_at_offset_ms: null,
      ended_at_offset_ms: null,
      duration_ms: null,
      caller_speaking: false,
    });
  });

  it('CALL_ANSWERED moves RINGING -> CONNECTED', () => {
    const ringing: CallStateView = {
      call_id: 'call-1',
      room_name: 'room-1',
      phase: 'RINGING',
      caller_display_ru: 'Абонент',
      started_at_offset_ms: 100,
      answered_at_offset_ms: null,
      ended_at_offset_ms: null,
      duration_ms: null,
      caller_speaking: false,
    };
    const event = makeEnvelope({
      event_type: 'CALL_ANSWERED',
      payload: { call_id: 'call-1', at_offset_ms: 5000, ring_duration_ms: 4900, answered_by_user_id: 'u1' },
    });

    const next = applyCallEvent(ringing, event);

    expect(next?.phase).toBe('CONNECTED');
    expect(next?.answered_at_offset_ms).toBe(5000);
  });

  it('CALL_ENDED moves CONNECTED -> ENDED and clears caller_speaking', () => {
    const event = makeEnvelope({
      event_type: 'CALL_ENDED',
      payload: { call_id: 'call-1', at_offset_ms: 20000, duration_ms: 15000, ended_by: 'TRAINEE', reason: 'OPERATOR_HANGUP' },
    });

    const next = applyCallEvent(connectedCall({ caller_speaking: true }), event);

    expect(next?.phase).toBe('ENDED');
    expect(next?.duration_ms).toBe(15000);
    expect(next?.caller_speaking).toBe(false);
  });

  it('CALLER_TTS_STARTED / CALLER_TTS_ENDED toggle caller_speaking', () => {
    const started = applyCallEvent(connectedCall(), makeEnvelope({ event_type: 'CALLER_TTS_STARTED' }));
    expect(started?.caller_speaking).toBe(true);

    const ended = applyCallEvent(started, makeEnvelope({ event_type: 'CALLER_TTS_ENDED' }));
    expect(ended?.caller_speaking).toBe(false);
  });

  it('ignores an event for a different call_id', () => {
    const previous = connectedCall();
    const event = makeEnvelope({
      event_type: 'CALL_ENDED',
      payload: { call_id: 'other-call', at_offset_ms: 1, duration_ms: 1, ended_by: 'TRAINEE', reason: 'OPERATOR_HANGUP' },
    });
    expect(applyCallEvent(previous, event)).toBe(previous);
  });

  it('ignores unrelated event types (e.g. ASR_FINAL)', () => {
    const previous = connectedCall();
    expect(applyCallEvent(previous, makeEnvelope({ event_type: 'ASR_FINAL' }))).toBe(previous);
  });
});

describe('formatCallDurationMs', () => {
  it('formats whole minutes and seconds as MM:SS', () => {
    expect(formatCallDurationMs(0)).toBe('00:00');
    expect(formatCallDurationMs(59_000)).toBe('00:59');
    expect(formatCallDurationMs(60_000)).toBe('01:00');
    expect(formatCallDurationMs(125_000)).toBe('02:05');
  });
});
