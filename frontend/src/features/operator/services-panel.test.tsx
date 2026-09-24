import { render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ServicesPanel } from './services-panel';
import { latestResolution } from './latest-resolution';
import { ru } from '@/shared/i18n/ru';
import { useCardStore } from '@/entities/card';
import { useSessionEventsStore } from '@/entities/session';
import { useStageStore } from '@/entities/stage';
import { makeCard } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

const CATALOG = [
  { id: 'FIRE_RESCUE', name_ru: 'Service 101', full_name_ru: 'Service 101 (fire)' },
  { id: 'POLICE', name_ru: 'Service 102', full_name_ru: 'Service 102 (police)' },
  { id: 'MOSLIFT', name_ru: 'Moslift', full_name_ru: 'Moslift lifts' },
].map((entry) => ({
  ...entry,
  kind: 'CITY',
  code: null,
  okrug: null,
  district: null,
  classifier_org_id: null,
  classifier_org_ids: [],
  status_policy: 'DEFAULT',
  display: true,
  deprecated: false,
  phone: null,
}));

function resolved(seqNo: number, auto: string[], informed: string[] = []) {
  return {
    seq_no: seqNo,
    event_type: 'RECIPIENTS_RESOLVED' as const,
    timestamp_utc: '2026-09-24T10:00:00.000Z',
    monotonic_offset_ms: 1000 + seqNo,
    payload: { auto_services: auto, informed_services: informed },
  };
}

function seed(cardSchema: 'v1' | 'v2', manual: string[] = []): void {
  useCardStore.getState().setCard(makeCard({ card_schema: cardSchema, values: { 'recipients.services': manual } }));
  useStageStore.setState({
    availableActions: [{ action_id: 'select_services', label_ru: 'Select services', permission: 'SELECT_SERVICES', trigger: null }],
  });
  useSessionEventsStore.getState().reset('sess-1', 0);
}

interface Routes {
  history?: unknown[];
  onCommand?: (url: string, body: unknown) => Response;
}

