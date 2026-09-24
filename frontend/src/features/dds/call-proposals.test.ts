import { afterEach, describe, expect, it } from 'vitest';
import { applyProposalEvent, latestProposalFor, useCallProposalStore } from './call-proposals';
import type { components } from '@/shared/api';

type Envelope = components['schemas']['SessionEventEnvelope'];

function proposed(seqNo: number, status: string, overrides: Record<string, unknown> = {}): Envelope {
  return {
    seq_no: seqNo,
    event_type: 'DDS_CALL_STATUS_PROPOSED',
    timestamp_utc: '2026-09-24T10:00:00Z',
    monotonic_offset_ms: seqNo * 1000,
    payload: {
      call_id: 'call-1',
      assignment_id: 'assign-1',
      service_type: 'FIRE_RESCUE',
      status,
      order_number: null,
      comment_ru: null,
      script_after_ms: 15000,
      due_offset_ms: 20000,
      at_offset_ms: seqNo * 1000,
      ...overrides,
    },
  };
}

describe('call proposals — the statuses a service head reported (I3 E6c, 80 par.80.3.3)', () => {
  afterEach(() => useCallProposalStore.getState().reset());

  it('folds DDS_CALL_STATUS_PROPOSED per leg, once per event, and ignores other events', () => {
    let byLeg = applyProposalEvent({}, proposed(3, 'ACCEPTED'));
    byLeg = applyProposalEvent(byLeg, proposed(3, 'ACCEPTED'));
    byLeg = applyProposalEvent(byLeg, proposed(4, 'RESPONSE_STARTED', { order_number: '2415' }));
    byLeg = applyProposalEvent(byLeg, { ...proposed(5, 'ARRIVED'), event_type: 'DDS_CALL_ENDED' });
    expect(byLeg['assign-1']?.map((item) => [item.status, item.order_number])).toEqual([
      ['ACCEPTED', null],
      ['RESPONSE_STARTED', '2415'],
    ]);
  });

  it("offers only a proposal whose status is one of the leg's next statuses", () => {
    const byLeg = [proposed(3, 'ACCEPTED'), proposed(4, 'RESPONSE_STARTED')].reduce(applyProposalEvent, {});
    expect(latestProposalFor(byLeg['assign-1'], new Set(['RESPONSE_STARTED']))?.status).toBe('RESPONSE_STARTED');
    expect(latestProposalFor(byLeg['assign-1'], new Set(['ACCEPTED', 'NOT_ACCEPTED']))?.status).toBe('ACCEPTED');
    expect(latestProposalFor(byLeg['assign-1'], new Set(['ARRIVED']))).toBeNull();
    expect(latestProposalFor(undefined, new Set(['ACCEPTED']))).toBeNull();
  });

  it('restores the proposals of earlier calls from a page of events (INV 13)', () => {
    useCallProposalStore.getState().applyEvents([proposed(3, 'ACCEPTED'), proposed(4, 'RESPONSE_STARTED')]);
    expect(useCallProposalStore.getState().byLeg['assign-1']).toHaveLength(2);
  });
});
