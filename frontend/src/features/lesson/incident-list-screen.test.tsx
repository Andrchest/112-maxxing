// I7 E50 (G2/G3): the list used to load once and never refresh. These tests pin the three pieces
// this epic added — the 3 s poll while the tab is visible, the auto-refresh switch turning it
// off, and the status select sending `card_status` — over the real `IncidentListScreen`, a fetch
// mock standing in for the server. Fake timers govern `refetchInterval`, so every wait is a manual
// `flush()` (advance-by-0 to drain the mocked fetch's promise chain) rather than
// `@testing-library`'s `waitFor`, which polls with its own (also faked) timer and would deadlock.
import { act, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IncidentListScreen } from './incident-list-screen';
import { ru } from '@/shared/i18n/ru';

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
}

const EMPTY_RESPONSE = { items: [], total: 0 };

async function flush(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

function renderScreen() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <IncidentListScreen roleType="DDS" consoleBasePath="/dds" searchInputId="dds-incident-search" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('IncidentListScreen — live refresh and the status filter (I7 E50 G2/G3)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    try {
      window.localStorage.clear();
    } catch {
      // ignore — some environments block storage entirely
    }
  });

  it('polls every 3 s while auto-refresh stays checked', async () => {
    const fetchMock = vi.fn(async () => jsonResponse(EMPTY_RESPONSE));
    vi.stubGlobal('fetch', fetchMock);

    renderScreen();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it('stops polling once auto-refresh is unchecked', async () => {
    const fetchMock = vi.fn(async () => jsonResponse(EMPTY_RESPONSE));
    vi.stubGlobal('fetch', fetchMock);

    renderScreen();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const toggle = screen.getByLabelText(ru.incidentListAutoRefreshLabel);
    fireEvent.click(toggle);
    expect(toggle).not.toBeChecked();

    const callsAfterToggle = fetchMock.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(fetchMock.mock.calls.length).toBe(callsAfterToggle);
  });

  it('defaults auto-refresh on, and remembers an off choice across a remount (localStorage)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(EMPTY_RESPONSE)));
    const first = renderScreen();
    await flush();
    expect(screen.getByLabelText(ru.incidentListAutoRefreshLabel)).toBeChecked();
    fireEvent.click(screen.getByLabelText(ru.incidentListAutoRefreshLabel));
    first.unmount();

    renderScreen();
    await flush();
    expect(screen.getByLabelText(ru.incidentListAutoRefreshLabel)).not.toBeChecked();
  });

  it('sends the selected status as card_status on the next request', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      expect(url).toContain('role_type=DDS');
      return jsonResponse(EMPTY_RESPONSE);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderScreen();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).not.toContain('card_status');

    fireEvent.change(screen.getByLabelText(ru.incidentListStatusFilterLabel), {
      target: { value: 'NOT_NOTIFIED' },
    });
    await flush();

    const last = fetchMock.mock.calls.at(-1)?.[0];
    expect(String(last)).toContain('card_status=NOT_NOTIFIED');
  });
});
