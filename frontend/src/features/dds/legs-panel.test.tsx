import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LegsPanel } from './legs-panel';
import { ru } from '@/shared/i18n/ru';
import { makeLeg } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function renderPanel(sessionId = 'sess-1') {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <LegsPanel sessionId={sessionId} />
    </QueryClientProvider>,
  );
}

describe('LegsPanel — the bottom services tab bar, one tab per notified service (70 par.70.4.3, REQ-5294/5295)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows the empty notice when there are no legs', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([])));
    renderPanel();
    expect(await screen.findByText(ru.ddsLegsEmpty)).toBeInTheDocument();
  });

  // I3 E5c manager review's own vitest: the tab bar shows one tab per leg with its last status.
  it('renders one tab per leg with its last status, every notified service visible regardless of who plays it', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        expect(String(input)).toBe('/api/v1/sessions/sess-1/dds/legs');
        return jsonResponse([
          makeLeg({ assignment_id: 'a1', service_name_ru: 'Fire service', response_status: 'ACCEPTED', is_mine: true }),
          makeLeg({ assignment_id: 'a2', service_name_ru: 'Ambulance service', response_status: 'ADDED', is_mine: false, available_actions: [] }),
        ]);
      }),
    );
    renderPanel();
    const tabs = await screen.findAllByRole('tab');
    expect(tabs).toHaveLength(2);
    expect(screen.getByText('Fire service')).toBeInTheDocument();
    expect(screen.getByText('Ambulance service')).toBeInTheDocument();
    expect(screen.getByText(ru.serviceResponseStatusAccepted)).toBeInTheDocument();
    expect(screen.getByText(ru.serviceResponseStatusAdded)).toBeInTheDocument();
  });

  it('opens exactly one tab at a time, and only the bound (is_mine) leg offers the pencil', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse([
          makeLeg({ assignment_id: 'a1', service_name_ru: 'Fire service', is_mine: true }),
          makeLeg({ assignment_id: 'a2', service_name_ru: 'Ambulance service', is_mine: false, available_actions: [] }),
        ]),
      ),
    );
    renderPanel();
    const tabs = await screen.findAllByRole('tab');

    await user.click(tabs[1]!); // Ambulance — not mine
    expect(screen.queryByRole('button', { name: ru.ddsLegEditButton })).not.toBeInTheDocument();

    await user.click(tabs[0]!); // Fire — mine; opening it closes the ambulance popup
    expect(screen.getByRole('button', { name: ru.ddsLegEditButton })).toBeInTheDocument();
    expect(screen.getAllByRole('tab', { selected: true })).toHaveLength(1);
  });
});
