import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { HistoryPage } from './history-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import { setAuthToken } from '@/shared/lib/api';
import type { MyHistory } from '@/shared/api';

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
}

function renderPage() {
  useAuthStore.setState({
    token: 'jwt-token',
    isAuthenticated: true,
    user: { id: 'trainee-1', username: 'trainee1', display_name_ru: 'Trainee One', user_role: 'TRAINEE', created_at: '2026-09-21T00:00:00Z' },
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/history']}>
        <HistoryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const HISTORY: MyHistory = {
  statistics: {
    trainee_user_id: 'trainee-1',
    display_name_ru: 'Trainee One',
    session_count: 1,
    lesson_count: 1,
    average_percent: 80,
    failed_rules_by_category: { CARD_QUALITY: 2 },
    accept_deviation_ms_avg: 5_000,
    fill_deviation_ms_avg: null,
  },
  sessions: [
    {
      session_id: 'sess-2',
      lesson_id: null,
      scenario_title_ru: 'Gas leak',
      completed_at: '2026-09-25T10:00:00Z',
      score_percent: null,
      failed_rule_count: null,
    },
    {
      session_id: 'sess-1',
      lesson_id: 'lesson-1',
      scenario_title_ru: 'Apartment fire',
      completed_at: '2026-09-24T10:00:00Z',
      score_percent: 80,
      failed_rule_count: 2,
    },
  ],
};

// I4 E33 (71 §71.10): the trainee's /history — own summary and completed sessions.
describe('HistoryPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.setState({ token: null, isAuthenticated: false, user: null });
  });

  it('shows the own summary and each completed session, an unreleased one without its score', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/me/history') return jsonResponse(HISTORY);
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );
    renderPage();

    expect(await screen.findByText('Apartment fire')).toBeInTheDocument();
    expect(document.querySelector('[data-slot="history-average"]')).toHaveTextContent('80%');
    expect(screen.getByText(`${ru.scoringCategoryCardQuality}: 2`)).toBeInTheDocument();
    expect(screen.getByText('+00:05')).toBeInTheDocument();

    const [unreleased, released] = screen.getAllByRole('row').filter((row) => row.getAttribute('data-slot') === 'history-row');
    expect(unreleased).toHaveTextContent('Gas leak');
    expect(unreleased).toHaveTextContent(ru.historyScoreNotReleased);
    expect(released).toHaveTextContent('80%');
    const links = screen.getAllByRole('link', { name: ru.historyOpenReport });
    expect(links.map((link) => link.getAttribute('href'))).toEqual(['/report/sess-2', '/report/sess-1']);
  });

  // I7 E50 (G9, ТЗ ¶265): the four additive `MyHistorySession` columns.
  it('renders the pass/fail result, the two reaction times in seconds and the text-quality count', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/me/history') {
          return jsonResponse({
            ...HISTORY,
            sessions: [
              {
                ...HISTORY.sessions[1],
                passed: true,
                reaction_open_ms: 12_400,
                reaction_first_status_ms: 45_000,
                text_quality_issue_count: 3,
              },
              {
                ...HISTORY.sessions[0],
                passed: null,
                reaction_open_ms: null,
                reaction_first_status_ms: null,
                text_quality_issue_count: null,
              },
            ],
          });
        }
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );
    renderPage();

    await screen.findByText('Apartment fire');
    const rows = screen.getAllByRole('row').filter((row) => row.getAttribute('data-slot') === 'history-row');
    const [scored, unscored] = rows;
    if (!scored || !unscored) throw new Error('expected two history rows');
    expect(scored).toHaveTextContent(ru.historyResultPassed);
    expect(scored).toHaveTextContent('12'); // 12_400ms rounds to 12s
    expect(scored).toHaveTextContent('45');
    expect(scored).toHaveTextContent('3');
    // the not-yet-visible session shows a dash for every one of the four additive columns.
    expect(unscored.querySelectorAll('td')).not.toHaveLength(0);
    expect(unscored.textContent?.match(new RegExp(ru.statisticsNoValue, 'g'))?.length).toBeGreaterThanOrEqual(4);
  });

  it('says so when there is no completed session yet', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ ...HISTORY, sessions: [], statistics: { ...HISTORY.statistics, session_count: 0 } })),
    );
    renderPage();
    expect(await screen.findByText(ru.historyEmpty)).toBeInTheDocument();
  });

  // I7 E54 (G10): a released session with failed rules hints at the report's recommendations;
  // an unreleased one (no score yet) never does, even with a `failed_rule_count`.
  it('hints at recommendations only for a released session with failed rules', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(HISTORY)));
    renderPage();

    await screen.findByText('Apartment fire');
    const rows = screen.getAllByRole('row').filter((row) => row.getAttribute('data-slot') === 'history-row');
    const [unreleased, released] = rows;
    if (!unreleased || !released) throw new Error('expected two history rows');
    expect(released).toHaveTextContent(ru.historyRecommendationsHint);
    expect(unreleased).not.toHaveTextContent(ru.historyRecommendationsHint);
  });

  // I7 E46a (owner item 6): its own line chart of `score_percent` over `sessions`, oldest first
  // (the table is newest first), the not-yet-released session (`score_percent: null`) dropped.
  it('renders the score-over-sessions line chart, oldest first, dropping an unreleased score', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(HISTORY)));
    renderPage();

    await screen.findByText('Apartment fire');
    expect(screen.getByRole('heading', { name: ru.historyScoreChartTitle })).toBeInTheDocument();
    const points = document.querySelectorAll('[data-slot="line-chart-point"]');
    // HISTORY has two sessions, newest first; only "sess-1" (Apartment fire) has a score.
    expect(points).toHaveLength(1);
    expect(points[0]?.querySelector('title')).toHaveTextContent('80%');
  });

  // I5 E37 (Q-E16-4): «Скачать профиль (JSON)» downloads the caller's own profile.
  it('downloads the own profile as JSON with the bearer token', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/v1/me/history') return jsonResponse(HISTORY);
      if (url === '/api/v1/users/trainee-1/profile-export') {
        return new Response('{"id":"trainee-1"}', { status: 200, headers: { 'content-type': 'application/json' } });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const original = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
    const createObjectURL = vi.fn(() => 'blob:profile');
    const revokeObjectURL = vi.fn();
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    setAuthToken('jwt-token');

    try {
      renderPage();
      await screen.findByText('Apartment fire');
      await userEvent.setup().click(screen.getByRole('button', { name: ru.historyDownloadProfileButton }));

      await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
      const [, init] = fetchMock.mock.calls.find(([requestInput]) => String(requestInput) === '/api/v1/users/trainee-1/profile-export') as unknown as [
        string,
        RequestInit,
      ];
      expect((init.headers as Record<string, string>).Authorization).toBe('Bearer jwt-token');
      // I7 E46c: the object URL is now revoked after a delay (S12.04/S13.28 fix), not
      // synchronously after the click — covered by `shared/lib/download.test.ts`.
      expect(revokeObjectURL).not.toHaveBeenCalled();
    } finally {
      URL.createObjectURL = original.create;
      URL.revokeObjectURL = original.revoke;
      click.mockRestore();
      setAuthToken(null);
    }
  });
});
