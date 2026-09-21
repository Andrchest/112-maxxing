import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ReportIndexPage } from './report-index-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function signIn(userRole: 'TRAINEE' | 'INSTRUCTOR' | 'ADMIN'): void {
  useAuthStore.setState({
    isAuthenticated: true,
    token: 'jwt-token',
    user: { id: 'u1', username: 'test-user', display_name_ru: 'Test User', user_role: userRole, created_at: '2026-09-21T00:00:00Z' },
  });
}

function renderPage() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ReportIndexPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ReportIndexPage — a small list into /report/:sessionId', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
  });

  it('lists MINE for a TRAINEE and links each row to /report/:sessionId', async () => {
    signIn('TRAINEE');
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe('/api/v1/sessions?scope=MINE');
      return jsonResponse({
        items: [{ id: 'sess-1', scenario_slug: 'apartment-fire', scenario_version: 1, session_mode: 'SINGLE_ROLE', state: 'COMPLETED', created_at: '2026-09-21T00:00:00Z', created_by_user_id: 'instr-1', my_role_type: 'OPERATOR_112' }],
        total: 1,
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    expect(await screen.findByRole('link', { name: ru.reportIndexOpenButton })).toHaveAttribute('href', '/report/sess-1');
  });

  it('lists ALL for an INSTRUCTOR', async () => {
    signIn('INSTRUCTOR');
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe('/api/v1/sessions?scope=ALL');
      return jsonResponse({ items: [], total: 0 });
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    expect(await screen.findByText(ru.reportIndexEmpty)).toBeInTheDocument();
  });
});
