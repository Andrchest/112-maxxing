import { afterEach, describe, expect, it } from 'vitest';
import { useRadioStore, type RadioMessageView } from './radio-store';

function makeMessage(overrides: Partial<RadioMessageView> = {}): RadioMessageView {
  return {
    radio_message_id: 'radio-1',
    seq_no: 1,
    incident_id: 'inc-1',
    from_callsign: 'АЦ-1',
    to_role: 'DDS',
    text_ru: 'x',
    resource_id: null,
    created_at_offset_ms: 0,
    source_world_event_id: null,
    ...overrides,
  };
}

describe('useRadioStore', () => {
  afterEach(() => {
    useRadioStore.getState().reset();
  });

  it('setMessages replaces the log wholesale with the given last_seq_no', () => {
    useRadioStore.getState().setMessages([makeMessage()], 5);
    expect(useRadioStore.getState().messages).toHaveLength(1);
    expect(useRadioStore.getState().lastSeqNo).toBe(5);
  });
});
