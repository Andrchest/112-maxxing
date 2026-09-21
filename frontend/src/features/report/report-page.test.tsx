import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ReportPage } from './report-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import { makeSessionReport } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function problemResponse(code: string, status: number): Response {
  return new Response(JSON.stringify({ title: code, status, code }), { status, headers: { 'content-type': 'application/problem+json' } });
}

/** Routes every `fetch` call this page's tree can make while a report is mounted:
 * `getSessionReport`, `TimingMetricsSection`'s own `listInferenceMetrics`, and (when
 * `explanationAvailable`) `getReportExplanation` — a blanket "return the report for everything"
 * mock would hand `TimingMetricsSection` a `SessionReport` body where it expects an
 * `InferenceMetricsPage`, crashing that subtree. */
function mockReportFetch(report: ReturnType<typeof makeSessionReport>): (input: RequestInfo | URL) => Promise<Response> {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/inference-metrics')) {
      return jsonResponse({ items: [], total: 0, timing_metrics: report.timing_metrics });
    }
    if (url.includes('/explanation')) {
      return new Response(JSON.stringify({ title: 'Not Found', status: 404, code: 'NOT_FOUND' }), {
        status: 404,
        headers: { 'content-type': 'application/problem+json' },
      });
    }
    return jsonResponse(report);
  });
}

function signIn(userRole: 'TRAINEE' | 'INSTRUCTOR' | 'ADMIN'): void {
  useAuthStore.setState({
    isAuthenticated: true,
    token: 'jwt-token',
    user: { id: 'u1', username: 'test-user', display_name_ru: 'Test User', user_role: userRole, created_at: '2026-09-21T00:00:00Z' },
  });
}

function renderPage(sessionId = 'sess-1') {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/report/${sessionId}`]}>
        <Routes>
          <Route path="/report/:sessionId" element={<ReportPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ReportPage — orchestrates one getSessionReport fetch, one component per §29 item', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
  });

  it('renders the loading state before the fetch resolves', () => {
    signIn('INSTRUCTOR');
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    renderPage();
    expect(screen.getByText(ru.reportLoading)).toBeInTheDocument();
  });

  it('renders the totals once the report loads', async () => {
    signIn('INSTRUCTOR');
    const report = makeSessionReport({ score_report: { ...makeSessionReport().score_report, total_points: 30, total_max_points: 50 } });
    vi.stubGlobal('fetch', mockReportFetch(report));
    renderPage();
    expect(await screen.findByText('30 / 50')).toBeInTheDocument();
  });

  it('renders the not-released in-page state on 403 REPORT_NOT_RELEASED', async () => {
    signIn('TRAINEE');
    vi.stubGlobal('fetch', vi.fn(async () => problemResponse('REPORT_NOT_RELEASED', 403)));
    renderPage();
    expect(await screen.findByText(ru.reportNotReleasedTitle)).toBeInTheDocument();
  });

  it('renders the not-ready in-page state on 409 REPORT_NOT_READY', async () => {
    signIn('INSTRUCTOR');
    vi.stubGlobal('fetch', vi.fn(async () => problemResponse('REPORT_NOT_READY', 409)));
    renderPage();
    expect(await screen.findByText(ru.reportNotReadyTitle)).toBeInTheDocument();
  });

  it('renders the 404 state', async () => {
    signIn('INSTRUCTOR');
    vi.stubGlobal('fetch', vi.fn(async () => problemResponse('NOT_FOUND', 404)));
    renderPage();
    expect(await screen.findByText(ru.notFoundTitle)).toBeInTheDocument();
  });

  it('shows the release button for INSTRUCTOR and calls releaseReportToTrainee on click', async () => {
    signIn('INSTRUCTOR');
    const report = makeSessionReport();
    const baseFetch = mockReportFetch(report);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') {
        expect(String(input)).toBe('/api/v1/instructor/sessions/sess-1/report/release');
        return jsonResponse({ session_id: 'sess-1', released: true, released_at: '2026-09-21T01:00:00Z', released_by_user_id: 'u1' });
      }
      return baseFetch(input);
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    renderPage();
    await screen.findByRole('button', { name: ru.reportReleaseButton });
    await user.click(screen.getByRole('button', { name: ru.reportReleaseButton }));

    // The trailing colon narrows the match to the released-at paragraph — the release button's
    // own label starts with the same word (reportReleaseButton) and would otherwise also match.
    await waitFor(() => expect(screen.getByText(new RegExp(`${ru.reportReleasedAtLabel}:`))).toBeInTheDocument());
  });

  it('does not show the release button for a TRAINEE', async () => {
    signIn('TRAINEE');
    vi.stubGlobal('fetch', mockReportFetch(makeSessionReport()));
    renderPage();
    await screen.findByText(ru.reportTotalsTitle);
    expect(screen.queryByRole('button', { name: ru.reportReleaseButton })).not.toBeInTheDocument();
  });
});
