import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RegisterPage } from './register-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
}

const INCIDENTS_RESPONSE = {
  items: [
    {
      session_id: 'sess-1',
      incident_id: 'inc-1',
      display_number: 36814851,
      lesson_id: 'lesson-1',
      card_status: 'REGISTERED',
      session_state: 'ACTIVE',
      arrived_at_utc: '2026-09-24T11:13:19Z',
      session_offset_ms: 1000,
      accept_deadline_offset_ms: 30000,
      fill_deadline_offset_ms: 180000,
      not_completed_deadline_offset_ms: null,
      classifier_code: '101',
      address_line_ru: 'Test City, Test St, 1',
      my_role_type: 'OPERATOR_112',
    },
  ],
  total: 1,
};

function renderPage() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('RegisterPage — the 112 register (ui-check D-2)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
  });

  it('requests the incident list filtered to the OPERATOR_112 role and renders the row', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/v1/incidents')) {
        expect(url).toContain('role_type=OPERATOR_112');
        return jsonResponse(INCIDENTS_RESPONSE);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    expect(await screen.findByText(`${ru.incidentListNumberPrefix} 36814851`)).toBeInTheDocument();
    // (I7 E50) the «Статус» filter's <option>s repeat the same Russian labels, so the query is
    // scoped to the status badge itself — never an ambiguous plain-text match.
    expect(
      screen.getByText(ru.lessonCardStatusRegistered, { selector: '[data-slot="card-status-badge"]' }),
    ).toBeInTheDocument();
    const link = screen.getByRole('link', { name: ru.incidentListOpenButton });
    expect(link).toHaveAttribute('href', '/operator/sess-1');
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
    expect(await screen.findByText(`${ru.incidentListNumberPrefix} 36814851`)).toBeInTheDocument();
    first.unmount();

    // A "reload" is a fresh mount with a fresh query client, fetching the list from the server
    // again rather than reading anything the client cached client-side (INV 13's own client-side
    // requirement: the list is restored, not lost).
    renderPage();
    expect(await screen.findByText(`${ru.incidentListNumberPrefix} 36814851`)).toBeInTheDocument();
  });
});
