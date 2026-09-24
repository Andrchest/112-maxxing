import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DdsPhoneWidget } from './phone-widget';
import { useCallProposalStore } from './call-proposals';
import { useWorkItemStore } from '@/entities/work-item';
import { useDdsCallStore } from '@/entities/call';
import { makeDdsCall } from '@/entities/call/test-fixtures';
import { ru } from '@/shared/i18n/ru';
import type { ActionDescriptor } from '@/shared/api';
import { ACTIONS_BY_DDS_STAGE_STATE } from './test-fixtures';

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

const CALL_112: ActionDescriptor = {
  action_id: 'call_112',
  label_ru: ru.ddsPhoneCall112,
  permission: 'PLACE_DDS_CALL',
  trigger: null,
};

describe('The DDS phone - the call to 112 (I3 E6d, 80 par.80.3.4, par.80.5)', () => {
  afterEach(() => {
    useWorkItemStore.getState().reset();
    useDdsCallStore.getState().reset();
    useCallProposalStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('offers the call-112 button from call_112 and the AI operator is the party', async () => {
    const user = userEvent.setup();
    useWorkItemStore.setState({ availableActions: [...ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED, CALL_112] });
    const ringing = makeDdsCall({
      kind: 'OPERATOR_112',
      dialed: '112',
      persona_id: 'OPERATOR_112',
      persona_title_ru: 'Operator 112 persona',
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/dds-calls') && init?.method === 'POST') {
        expect(JSON.parse(String(init.body))).toEqual({ kind: 'OPERATOR_112' });
        return jsonResponse({ call: ringing, voice: null }, 201);
      }
      if (url.includes('/events')) return jsonResponse({ items: [], last_seq_no: 0, has_more: false });
      if (url.endsWith('/dds-calls')) return jsonResponse([]);
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderWidget();
    await user.click(await screen.findByRole('button', { name: ru.ddsPhoneCall112 }));
    expect(await screen.findByText('Operator 112 persona')).toBeInTheDocument();
    expect(screen.getByText(ru.ddsPhoneRinging)).toBeInTheDocument();
    // The line is taken: no second call while this one is live.
    expect(screen.queryByRole('button', { name: ru.ddsPhoneCall112 })).toBeNull();
  });

  it('offers no call to 112 when the stage does not (OFF, or a state that holds no card)', async () => {
    useWorkItemStore.setState({ availableActions: [...ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED] });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/events')) return jsonResponse({ items: [], last_seq_no: 0, has_more: false });
      if (url.endsWith('/dds-calls')) return jsonResponse([]);
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderWidget();
    expect(await screen.findByText(ru.ddsPhoneIdle)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: ru.ddsPhoneCall112 })).toBeNull();
  });
});
