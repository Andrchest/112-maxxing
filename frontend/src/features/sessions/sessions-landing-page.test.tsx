import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SessionsLandingPage } from './sessions-landing-page';
import { ru } from '@/shared/i18n/ru';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function renderPage() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SessionsLandingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('SessionsLandingPage — lists only what listSessions returned', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders exactly the sessions the backend returned, and only those', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe('/api/v1/sessions?scope=MINE');
      return jsonResponse({
        items: [
          {
            id: 'sess-1',
            scenario_slug: 'apartment-fire',
            scenario_version: 1,
            session_mode: 'SINGLE_ROLE',
            state: 'ACTIVE',
            created_at: '2026-09-21T00:00:00Z',
            created_by_user_id: 'instr-1',
            my_role_type: 'OPERATOR_112',
          },
          {
            id: 'sess-2',
            scenario_slug: 'gas-leak',
            scenario_version: 2,
            session_mode: 'MULTI_TRAINEE',
            state: 'READY',
            created_at: '2026-09-21T00:00:00Z',
            created_by_user_id: 'instr-1',
            my_role_type: null,
          },
        ],
        total: 2,
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    expect(await screen.findByText(/apartment-fire/)).toBeInTheDocument();
    expect(screen.getByText(/gas-leak/)).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    // Only sess-1 has an OPERATOR_112 assignment, so only it gets an "open console" link.
    expect(screen.getByRole('link', { name: ru.sessionsOpenButton })).toHaveAttribute('href', '/operator/sess-1');
  });

  it('routes a FULL_CYCLE_SINGLE_TRAINEE participant (my_role_type null) through the resolver (E10)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          items: [
            {
              id: 'sess-3',
              scenario_slug: 'apartment-fire',
              scenario_version: 1,
              session_mode: 'FULL_CYCLE_SINGLE_TRAINEE',
              state: 'ACTIVE',
              created_at: '2026-09-21T00:00:00Z',
              created_by_user_id: 'instr-1',
              my_role_type: null,
            },
          ],
          total: 1,
        }),
      ),
    );

    renderPage();

    expect(await screen.findByRole('link', { name: ru.sessionsOpenButton })).toHaveAttribute('href', '/sessions/sess-3/open');
  });

  it('shows "no console yet" for a true observer (my_role_type null, not FULL_CYCLE_SINGLE_TRAINEE)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          items: [
            {
              id: 'sess-4',
              scenario_slug: 'apartment-fire',
              scenario_version: 1,
              session_mode: 'MULTI_TRAINEE',
              state: 'ACTIVE',
              created_at: '2026-09-21T00:00:00Z',
              created_by_user_id: 'instr-1',
              my_role_type: null,
            },
          ],
          total: 1,
        }),
      ),
    );

    renderPage();

    expect(await screen.findByText(ru.sessionsNoConsoleYet)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: ru.sessionsOpenButton })).not.toBeInTheDocument();
  });

  it('renders the empty state when listSessions returns no items', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    expect(await screen.findByText(ru.sessionsEmpty)).toBeInTheDocument();
    expect(screen.queryAllByRole('listitem')).toHaveLength(0);
  });

  // I3 E4b (manager follow-up): both trainee-side nav links live on this TRAINEE-only home page —
  // a trainee's role is per-session (D6), so neither link is gated on which role a past/future
  // session assigned.
  it('links to the 112 register (/operator/register)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], total: 0 })));
    renderPage();
    const link = await screen.findByRole('link', { name: ru.navRegisterLink });
    expect(link).toHaveAttribute('href', '/operator/register');
  });

  it('links to the DDS incident list (/dds/incidents)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], total: 0 })));
    renderPage();
    const link = await screen.findByRole('link', { name: ru.navIncidentListLink });
    expect(link).toHaveAttribute('href', '/dds/incidents');
  });
});
