import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StatisticsPage } from './statistics-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import type { TraineeRating, TraineeStatistics } from '@/shared/api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function signIn(): void {
  useAuthStore.setState({
    token: 'jwt-token',
    isAuthenticated: true,
    user: { id: 'instr-1', username: 'instructor', display_name_ru: 'Instructor', user_role: 'INSTRUCTOR', created_at: '2026-09-21T00:00:00Z' },
  });
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/instructor/statistics']}>
        <StatisticsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const STATISTICS: TraineeStatistics = {
  rows: [
    {
      trainee_user_id: 'trainee-1',
      display_name_ru: 'Trainee One',
      session_count: 4,
      lesson_count: 2,
      average_percent: 72.6,
      failed_rules_by_category: { TIMELINESS: 2, WORKFLOW: 1 },
      accept_deviation_ms_avg: -4_400,
      fill_deviation_ms_avg: 31_000,
      reaction_to_open_ms_avg: 6_000,
      reaction_to_status_ms_avg: 25_000,
      pass_count: 3,
      pass_rate: 75,
    },
    {
      trainee_user_id: 'trainee-2',
      display_name_ru: 'Trainee Two',
      session_count: 0,
      lesson_count: 0,
      average_percent: null,
      failed_rules_by_category: {},
      accept_deviation_ms_avg: null,
      fill_deviation_ms_avg: null,
      reaction_to_open_ms_avg: null,
      reaction_to_status_ms_avg: null,
      pass_count: 0,
      pass_rate: null,
    },
  ],
};

// I5 E36, Q-E12-2: the rating, best trainee first.
const RATING: TraineeRating = {
  rows: [
    { rank: 1, trainee_user_id: 'trainee-1', display_name_ru: 'Trainee One', average_percent: 72.6, pass_count: 3, pass_rate: 75 },
  ],
};

const GROUPS = { items: [{ group_id: 'group-1', name_ru: 'Group A', created_by_user_id: 'instr-1', members: [], created_at: '2026-09-21T00:00:00Z' }], total: 1 };

// I4 E33 (71 §71.10): /instructor/statistics — one row per trainee, a group filter, the CSV.
describe('StatisticsPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.setState({ token: null, isAuthenticated: false, user: null });
  });

  it('shows each trainee row as the server sent it, and nothing where nothing was measured', async () => {
    signIn();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/statistics') return jsonResponse(STATISTICS);
        if (url === '/api/v1/statistics/rating') return jsonResponse(RATING);
        if (url === '/api/v1/trainee-groups?limit=200') return jsonResponse(GROUPS);
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );
    renderPage();

    expect((await screen.findAllByText('Trainee One'))[0]).toBeInTheDocument();
    const [first, second] = screen.getAllByRole('row').filter((row) => row.getAttribute('data-slot') === 'statistics-row');
    expect(first).toHaveTextContent('73%');
    expect(first).toHaveTextContent('−00:04');
    expect(first).toHaveTextContent('+00:31');
    // (I5 E36, Q-E12-1) reaction times are plain durations, no +/− sign.
    expect(first).toHaveTextContent('00:06');
    expect(first).toHaveTextContent('00:25');
    expect(first).toHaveTextContent(`${ru.scoringCategoryTimeliness}: 2`);
    expect(first).toHaveTextContent(`${ru.scoringCategoryWorkflow}: 1`);
    expect(second).toHaveTextContent('Trainee Two');
    expect(second).not.toHaveTextContent('%');
    // (I5 E38, Q-E9b-3) sessions judged passed, and their share.
    expect(first?.querySelector('[data-slot="statistics-passed"]')).toHaveTextContent('3 (75%)');
    expect(second?.querySelector('[data-slot="statistics-passed"]')).toHaveTextContent(`0 (${ru.statisticsNoValue})`);
    // one «Сдано» column in the statistics table and one in the rating table
    expect(screen.getAllByRole('columnheader', { name: ru.statisticsColumnPassed })).toHaveLength(2);

    // (I5 E36, Q-E12-2) the rating table, ranked.
    const [ratingRow] = screen.getAllByRole('row').filter((row) => row.getAttribute('data-slot') === 'statistics-rating-row');
    expect(ratingRow).toHaveTextContent('1');
    expect(ratingRow).toHaveTextContent('Trainee One');
    expect(ratingRow).toHaveTextContent('73%');
    // (I5 E38) the additional column; the order is the server's.
    expect(ratingRow?.querySelector('[data-slot="statistics-rating-passed"]')).toHaveTextContent('3 (75%)');
  });

  it('asks for one group and downloads the same rows as CSV', async () => {
    signIn();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/v1/statistics.csv')) return new Response('x', { status: 200, headers: { 'content-type': 'text/csv' } });
      if (url.startsWith('/api/v1/statistics/rating.csv')) return new Response('x', { status: 200, headers: { 'content-type': 'text/csv' } });
      if (url.startsWith('/api/v1/statistics/rating')) return jsonResponse(RATING);
      if (url.startsWith('/api/v1/statistics')) return jsonResponse(STATISTICS);
      if (url === '/api/v1/trainee-groups?limit=200') return jsonResponse(GROUPS);
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const original = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
    URL.createObjectURL = vi.fn(() => 'blob:statistics');
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    try {
      renderPage();
      const user = userEvent.setup();
      await screen.findByRole('option', { name: 'Group A' });
      await user.selectOptions(screen.getByLabelText(ru.statisticsGroupLabel), 'group-1');
      await waitFor(() =>
        expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/v1/statistics?group_id=group-1')).toBe(true),
      );
      await waitFor(() =>
        expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/v1/statistics/rating?group_id=group-1')).toBe(true),
      );

      const [downloadButton] = screen.getAllByRole('button', { name: ru.lessonReportDownloadCsv });
      await user.click(downloadButton!);
      await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
      expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/v1/statistics.csv?group_id=group-1')).toBe(true);
    } finally {
      URL.createObjectURL = original.create;
      URL.revokeObjectURL = original.revoke;
      click.mockRestore();
    }
  });

  it('downloads the rating as its own CSV', async () => {
    signIn();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/v1/statistics/rating.csv')) return new Response('x', { status: 200, headers: { 'content-type': 'text/csv' } });
      if (url.startsWith('/api/v1/statistics/rating')) return jsonResponse(RATING);
      if (url.startsWith('/api/v1/statistics')) return jsonResponse(STATISTICS);
      if (url === '/api/v1/trainee-groups?limit=200') return jsonResponse(GROUPS);
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const original = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
    URL.createObjectURL = vi.fn(() => 'blob:rating');
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    try {
      renderPage();
      const user = userEvent.setup();
      const [, ratingDownloadButton] = await screen.findAllByRole('button', { name: ru.lessonReportDownloadCsv });
      await user.click(ratingDownloadButton!);
      await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
      expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/v1/statistics/rating.csv')).toBe(true);
    } finally {
      URL.createObjectURL = original.create;
      URL.revokeObjectURL = original.revoke;
      click.mockRestore();
    }
  });
});
