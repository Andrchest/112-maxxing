import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { UsageStatsTab } from './usage-stats-tab';
import { ru } from '@/shared/i18n/ru';
import type { ActivityHeatmap, UsageStats } from '@/shared/api';

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

// I7 E46a, admin item 6: one bucket (Monday, 10:00 UTC).
const ACTIVITY: ActivityHeatmap = {
  cells: [{ weekday: 1, hour: 10, session_count: 4 }],
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
        if (url.startsWith('/api/v1/admin/activity-heatmap')) return jsonResponse(ACTIVITY);
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
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith('/api/v1/admin/usage-stats')) return jsonResponse({ days: [] });
        if (url.startsWith('/api/v1/admin/activity-heatmap')) return jsonResponse({ cells: [] });
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderTab();
    expect(await screen.findByText(ru.adminUsageEmpty)).toBeInTheDocument();
  });

  // I7 E46a (admin item 6): its own card, next to the per-day table above.
  it('renders the activity heatmap next to the usage table, one cell per bucket', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith('/api/v1/admin/usage-stats')) return jsonResponse(STATS);
        if (url.startsWith('/api/v1/admin/activity-heatmap')) return jsonResponse(ACTIVITY);
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderTab();

    expect(await screen.findByRole('heading', { name: ru.adminActivityHeatmapTitle })).toBeInTheDocument();
    // 7 weekdays × 24 hours, always the full grid (a `0` bucket is a real measurement).
    await waitFor(() => expect(document.querySelectorAll('[data-slot="heatmap-cell"]')).toHaveLength(7 * 24));
    const cells = document.querySelectorAll('[data-slot="heatmap-cell"]');
    const populated = Array.from(cells).find((cell) => cell.querySelector('title')?.textContent?.endsWith(': 4'));
    expect(populated).toBeTruthy();
  });

  it('shows the empty message when no session has ever started', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith('/api/v1/admin/usage-stats')) return jsonResponse(STATS);
        if (url.startsWith('/api/v1/admin/activity-heatmap')) return jsonResponse({ cells: [] });
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderTab();
    expect(await screen.findByText(ru.adminActivityHeatmapEmpty)).toBeInTheDocument();
  });
});
