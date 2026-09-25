import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { UsageStatsTab } from './usage-stats-tab';
import { ru } from '@/shared/i18n/ru';
import type { UsageStats } from '@/shared/api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function renderTab() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <UsageStatsTab />
    </QueryClientProvider>,
  );
}

const STATS: UsageStats = {
  days: [{ date: '2026-09-24', logins: 7, sessions: 3, lessons: 1, active_users: 5 }],
};

// I4 E30 (71 §71.7): the «Статистика» tab shows E29's per-day usage counts.
describe('UsageStatsTab', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders one row per day from getUsageStats', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith('/api/v1/admin/usage-stats')) return jsonResponse(STATS);
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderTab();

    const row = await screen.findByText('2026-09-24');
    expect(row.closest('tr')).toHaveTextContent('7');
    expect(row.closest('tr')).toHaveTextContent('5');
  });

  it('shows the empty state for no days', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ days: [] })),
    );

    renderTab();
    expect(await screen.findByText(ru.adminUsageEmpty)).toBeInTheDocument();
  });
});
