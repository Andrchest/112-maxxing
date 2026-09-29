import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StatisticsPage } from './statistics-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import type { StatisticsCharts, TraineeRating, TraineeStatistics, TypicalErrors } from '@/shared/api';

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

// I7 E54, G11: top failed rules, worst first.
const TYPICAL_ERRORS: TypicalErrors = {
  rows: [
    { rule_id: 'r1', name_ru: 'Rule one', category: 'CARD_QUALITY', failed_session_count: 3, session_count: 4, share_percent: 75 },
  ],
};

// I7 E46a, owner item 6: score timeline + error heatmap, same filters as `STATISTICS`.
const STATISTICS_CHARTS: StatisticsCharts = {
  score_timeline: {
    points: [
      { at: '2026-09-20T10:00:00Z', score_percent: 60 },
      { at: '2026-09-21T10:00:00Z', score_percent: 80 },
    ],
  },
  error_heatmap: {
    categories: ['CARD_QUALITY', 'TIMELINESS'],
    rows: [
      { trainee_user_id: 'trainee-1', display_name_ru: 'Trainee One', cells: [{ category: 'CARD_QUALITY', share_percent: 50 }, { category: 'TIMELINESS', share_percent: null }] },
      { trainee_user_id: 'trainee-2', display_name_ru: 'Trainee Two', cells: [{ category: 'CARD_QUALITY', share_percent: null }, { category: 'TIMELINESS', share_percent: null }] },
    ],
  },
};

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
        if (url === '/api/v1/statistics/typical-errors') return jsonResponse(TYPICAL_ERRORS);
        if (url === '/api/v1/statistics/charts') return jsonResponse(STATISTICS_CHARTS);
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
      if (url.startsWith('/api/v1/statistics/typical-errors')) return jsonResponse(TYPICAL_ERRORS);
      if (url.startsWith('/api/v1/statistics/charts')) return jsonResponse(STATISTICS_CHARTS);
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
      if (url.startsWith('/api/v1/statistics/typical-errors')) return jsonResponse(TYPICAL_ERRORS);
      if (url.startsWith('/api/v1/statistics/charts')) return jsonResponse(STATISTICS_CHARTS);
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

  it('(I7 E46b) downloads statistics and rating as Excel or PDF, next to their CSV buttons', async () => {
    signIn();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/v1/statistics.csv') || url.startsWith('/api/v1/statistics/rating.csv')) {
        const contentType = url.includes('format=pdf')
          ? 'application/pdf'
          : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
        return new Response('x', { status: 200, headers: { 'content-type': contentType } });
      }
      if (url.startsWith('/api/v1/statistics/rating')) return jsonResponse(RATING);
      if (url.startsWith('/api/v1/statistics/typical-errors')) return jsonResponse(TYPICAL_ERRORS);
      if (url.startsWith('/api/v1/statistics/charts')) return jsonResponse(STATISTICS_CHARTS);
      if (url.startsWith('/api/v1/statistics')) return jsonResponse(STATISTICS);
      if (url === '/api/v1/trainee-groups?limit=200') return jsonResponse(GROUPS);
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const original = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
    URL.createObjectURL = vi.fn(() => 'blob:x');
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    try {
      renderPage();
      const user = userEvent.setup();
      const [statsExcel] = await screen.findAllByRole('button', { name: ru.reportDownloadExcel });
      await user.click(statsExcel!);
      await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
      expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/v1/statistics.csv?format=xlsx')).toBe(true);

      const [, ratingPdf] = screen.getAllByRole('button', { name: ru.reportDownloadPdf });
      await user.click(ratingPdf!);
      await waitFor(() => expect(click).toHaveBeenCalledTimes(2));
      expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/v1/statistics/rating.csv?format=pdf')).toBe(true);
    } finally {
      URL.createObjectURL = original.create;
      URL.revokeObjectURL = original.revoke;
      click.mockRestore();
    }
  });

  // I7 E54, G11: its own table, same filters, rendered verbatim in the server's own order.
  it('shows the typical-errors table, its own empty state when there are no rows', async () => {
    signIn();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/statistics') return jsonResponse(STATISTICS);
        if (url === '/api/v1/statistics/rating') return jsonResponse(RATING);
        if (url === '/api/v1/statistics/typical-errors') return jsonResponse(TYPICAL_ERRORS);
        if (url === '/api/v1/statistics/charts') return jsonResponse(STATISTICS_CHARTS);
        if (url === '/api/v1/trainee-groups?limit=200') return jsonResponse(GROUPS);
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );
    renderPage();

    const row = await screen.findByRole('row', { name: /Rule one/ });
    expect(row).toHaveTextContent(ru.scoringCategoryCardQuality);
    expect(row).toHaveTextContent('3 / 4');
    expect(row).toHaveTextContent('75%');
  });

  it('shows the empty state when the scope has no failed rules', async () => {
    signIn();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/statistics') return jsonResponse(STATISTICS);
        if (url === '/api/v1/statistics/rating') return jsonResponse(RATING);
        if (url === '/api/v1/statistics/typical-errors') return jsonResponse({ rows: [] });
        if (url === '/api/v1/statistics/charts') return jsonResponse(STATISTICS_CHARTS);
        if (url === '/api/v1/trainee-groups?limit=200') return jsonResponse(GROUPS);
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );
    renderPage();

    expect(await screen.findByText(ru.typicalErrorsEmpty)).toBeInTheDocument();
  });

  // I7 E46a (owner item 6): the bar chart, the line chart (with its own trainee scope select)
  // and the error heatmap, each in its own card, none touching the E54 table above.
  it('renders the score-distribution bar chart, the score timeline and the error heatmap', async () => {
    signIn();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/statistics') return jsonResponse(STATISTICS);
        if (url === '/api/v1/statistics/rating') return jsonResponse(RATING);
        if (url === '/api/v1/statistics/typical-errors') return jsonResponse(TYPICAL_ERRORS);
        if (url === '/api/v1/statistics/charts') return jsonResponse(STATISTICS_CHARTS);
        if (url === '/api/v1/trainee-groups?limit=200') return jsonResponse(GROUPS);
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );
    renderPage();

    // The bar chart buckets `STATISTICS.rows`' own `average_percent` (72.6 -> the 70-80% bar).
    const barChart = await screen.findByRole('heading', { name: ru.statisticsScoreDistributionTitle });
    expect(barChart).toBeInTheDocument();
    const bars = document.querySelectorAll('[data-slot="bar-chart-bar"]');
    expect(bars.length).toBeGreaterThan(0);

    // The line chart: one point per `score_timeline.points` entry, oldest first.
    expect(screen.getByRole('heading', { name: ru.statisticsAverageByLessonTitle })).toBeInTheDocument();
    await waitFor(() => expect(document.querySelectorAll('[data-slot="line-chart-point"]')).toHaveLength(2));

    // The trainee scope select is populated from the current filter's rows.
    await screen.findByRole('option', { name: 'Trainee One' });

    // The error heatmap: one row per `error_heatmap.rows` entry, a `null` cell renders as
    // «Нет данных», never `0%`.
    expect(screen.getByRole('heading', { name: ru.statisticsErrorHeatmapTitle })).toBeInTheDocument();
    const cells = document.querySelectorAll('[data-slot="heatmap-cell"]');
    expect(cells).toHaveLength(4);
    expect(cells[1]?.querySelector('title')).toHaveTextContent(ru.chartsNoData);
  });
});
