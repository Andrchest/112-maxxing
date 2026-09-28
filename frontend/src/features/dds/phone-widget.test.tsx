import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DdsPhoneWidget } from './phone-widget';
import { useWorkItemStore } from '@/entities/work-item';
import { useDdsCallStore } from '@/entities/call';
import { makeDdsCall } from '@/entities/call/test-fixtures';
import { ru } from '@/shared/i18n/ru';
import type { ActionDescriptor } from '@/shared/api';
import { ACTIONS_BY_DDS_STAGE_STATE } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function renderWidget(sessionId = 'sess-1') {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <DdsPhoneWidget sessionId={sessionId} />
    </QueryClientProvider>,
  );
}

const CALL_CLAIMANT: ActionDescriptor = { action_id: 'call_claimant', label_ru: 'Call the claimant', permission: 'PLACE_DDS_CALL', trigger: null };

describe('DdsPhoneWidget — the DDS phone (I3 E6b, 80 par.80.3, par.80.5)', () => {
  afterEach(() => {
    useWorkItemStore.getState().reset();
    useDdsCallStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('offers the claimant call only when available_actions has call_claimant', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([])));
    useWorkItemStore.setState({ availableActions: ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED });
    renderWidget();
    expect(await screen.findByText(ru.ddsPhoneIdle)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: CALL_CLAIMANT.label_ru })).toBeNull();
  });

  it('places the claimant call, shows it ringing, and hangs up from the call’s own action', async () => {
    const user = userEvent.setup();
    useWorkItemStore.setState({ availableActions: [...ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED, CALL_CLAIMANT] });
    const ringing = makeDdsCall();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/dds-calls') && (init?.method ?? 'GET') === 'GET') return jsonResponse([]);
      if (url.endsWith('/dds-calls') && init?.method === 'POST') {
        expect(JSON.parse(String(init.body))).toEqual({ kind: 'CLAIMANT' });
        return jsonResponse({ call: ringing, voice: null }, 201);
      }
      if (url.endsWith('/dds-calls/call-1/hang-up')) {
        return jsonResponse(makeDdsCall({ state: 'ENDED', end_reason: 'HANGUP', ended_at_offset_ms: 2000, available_actions: [] }));
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderWidget();
    await user.click(await screen.findByRole('button', { name: CALL_CLAIMANT.label_ru }));
    expect(await screen.findByText(ru.ddsPhoneRinging)).toBeInTheDocument();
    expect(screen.getByText(ru.ddsPhonePartyClaimant)).toBeInTheDocument();
    expect(screen.getByText(`${ru.ddsPhoneNumberLabel}: +7 (916) 123-45-67`)).toBeInTheDocument();
    // The line is taken: no second call button while the call is live.
    expect(screen.queryByRole('button', { name: CALL_CLAIMANT.label_ru })).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Hang up' }));
    expect(await screen.findByText(ru.ddsPhoneEnded)).toBeInTheDocument();
    expect(screen.getByText(ru.ddsPhoneEndReasonHangup)).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/sessions/sess-1/dds-calls/call-1/hang-up', expect.anything()));
  });

  it('restores the line from listDdsCalls after a refresh (INV 13)', async () => {
    useWorkItemStore.setState({ availableActions: [...ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED, CALL_CLAIMANT] });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/dds-calls')) return jsonResponse([makeDdsCall({ state: 'ENDED', end_reason: 'BUSY', available_actions: [] })]);
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );
    renderWidget();
    expect(await screen.findByText(ru.ddsPhoneEndReasonBusy)).toBeInTheDocument();
    // An ENDED call frees the line again.
    expect(screen.getByRole('button', { name: CALL_CLAIMANT.label_ru })).toBeInTheDocument();
  });

  it('renders the server’s DDS_LINE_BUSY refusal in Russian', async () => {
    const user = userEvent.setup();
    useWorkItemStore.setState({ availableActions: [...ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED, CALL_CLAIMANT] });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'GET') return jsonResponse([]);
        return new Response(JSON.stringify({ type: 'about:blank', title: 'busy', status: 409, code: 'DDS_LINE_BUSY' }), {
          status: 409,
          headers: { 'content-type': 'application/problem+json' },
        });
      }),
    );
    renderWidget();
    await user.click(await screen.findByRole('button', { name: CALL_CLAIMANT.label_ru }));
    expect(await screen.findByRole('alert')).toHaveTextContent(ru.problemDdsLineBusy);
  });
});

// I6 HTTP: the phone widget switches off at runtime when the page is not a secure context
// (window.isSecureContext false — a plain http origin) — shared/lib/secure-context.ts.
describe('DdsPhoneWidget — insecure context (I6 HTTP)', () => {
  afterEach(() => {
    useWorkItemStore.getState().reset();
    useDdsCallStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('shows only the title and the Russian notice, and offers no call button', async () => {
    vi.stubGlobal('isSecureContext', false);
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([])));
    useWorkItemStore.setState({ availableActions: [...ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED, CALL_CLAIMANT] });

    renderWidget();

    expect(await screen.findByText(ru.secureContextRequiredNotice)).toBeInTheDocument();
    expect(screen.queryByText(ru.ddsPhoneIdle)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: CALL_CLAIMANT.label_ru })).not.toBeInTheDocument();
  });

  it('never joins LiveKit even for a call already CONNECTED (restored from listDdsCalls)', async () => {
    vi.stubGlobal('isSecureContext', false);
    const connected = makeDdsCall({ state: 'CONNECTED', endpoint: 'BROWSER' });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/dds-calls')) return jsonResponse([connected]);
        throw new Error(`unexpected fetch over an insecure context: ${url}`);
      }),
    );
    useWorkItemStore.setState({ availableActions: [] });

    renderWidget();

    expect(await screen.findByText(ru.secureContextRequiredNotice)).toBeInTheDocument();
    // No voice-token mint, no hang-up button — the call state itself is not rendered.
    expect(screen.queryByText(ru.ddsPhoneConnected)).not.toBeInTheDocument();
  });
});
