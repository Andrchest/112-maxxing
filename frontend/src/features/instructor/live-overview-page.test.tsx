import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InstructorLiveOverviewPage } from './live-overview-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import { makeInstructorSessionOverview, makeSessionDetail } from './test-fixtures';
import { makeLeg } from '@/features/dds/test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function problemResponse(code: string, status: number): Response {
  return new Response(JSON.stringify({ title: code, status, code }), { status, headers: { 'content-type': 'application/problem+json' } });
}

class InertSocket {
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  url: string;
  constructor(url: string) {
    this.url = url;
  }
  send(): void {}
  close(): void {
    this.readyState = 3;
  }
}

function signIn(): void {
  useAuthStore.setState({
    token: 'jwt-token',
    isAuthenticated: true,
    user: { id: 'instr-1', username: 'instructor', display_name_ru: 'Instructor', user_role: 'INSTRUCTOR', created_at: '2026-09-21T00:00:00Z' },
  });
}

function renderPage(sessionId = 'sess-1') {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/instructor/sessions/${sessionId}`]}>
        <Routes>
          <Route path="/instructor/sessions/:sessionId" element={<InstructorLiveOverviewPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('InstructorLiveOverviewPage — one getInstructorSessionOverview fetch, refetches on realtime frames', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
  });

  it('renders the loading state before the fetch resolves', () => {
    signIn();
    vi.stubGlobal('WebSocket', InertSocket);
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    renderPage();
    expect(screen.getByText(ru.instructorOverviewLoading)).toBeInTheDocument();
  });

  it('renders every block once the overview loads', async () => {
    signIn();
    vi.stubGlobal('WebSocket', InertSocket);
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(makeInstructorSessionOverview())));
    renderPage();

    expect(await screen.findByText(ru.instructorWorldTruthTitle)).toBeInTheDocument();
    expect(screen.getByText(ru.instructorCallerBeliefTitle)).toBeInTheDocument();
    expect(screen.getByText(ru.instructorGateTurnsTitle)).toBeInTheDocument();
    expect(screen.getByText(ru.instructorOperatorCardTitle)).toBeInTheDocument();
    expect(screen.getByText(ru.reportHandoffTitle)).toBeInTheDocument();
    expect(screen.getByText(ru.instructorDdsWorkItemsTitle)).toBeInTheDocument();
    expect(screen.getByText(ru.instructorCallStateTitle)).toBeInTheDocument();
    expect(screen.getByText(ru.instructorInferenceHealthTitle)).toBeInTheDocument();
  });

  it('renders a Russian 403 message for a non-instructor caller', async () => {
    signIn();
    vi.stubGlobal('WebSocket', InertSocket);
    vi.stubGlobal('fetch', vi.fn(async () => problemResponse('FORBIDDEN_FOR_ROLE', 403)));
    renderPage();
    expect(await screen.findByText(ru.problemForbiddenForRole)).toBeInTheDocument();
  });

  it('links to the report when the session is COMPLETED', async () => {
    signIn();
    vi.stubGlobal('WebSocket', InertSocket);
    const overview = makeInstructorSessionOverview({ session: makeSessionDetail({ state: 'COMPLETED' }) });
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(overview)));
    renderPage();
    const link = await screen.findByRole('link', { name: ru.reportViewReportButton });
    expect(link).toHaveAttribute('href', '/report/sess-1');
  });

  // I6 NAV2 (manager decision, final): a card of a lesson links back into that lesson's own
  // detail page — «Начать занятие» lives there, not on this read-only overview.
  it('links to the lesson when this session is one of its cards', async () => {
    signIn();
    vi.stubGlobal('WebSocket', InertSocket);
    const overview = makeInstructorSessionOverview({ session: makeSessionDetail({ lesson_id: 'lesson-1' }) });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith('/api/v1/lessons/lesson-1')) {
          return jsonResponse({
            lesson_id: 'lesson-1',
            title_ru: 'Fire drill, three cards',
            session_mode: 'SINGLE_ROLE',
            state: 'ACTIVE',
            participants: [],
            scenario_plan: [],
            sessions: [],
            created_at: '2026-09-21T00:00:00Z',
            started_at: null,
            completed_at: null,
            created_by_user_id: 'instr-1',
            report_released_at: null,
          });
        }
        return jsonResponse(overview);
      }),
    );
    renderPage();
    const link = await screen.findByRole('link', { name: /Fire drill, three cards/ });
    expect(link).toHaveAttribute('href', '/instructor/lessons/lesson-1');
  });

  // -- E20-E R11: abortSession client wrapper + the confirm-dialog button ----------------------

  it('shows the abort button for an INSTRUCTOR on a non-terminal session', async () => {
    signIn();
    vi.stubGlobal('WebSocket', InertSocket);
    const overview = makeInstructorSessionOverview({
      session: makeSessionDetail({ state: 'ACTIVE', created_by_user_id: 'instr-1' }),
    });
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(overview)));
    renderPage();
    expect(await screen.findByRole('button', { name: ru.instructorAbortButton })).toBeEnabled();
    expect(screen.queryByText(ru.ownershipHintLesson)).not.toBeInTheDocument();
  });

  it('I5 E39: disables the abort button, with the ownership hint, on another instructor\'s session', async () => {
    signIn();
    vi.stubGlobal('WebSocket', InertSocket);
    const overview = makeInstructorSessionOverview({
      session: makeSessionDetail({ state: 'ACTIVE', created_by_user_id: 'instr-2' }),
    });
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(overview)));
    renderPage();
    expect(await screen.findByRole('button', { name: ru.instructorAbortButton })).toBeDisabled();
    expect(screen.getByText(ru.ownershipHintLesson)).toBeInTheDocument();
  });

  it('hides the abort button once the session is terminal', async () => {
    signIn();
    vi.stubGlobal('WebSocket', InertSocket);
    const overview = makeInstructorSessionOverview({ session: makeSessionDetail({ state: 'COMPLETED' }) });
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(overview)));
    renderPage();
    await screen.findByRole('link', { name: ru.reportViewReportButton });
    expect(screen.queryByRole('button', { name: ru.instructorAbortButton })).not.toBeInTheDocument();
  });

  it('shows the abort button for an ADMIN too', async () => {
    useAuthStore.setState({
      token: 'jwt-token',
      isAuthenticated: true,
      user: { id: 'admin-1', username: 'someone', display_name_ru: 'Someone', user_role: 'ADMIN', created_at: '2026-09-21T00:00:00Z' },
    });
    vi.stubGlobal('WebSocket', InertSocket);
    const overview = makeInstructorSessionOverview({ session: makeSessionDetail({ state: 'ACTIVE' }) });
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(overview)));
    renderPage();
    expect(await screen.findByRole('button', { name: ru.instructorAbortButton })).toBeInTheDocument();
  });

  it('hides the abort button for a role other than INSTRUCTOR/ADMIN', async () => {
    useAuthStore.setState({
      token: 'jwt-token',
      isAuthenticated: true,
      user: { id: 'trainee-1', username: 'someone', display_name_ru: 'Someone', user_role: 'TRAINEE', created_at: '2026-09-21T00:00:00Z' },
    });
    vi.stubGlobal('WebSocket', InertSocket);
    const overview = makeInstructorSessionOverview({ session: makeSessionDetail({ state: 'ACTIVE' }) });
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(overview)));
    renderPage();
    await screen.findByText(ru.instructorWorldTruthTitle);
    expect(screen.queryByRole('button', { name: ru.instructorAbortButton })).not.toBeInTheDocument();
  });

  it('refetches the overview on any realtime event', async () => {
    signIn();
    const sockets: InertSocket[] = [];
    class CapturingSocket extends InertSocket {
      constructor(url: string) {
        super(url);
        sockets.push(this);
      }
    }
    vi.stubGlobal('WebSocket', CapturingSocket);
    let overviewCalls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        overviewCalls += 1;
        return jsonResponse(makeInstructorSessionOverview());
      }),
    );

    renderPage();
    await waitFor(() => expect(overviewCalls).toBe(1));
    await waitFor(() => expect(sockets).toHaveLength(1));
    const socket = sockets[0]!;
    socket.onopen?.();
    socket.onmessage?.({ data: JSON.stringify({ type: 'resume_complete', replayed_count: 0, last_seq_no: 12, live: true }) });

    socket.onmessage?.({
      data: JSON.stringify({
        seq_no: 13,
        type: 'event',
        event_type: 'FACT_GATE_EVALUATED',
        timestamp_utc: '2026-09-21T10:00:05.000Z',
        monotonic_offset_ms: 61000,
        payload: {},
        actor_type: 'SIMULATION',
        correlation_id: null,
        redacted_keys: [],
      }),
    });

    await waitFor(() => expect(overviewCalls).toBeGreaterThan(1));
  });

  // I6 FIX1: each ДДС service's current memo status with its time, following the trainee live.
  it('shows each DDS service\'s memo status with its time and updates it on a realtime frame', async () => {
    signIn();
    const sockets: InertSocket[] = [];
    class CapturingSocket extends InertSocket {
      constructor(url: string) {
        super(url);
        sockets.push(this);
      }
    }
    vi.stubGlobal('WebSocket', CapturingSocket);
    let legsStatus: 'ACCEPTED' | 'COMPLETED' = 'ACCEPTED';
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith('/dds/legs')) {
          return jsonResponse([
            makeLeg({ service_name_ru: 'Fire service', response_status: legsStatus, response_status_at_offset_ms: 65000 }),
          ]);
        }
        return jsonResponse(makeInstructorSessionOverview());
      }),
    );

    renderPage();
    expect(await screen.findByText(ru.instructorDdsLegStatusesTitle)).toBeInTheDocument();
    const row = await screen.findByText('Fire service');
    expect(row.closest('li')).toHaveTextContent(ru.serviceResponseStatusAccepted);
    expect(row.closest('li')).toHaveTextContent('01:05');

    await waitFor(() => expect(sockets).toHaveLength(1));
    const socket = sockets[0]!;
    socket.onopen?.();
    socket.onmessage?.({ data: JSON.stringify({ type: 'resume_complete', replayed_count: 0, last_seq_no: 12, live: true }) });
    legsStatus = 'COMPLETED';
    socket.onmessage?.({
      data: JSON.stringify({
        seq_no: 13,
        type: 'event',
        event_type: 'DDS_SERVICE_STATUS_CHANGED',
        timestamp_utc: '2026-09-21T10:00:05.000Z',
        monotonic_offset_ms: 61000,
        payload: {},
        actor_type: 'TRAINEE',
        correlation_id: null,
        redacted_keys: [],
      }),
    });

    await waitFor(() => expect(screen.getByText('Fire service').closest('li')).toHaveTextContent(ru.serviceResponseStatusCompleted));
  });
});