function stubFetch({ history = [], onCommand }: Routes = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.startsWith('/api/v1/sessions/sess-1/events')) {
      expect(url).toContain('event_type=RECIPIENTS_RESOLVED');
      return jsonResponse({ items: history, last_seq_no: 0, has_more: false });
    }
    if (url.startsWith('/api/v1/reference/services')) {
      return jsonResponse(CATALOG);
    }
    if (onCommand) {
      return onCommand(url, init?.body ? JSON.parse(init.body as string) : undefined);
    }
    throw new Error(`unexpected fetch ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ServicesPanel sessionId="sess-1" />
    </QueryClientProvider>,
  );
}

function selection(manual: string[], card: ReturnType<typeof makeCard>) {
  return {
    card_id: 'card-1',
    selected_services: manual,
    available_services: CATALOG.map((entry) => entry.id),
    card,
    auto_services: [],
    informed_services: [],
    notification_list: manual,
    classifier_code: null,
    candidate_codes: [],
    removal_allowed: card.card_schema === 'v1',
  };
}

describe('ServicesPanel — the notification list and the catalog picker (I3 E2b′)', () => {
  afterEach(() => {
    useCardStore.getState().setCard(null);
    useStageStore.getState().reset();
    useSessionEventsStore.getState().reset('sess-1', 0);
    vi.unstubAllGlobals();
  });

  it('marks the latest resolution as auto and recipients.services as manual, with no remove control under v2', async () => {
    seed('v2', ['MOSLIFT']);
    stubFetch({ history: [resolved(3, ['POLICE']), resolved(7, ['FIRE_RESCUE'], ['FSO'])] });

    renderPanel();

    const list = await screen.findByRole('list', { name: ru.operatorServicesTitle });
    await waitFor(() => expect(within(list).getAllByRole('listitem')).toHaveLength(2));
    const [first, second] = within(list).getAllByRole('listitem');
    expect(first).toHaveTextContent(ru.operatorServicesAuto);
    expect(second).toHaveTextContent(ru.operatorServicesManual);
    expect(screen.queryByRole('button', { name: new RegExp(ru.operatorServicesRemove) })).not.toBeInTheDocument();
  });

  it('follows a live RECIPIENTS_RESOLVED over the history', async () => {
    seed('v2');
    stubFetch({ history: [resolved(3, ['POLICE'])] });
    useSessionEventsStore.getState().applyEvent(resolved(9, ['MOSLIFT']));

    renderPanel();

    const list = await screen.findByRole('list', { name: ru.operatorServicesTitle });
    await waitFor(() => expect(within(list).getAllByRole('listitem')).toHaveLength(1));
    expect(within(list).getByRole('listitem')).toHaveTextContent(ru.operatorServicesAuto);
  });

  it('adds a service through the picker with search', async () => {
    const user = userEvent.setup();
    seed('v2');
    const fetchMock = stubFetch({
      onCommand: (url, body) => {
        expect(url).toBe('/api/v1/sessions/sess-1/operator/services/select');
        expect(body).toEqual({ service_type: 'MOSLIFT' });
        return jsonResponse(selection(['MOSLIFT'], makeCard({ card_schema: 'v2', values: { 'recipients.services': ['MOSLIFT'] } })));
      },
    });

    renderPanel();
    await user.click(screen.getByRole('button', { name: ru.operatorServicesAdd }));
    expect(await screen.findByText(ru.operatorServicesPickerDescription)).toBeInTheDocument();
    const search = screen.getByLabelText(ru.operatorServicesSearchLabel);
    await user.type(search, 'MOSL');
    const picker = await screen.findByRole('list', { name: ru.operatorServicesPickerTitle });
    await waitFor(() => expect(within(picker).getAllByRole('button')).toHaveLength(1));
    await user.click(within(picker).getByRole('button', { name: 'Moslift' }));

    await waitFor(() => expect(useCardStore.getState().card?.values['recipients.services']).toEqual(['MOSLIFT']));
    expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith('/api/v1/reference/services'))).toBe(true);
  });

  it('keeps the remove control for a manual service under v1', async () => {
    const user = userEvent.setup();
    seed('v1', ['POLICE']);
    stubFetch({
      onCommand: (url, body) => {
        expect(url).toBe('/api/v1/sessions/sess-1/operator/services/deselect');
        expect(body).toEqual({ service_type: 'POLICE' });
        return jsonResponse(selection([], makeCard({ card_schema: 'v1', values: { 'recipients.services': [] } })));
      },
    });

    renderPanel();
    await user.click(await screen.findByRole('button', { name: new RegExp(ru.operatorServicesRemove) }));

    await waitFor(() => expect(screen.getByText(ru.operatorServicesEmpty)).toBeInTheDocument());
  });

  it('shows the server problem message, e.g. SERVICE_REMOVAL_FORBIDDEN', async () => {
    const user = userEvent.setup();
    seed('v1', ['POLICE']);
    stubFetch({
      onCommand: () =>
        new Response(JSON.stringify({ code: 'SERVICE_REMOVAL_FORBIDDEN', title: 'x', status: 409 }), {
          status: 409,
          headers: { 'content-type': 'application/problem+json' },
        }),
    });

    renderPanel();
    await user.click(await screen.findByRole('button', { name: new RegExp(ru.operatorServicesRemove) }));

    expect(await screen.findByRole('alert')).toHaveTextContent(ru.problemServiceRemovalForbidden);
  });

  it('disables adding when the server does not offer select_services', () => {
    useCardStore.getState().setCard(makeCard({ card_schema: 'v2', values: {} }));
    useStageStore.setState({ availableActions: [] });
    stubFetch();

    renderPanel();
    expect(screen.getByRole('button', { name: ru.operatorServicesAdd })).toBeDisabled();
  });
});

describe('latestResolution', () => {
  it('takes the highest seq_no whatever the order', () => {
    expect(latestResolution([resolved(9, ['A']), resolved(2, ['B'])])?.auto).toEqual(['A']);
    expect(latestResolution([])).toBeNull();
  });
});
