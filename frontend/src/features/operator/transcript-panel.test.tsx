import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { TranscriptPanel } from './transcript-panel';
import { ru } from '@/shared/i18n/ru';
import { useSessionEventsStore } from '@/entities/session';

describe('TranscriptPanel — collapsible, collapsed by default, read-only (D12 design decision #4)', () => {
  afterEach(() => {
    useSessionEventsStore.getState().reset('sess-1', 0);
  });

  it('is collapsed by default and shows no transcript lines', () => {
    useSessionEventsStore.getState().reset('sess-1', 0);
    useSessionEventsStore.getState().applyEvent({
      seq_no: 1,
      event_type: 'ASR_FINAL',
      timestamp_utc: '2026-09-21T10:00:00.000Z',
      monotonic_offset_ms: 1000,
      payload: { call_id: 'call-1', turn_index: 0, text: 'fire at 5 Lenina street' },
    });

    render(<TranscriptPanel />);

    expect(screen.queryByText('fire at 5 Lenina street')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: ru.operatorTranscriptShow })).toBeInTheDocument();
  });

  it('shows ASR_FINAL (operator) and CALLER_UTTERANCE_INTERRUPTED (caller, delivered_text only) lines once opened, and offers no action on them', async () => {
    const user = userEvent.setup();
    useSessionEventsStore.getState().reset('sess-1', 0);
    useSessionEventsStore.getState().applyEvent({
      seq_no: 1,
      event_type: 'ASR_FINAL',
      timestamp_utc: '2026-09-21T10:00:00.000Z',
      monotonic_offset_ms: 1000,
      payload: { call_id: 'call-1', turn_index: 0, text: 'fire at 5 Lenina street' },
    });
    useSessionEventsStore.getState().applyEvent({
      seq_no: 2,
      event_type: 'CALLER_UTTERANCE_INTERRUPTED',
      timestamp_utc: '2026-09-21T10:00:01.000Z',
      monotonic_offset_ms: 1500,
      payload: { call_id: 'call-1', turn_index: 1, delivered_text: 'there is smo', cutoff_latency_ms: 50 },
    });
    // Never rendered: WORLD_TRUTH_MUTATED is never visible to OPERATOR_112 (D3) and carries no
    // dialogue text this panel understands anyway.
    useSessionEventsStore.getState().applyEvent({
      seq_no: 3,
      event_type: 'CARD_FIELD_CHANGED',
      timestamp_utc: '2026-09-21T10:00:02.000Z',
      monotonic_offset_ms: 1600,
      payload: { card_id: 'card-1', revision_no: 1, field_path: 'address.house', new_value: '5' },
    });

    render(<TranscriptPanel />);
    await user.click(screen.getByRole('button', { name: ru.operatorTranscriptShow }));

    const operatorLine = screen.getByText('fire at 5 Lenina street');
    const callerLine = screen.getByText('there is smo');
    expect(operatorLine.tagName).toBe('LI');
    expect(callerLine.tagName).toBe('LI');
    expect(operatorLine.querySelector('button, a')).toBeNull();
    expect(callerLine.querySelector('button, a')).toBeNull();
  });
});
