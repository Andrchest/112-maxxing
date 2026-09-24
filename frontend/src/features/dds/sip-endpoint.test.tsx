import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DdsPhoneWidget } from './phone-widget';
import { ServiceLegBlock } from './service-leg-block';
import { useCallProposalStore } from './call-proposals';
import { useWorkItemStore } from '@/entities/work-item';
import { useDdsCallStore } from '@/entities/call';
import { makeDdsCall } from '@/entities/call/test-fixtures';
import { ru } from '@/shared/i18n/ru';
import type { ActionDescriptor } from '@/shared/api';
import { ACTIONS_BY_DDS_STAGE_STATE, makeLeg, makeWorkItem } from './test-fixtures';

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

function stubFetch(calls: unknown[] = []) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/events')) return jsonResponse({ items: [], last_seq_no: 0, has_more: false });
    if (url.endsWith('/dds-calls')) return jsonResponse(calls);
    throw new Error(`unexpected fetch: ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const CALL_CLAIMANT: ActionDescriptor = {
  action_id: 'call_claimant',
  label_ru: 'Call the claimant',
  permission: 'PLACE_DDS_CALL',
  trigger: null,
};

describe('The DDS phone with the SIP endpoint (I3 E6e, 80 par.80.3.5, par.80.3.7)', () => {
  afterEach(() => {
    useWorkItemStore.getState().reset();
    useDdsCallStore.getState().reset();
    useCallProposalStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it("shows each service's dial-plan number on its leg tab, and nothing without one", () => {
    const { rerender } = render(
      <ServiceLegBlock
        sessionId="sess-1"
        leg={makeLeg({ service_name_ru: 'Service 7', phone_extension: '7012' })}
        expanded={false}
        onToggle={() => {}}
        onLegUpdated={() => {}}
      />,
    );
    expect(screen.getByText(`${ru.ddsLegPhoneExtensionPrefix} 7012`)).toBeInTheDocument();
    rerender(
      <ServiceLegBlock
        sessionId="sess-1"
        leg={makeLeg({ service_name_ru: 'Service 7', phone_extension: null })}
        expanded={false}
        onToggle={() => {}}
        onLegUpdated={() => {}}
      />,
    );
    expect(screen.queryByText(new RegExp(`^${ru.ddsLegPhoneExtensionPrefix}`))).toBeNull();
  });

  it("shows the claimant's number from the card beside the call-back button", async () => {
    stubFetch();
    useWorkItemStore.setState({
      availableActions: [...ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED, CALL_CLAIMANT],
      workItem: makeWorkItem({ card_values: { 'caller.phone': '+79161234567' } }),
    });
    renderWidget();
    expect(await screen.findByRole('button', { name: CALL_CLAIMANT.label_ru })).toBeInTheDocument();
    expect(screen.getByText(`${ru.ddsPhoneClaimantNumberLabel} +7 (916) 123-45-67`)).toBeInTheDocument();
  });

  it('falls back to the AON number, and shows none when the card has no number', async () => {
    stubFetch();
    useWorkItemStore.setState({
      availableActions: [...ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED, CALL_CLAIMANT],
      workItem: makeWorkItem({ card_values: { 'caller.phone_aon': '89031112233' } }),
    });
    const { unmount } = renderWidget();
    expect(await screen.findByText(`${ru.ddsPhoneClaimantNumberLabel} +7 (903) 111-22-33`)).toBeInTheDocument();
    unmount();
    useWorkItemStore.setState({ workItem: makeWorkItem({ card_values: {} }) });
    renderWidget();
    expect(await screen.findByRole('button', { name: CALL_CLAIMANT.label_ru })).toBeInTheDocument();
    expect(screen.queryByText(new RegExp(ru.ddsPhoneClaimantNumberLabel))).toBeNull();
  });

  it('a SIP-endpoint call says it is on the softphone and joins no browser media', async () => {
    const fetchMock = stubFetch([makeDdsCall({ endpoint: 'SIP', state: 'CONNECTED', answered_at_offset_ms: 4000 })]);
    useWorkItemStore.setState({ availableActions: [...ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED] });
    renderWidget();
    expect(await screen.findByText(ru.ddsPhoneOnSoftphone)).toBeInTheDocument();
    expect(screen.queryByText(ru.ddsPhoneMediaFailed)).toBeNull();
    const tokenCalls = fetchMock.mock.calls.filter(([input]) => String(input).includes('voice-token'));
    expect(tokenCalls).toEqual([]);
  });
});
