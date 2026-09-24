import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DdsIncidentListPage } from './incident-list-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
}

const INCIDENTS_RESPONSE = {
  items: [
    {
      session_id: 'sess-9',
      incident_id: 'inc-9',
      display_number: 36814845,
      lesson_id: 'lesson-1',
      card_status: 'NOT_NOTIFIED',
      session_state: 'ACTIVE',
      arrived_at_utc: '2026-09-24T11:13:19Z',
      session_offset_ms: 40000,
      accept_deadline_offset_ms: 30000,
      fill_deadline_offset_ms: 180000,
      not_completed_deadline_offset_ms: null,
      classifier_code: '101',
      address_line_ru: 'Test City, Test St, 2',
      my_role_type: 'DDS',
    },
  ],
  total: 1,
};

function renderPage() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DdsIncidentListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('DdsIncidentListPage — the DDS incident list (ui-check D-8)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
  });

  it('requests the incident list filtered to the DDS role and red-flags a NOT_NOTIFIED row', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/v1/incidents')) {
        expect(url).toContain('role_type=DDS');
        return jsonResponse(INCIDENTS_RESPONSE);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    const badge = await screen.findByText(ru.lessonCardStatusNotNotified);
    expect(badge).toHaveAttribute('data-variant', 'destructive');
    const link = screen.getByRole('link', { name: ru.incidentListOpenButton });
    expect(link).toHaveAttribute('href', '/dds/sess-9');
  });

  it('restores the same list after a reload (INV 13, client side)', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/v1/incidents')) {
        return jsonResponse(INCIDENTS_RESPONSE);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    const first = renderPage();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(await screen.findByText(`${ru.incidentListNumberPrefix} 36814845`)).toBeInTheDocument();
    first.unmount();

    renderPage();
    expect(await screen.findByText(`${ru.incidentListNumberPrefix} 36814845`)).toBeInTheDocument();
  });
});
