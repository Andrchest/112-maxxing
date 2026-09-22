import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi, afterEach } from 'vitest';
import { InstructorSessionsList } from './instructor-sessions-list';
import { ru } from '@/shared/i18n/ru';

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
}

function renderList() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <InstructorSessionsList />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('InstructorSessionsList — links into the live overview and, for terminal sessions, the report', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the empty state when there are no sessions', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], total: 0 })));
    renderList();
    expect(await screen.findByText(ru.instructorSessionsListEmpty)).toBeInTheDocument();
  });

  it('links an ACTIVE session only to the live overview', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          items: [{ id: 'sess-1', scenario_slug: 'apartment-fire', scenario_version: 1, session_mode: 'SINGLE_ROLE', state: 'ACTIVE', created_at: '2026-09-21T00:00:00Z', created_by_user_id: 'u1', my_role_type: null }],
          total: 1,
        }),
      ),
    );
    renderList();
    const overviewLink = await screen.findByRole('link', { name: ru.instructorSessionsListOverviewButton });
    expect(overviewLink).toHaveAttribute('href', '/instructor/sessions/sess-1');
    expect(screen.queryByRole('link', { name: ru.reportIndexOpenButton })).not.toBeInTheDocument();
  });

  it('additionally links a COMPLETED session to its report', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          items: [{ id: 'sess-2', scenario_slug: 'apartment-fire', scenario_version: 1, session_mode: 'SINGLE_ROLE', state: 'COMPLETED', created_at: '2026-09-21T00:00:00Z', created_by_user_id: 'u1', my_role_type: null }],
          total: 1,
        }),
      ),
    );
    renderList();
    const reportLink = await screen.findByRole('link', { name: ru.reportIndexOpenButton });
    expect(reportLink).toHaveAttribute('href', '/report/sess-2');
  });
});
