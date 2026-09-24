import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DdsPhoneWidget } from './phone-widget';
import { ServiceLegBlock } from './service-leg-block';
import { useCallProposalStore } from './call-proposals';
import { useWorkItemStore } from '@/entities/work-item';
import { useDdsCallStore } from '@/entities/call';
import { makeDdsCall } from '@/entities/call/test-fixtures';
import { ru } from '@/shared/i18n/ru';
import type { ActionDescriptor } from '@/shared/api';
import { ACTIONS_BY_DDS_STAGE_STATE, makeLeg } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function renderWidget() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <DdsPhoneWidget sessionId="sess-1" />
    </QueryClientProvider>,
  );
}

const CALL_SERVICE_HEAD: ActionDescriptor = {
  action_id: 'call_service_head',
  label_ru: 'Call the head',
  permission: 'PLACE_DDS_CALL',
  trigger: null,
};

describe('The DDS phone - the service head (I3 E6c, 80 par.80.3.3, par.80.4, par.80.5)', () => {
  afterEach(() => {
    useWorkItemStore.getState().reset();
    useDdsCallStore.getState().reset();
    useCallProposalStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('offers call_service_head once per leg the trainee plays and calls that leg', async () => {
    const user = userEvent.setup();
    useWorkItemStore.setState({ availableActions: [...ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED, CALL_SERVICE_HEAD] });
    const head = makeDdsCall({
      kind: 'SERVICE_HEAD',
      assignment_id: 'assign-1',
      service_type: 'FIRE_RESCUE',
      dialed: '101',
      persona_id: 'BRIGADE_101',
      persona_title_ru: 'Fire watch commander',
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/dds/legs')) {
        return jsonResponse([
          makeLeg(),
          makeLeg({ assignment_id: 'assign-2', service_name_ru: 'Traffic centre', is_mine: false, available_actions: [] }),
        ]);
      }
      if (url.endsWith('/dds-calls') && init?.method === 'POST') {
        expect(JSON.parse(String(init.body))).toEqual({ kind: 'SERVICE_HEAD', assignment_id: 'assign-1' });
        return jsonResponse({ call: head, voice: null }, 201);
      }
      if (url.includes('/events')) return jsonResponse({ items: [], last_seq_no: 0, has_more: false });
      if (url.endsWith('/dds-calls')) return jsonResponse([]);
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderWidget();
    const button = await screen.findByRole('button', { name: `${CALL_SERVICE_HEAD.label_ru} · ${makeLeg().service_name_ru}` });
    expect(screen.queryByRole('button', { name: /Traffic centre/ })).toBeNull();
    await user.click(button);
    expect(await screen.findByText('Fire watch commander')).toBeInTheDocument();
    expect(screen.getByText(ru.ddsPhoneRinging)).toBeInTheDocument();
    // The line is taken: no second call while this one is live.
    expect(screen.queryByRole('button', { name: /Call the head/ })).toBeNull();
  });

  it('shows a ringing INBOUND call as incoming and answers it from the call own action', async () => {
    const user = userEvent.setup();
    const ringing = makeDdsCall({
      kind: 'SERVICE_HEAD',
      direction: 'INBOUND',
      persona_title_ru: 'Fire watch commander',
      available_actions: [
        { action_id: 'answer', label_ru: 'Answer', permission: 'PLACE_DDS_CALL', trigger: 'answer' },
        { action_id: 'hang_up', label_ru: 'Hang up', permission: 'PLACE_DDS_CALL', trigger: 'hang_up' },
      ],
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/dds-calls/call-1/answer') && init?.method === 'POST') {
        return jsonResponse({
          call: { ...ringing, state: 'CONNECTED', answered_by: 'TRAINEE', available_actions: [ringing.available_actions[1]] },
          voice: null,
        });
      }
      if (url.includes('/events')) return jsonResponse({ items: [], last_seq_no: 0, has_more: false });
      if (url.endsWith('/dds-calls')) return jsonResponse([ringing]);
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderWidget();
    expect(await screen.findByText(ru.ddsPhoneIncoming)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Answer' }));
    expect(await screen.findByText(ru.ddsPhoneConnected)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Answer' })).toBeNull();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/sessions/sess-1/dds-calls/call-1/answer', expect.anything()));
  });

  it('offers a heard status on the pencil form and confirms it with proposed_by_call_id', async () => {
    const user = userEvent.setup();
    useCallProposalStore.getState().applyEvents([
      {
        seq_no: 7,
        event_type: 'DDS_CALL_STATUS_PROPOSED',
        timestamp_utc: '2026-09-24T10:00:00Z',
        monotonic_offset_ms: 7000,
        payload: {
          call_id: 'call-9',
          assignment_id: 'assign-1',
          service_type: 'FIRE_RESCUE',
          status: 'ACCEPTED',
          order_number: '2415',
          comment_ru: null,
          script_after_ms: 15000,
          due_offset_ms: 20000,
          at_offset_ms: 7000,
        },
      },
    ]);
    const onLegUpdated = vi.fn();
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toEqual({
        status: 'ACCEPTED',
        order_number: '2415',
        comment_ru: null,
        proposed_by_call_id: 'call-9',
      });
      return jsonResponse(makeLeg({ response_status: 'ACCEPTED' }));
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<ServiceLegBlock sessionId="sess-1" leg={makeLeg()} expanded={true} onToggle={() => {}} onLegUpdated={onLegUpdated} />);
    expect(screen.getByText(new RegExp(ru.ddsLegProposalChip))).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: ru.ddsLegProposalApply }));
    expect(screen.getByText(ru.ddsLegProposalFromCall)).toBeInTheDocument();
    expect((screen.getByLabelText(ru.ddsLegOrderNumberLabel) as HTMLInputElement).value).toBe('2415');
    await user.click(screen.getByRole('button', { name: ru.ddsLegFormConfirmButton }));
    await waitFor(() => expect(onLegUpdated).toHaveBeenCalledTimes(1));
  });

  it('never offers a heard status the leg cannot take next', () => {
    useCallProposalStore.getState().applyEvents([
      {
        seq_no: 7,
        event_type: 'DDS_CALL_STATUS_PROPOSED',
        timestamp_utc: '2026-09-24T10:00:00Z',
        monotonic_offset_ms: 7000,
        payload: { call_id: 'call-9', assignment_id: 'assign-1', status: 'ARRIVED', order_number: null, comment_ru: null, due_offset_ms: 1 },
      },
    ]);
    render(<ServiceLegBlock sessionId="sess-1" leg={makeLeg()} expanded={true} onToggle={() => {}} onLegUpdated={() => {}} />);
    expect(screen.queryByText(new RegExp(ru.ddsLegProposalChip))).toBeNull();
  });
});
