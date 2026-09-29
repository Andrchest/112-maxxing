import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LessonDetailPage } from './lesson-detail-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import type { LessonDetail, LessonReport } from '@/shared/api';

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
}

function notFound(): Response {
  return new Response(JSON.stringify({ title: 'Not Found', status: 404, code: 'NOT_FOUND' }), {
    status: 404,
    headers: { 'content-type': 'application/problem+json' },
  });
}

const SCENARIO_SUMMARY_RESPONSE = {
  id: 'v1',
  scenario_id: 's1',
  scenario_slug: 'apartment-fire',
  version: 1,
  title: 'Apartment fire drill',
  description: 'test',
  difficulty: 3,
  role_chain: ['OPERATOR_112', 'DDS'],
  caller_display_ru: 'Neighbour',
  caller_language: 'ru-RU',
  caller_age_group: 'ADULT',
  caller_relationship: 'NEIGHBOR',
  estimated_duration_seconds: 600,
  resource_count: 3,
  variants: {
    supported: {
      card_source: ['CALLER_VOICE'],
      dds_mode: ['RESOURCE_PICKER'],
      dds_card_check: ['OFF'],
      dds_brigade_call: ['OFF'],
    },
    default: { card_source: 'CALLER_VOICE', dds_mode: 'RESOURCE_PICKER', dds_card_check: 'OFF', dds_brigade_call: 'OFF' },
  },
};

function makeLesson(overrides: Partial<LessonDetail>): LessonDetail {
  return {
    lesson_id: 'lesson-1',
    title_ru: 'Fire drill, three cards',
    session_mode: 'SINGLE_ROLE',
    state: 'CREATED',
    participants: [{ user_id: 'trainee-1', assigned_role_type: 'DDS' }],
    scenario_plan: [
      { position: 1, scenario_version_id: 'v1', arrival: { kind: 'AT_OFFSET', offset_ms: 60000, delay_ms: 0 }, weight: 1 },
    ],
    sessions: [
      {
        position: 1,
        session_id: 'sess-1',
        incident_id: 'inc-1',
        display_number: 36814851,
        state: 'READY',
        card_status: 'NOT_NOTIFIED',
        arrival: { kind: 'AT_OFFSET', offset_ms: 0, delay_ms: 0 },
        started_at_lesson_offset_ms: null,
        variants: { card_source: 'GENERATED_CARD', dds_mode: 'RESOURCE_PICKER', dds_card_check: 'OFF', dds_brigade_call: 'OFF' },
      },
    ],
    created_at: '2026-09-24T00:00:00Z',
    started_at: null,
    completed_at: null,
    report_released_at: null,
    group_id: null,
    created_by_user_id: 'instructor-1',
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/instructor/lessons/lesson-1']}>
        <Routes>
          <Route path="/instructor/lessons/:lessonId" element={<LessonDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** I5 E39: the signed-in account; `instructor-1` is `makeLesson`'s owner. */
function signIn(id: string, userRole: 'INSTRUCTOR' | 'ADMIN' = 'INSTRUCTOR'): void {
  useAuthStore.setState({
    isAuthenticated: true,
    token: 'jwt-token',
    user: { id, username: id, display_name_ru: 'Instructor', user_role: userRole, created_at: '2026-09-21T00:00:00Z' },
  });
}

describe('LessonDetailPage — /instructor/lessons/:lessonId (70 §70.3)', () => {
  beforeEach(() => signIn('instructor-1'));

  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
  });

  it('renders the card_status badge verbatim, red-flagging NOT_NOTIFIED, and starts a CREATED lesson', async () => {
    const user = userEvent.setup();
    const lesson = makeLesson({});
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/lessons/lesson-1' && method === 'GET') return jsonResponse(lesson);
      if (url === '/api/v1/lessons/lesson-1/start' && method === 'POST') return jsonResponse(makeLesson({ state: 'ACTIVE' }));
      if (url === '/api/v1/scenarios/versions/v1/summary' && method === 'GET') return jsonResponse(SCENARIO_SUMMARY_RESPONSE);
      if (url === '/api/v1/users?role=TRAINEE') return jsonResponse({ items: [], total: 0 });
      if (url === '/api/v1/lessons/lesson-1/weight-proposals') return notFound();
      throw new Error(`unexpected fetch: ${method} ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    const badge = await screen.findByText(ru.lessonCardStatusNotNotified);
    expect(badge).toHaveAttribute('data-variant', 'destructive');

    // Manager follow-up on E4b-shots/04: mm:ss (E0's `formatCallDurationMs`), never raw ms; the
    // scenario's Russian title on both the plan entry and the card row, not just a position; no
    // connection indicator on a page with no socket.
    expect(await screen.findAllByText('Apartment fire drill')).toHaveLength(2);
    expect(screen.getByText('01:00', { exact: false })).toBeInTheDocument();
    expect(screen.queryByText(/60000/)).not.toBeInTheDocument();
    expect(document.querySelector('[data-slot="connection-indicator"]')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: ru.lessonDetailStartButton }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/v1/lessons/lesson-1/start' && (init as RequestInit | undefined)?.method === 'POST')).toBe(true),
    );
  });

  it('shows the N card reports and the weighted total once the lesson is COMPLETED', async () => {
    const lesson = makeLesson({ state: 'COMPLETED', completed_at: '2026-09-24T01:00:00Z' });
    const report: LessonReport = {
      lesson_id: 'lesson-1',
      cards: [
        {
          position: 1,
          session_id: 'sess-1',
          weight: 1,
          score: {
            scenario_version_id: 'v1',
            session_id: 'sess-1',
            total_points: 8,
            total_max_points: 10,
            by_category: [],
            critical_errors: [],
            results: [],
            computed_from_event_count: 12,
            checksum: 'abc',
          },
          unscored: null,
        },
      ],
      weighted_total: 8,
      weighted_max: 10,
      // I7 E54, G11: the lesson's own «Типичные ошибки» table.
      typical_errors: {
        rows: [
          { rule_id: 'r1', name_ru: 'Rule one', category: 'CARD_QUALITY', failed_session_count: 1, session_count: 1, share_percent: 100 },
        ],
      },
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/lessons/lesson-1') return jsonResponse(lesson);
        if (url === '/api/v1/lessons/lesson-1/report') return jsonResponse(report);
        if (url === '/api/v1/scenarios/versions/v1/summary') return jsonResponse(SCENARIO_SUMMARY_RESPONSE);
        if (url === '/api/v1/users?role=TRAINEE') return jsonResponse({ items: [], total: 0 });
        if (url === '/api/v1/lessons/lesson-1/weight-proposals') return notFound();
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderPage();

    expect(await screen.findByText('8 / 10')).toBeInTheDocument();
    expect(screen.getByText(`${ru.lessonDetailWeightedTotalLabel}: 8 / 10`)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: ru.lessonDetailReleaseButton })).toBeInTheDocument();
    // I7 E54, G11: the lesson's own «Типичные ошибки» table.
    expect(screen.getByText('Rule one')).toBeInTheDocument();
    expect(screen.getByText(ru.scoringCategoryCardQuality)).toBeInTheDocument();
  });

  it('lists a card aborted by an early end unscored, with its time at work and its actions (I4 E31)', async () => {
    const user = userEvent.setup();
    const lesson = makeLesson({ state: 'ABORTED', completed_at: '2026-09-24T01:00:00Z' });
    const report: LessonReport = {
      lesson_id: 'lesson-1',
      cards: [
        {
          position: 1,
          session_id: 'sess-1',
          weight: 2,
          score: null,
          unscored: {
            state: 'ABORTED',
            timeline: [
              {
                seq_no: 1,
                event_type: 'SESSION_STARTED',
                monotonic_offset_ms: 0,
                timestamp_utc: '2026-09-24T00:00:00Z',
                actor_type: 'INSTRUCTOR',
                actor_id: null,
                summary_ru: 'Session started',
                payload: {},
              },
              {
                seq_no: 2,
                event_type: 'SESSION_ABORTED',
                monotonic_offset_ms: 75_000,
                timestamp_utc: '2026-09-24T00:01:15Z',
                actor_type: 'INSTRUCTOR',
                actor_id: null,
                summary_ru: 'Session aborted',
                payload: {},
              },
            ],
            times: { started_at: '2026-09-24T00:00:00Z', aborted_at: '2026-09-24T00:01:15Z', elapsed_ms: 75_000 },
          },
        },
        {
          position: 2,
          session_id: 'sess-2',
          weight: 1,
          score: null,
          unscored: { state: 'ABORTED', timeline: [], times: { started_at: null, aborted_at: '2026-09-24T00:01:15Z', elapsed_ms: null } },
        },
      ],
      weighted_total: 0,
      weighted_max: 0,
      typical_errors: { rows: [] },
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/lessons/lesson-1') return jsonResponse(lesson);
        if (url === '/api/v1/lessons/lesson-1/report') return jsonResponse(report);
        if (url === '/api/v1/scenarios/versions/v1/summary') return jsonResponse(SCENARIO_SUMMARY_RESPONSE);
        if (url === '/api/v1/users?role=TRAINEE') return jsonResponse({ items: [], total: 0 });
        if (url === '/api/v1/lessons/lesson-1/weight-proposals') return notFound();
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderPage();

    expect(await screen.findAllByText(ru.lessonReportCardUnscored)).toHaveLength(2);
    expect(screen.getByText(`${ru.lessonReportCardElapsedLabel} 01:15`)).toBeInTheDocument();
    expect(screen.getByText(ru.lessonReportCardNotStarted)).toBeInTheDocument();
    expect(screen.getByText(`${ru.lessonDetailWeightedTotalLabel}: 0 / 0`)).toBeInTheDocument();
    await user.click(screen.getByText(`${ru.lessonReportCardActionsLabel} (2)`));
    expect(screen.getByText('Session aborted')).toBeInTheDocument();
  });
  it('asks for AI weight proposals, changes nothing until the instructor accepts the ticked ones', async () => {
    const user = userEvent.setup();
    const lesson = makeLesson({
      group_id: 'group-1',
      scenario_plan: [
        { position: 1, scenario_version_id: 'v1', arrival: { kind: 'AT_OFFSET', offset_ms: 0, delay_ms: 0 }, weight: 1, participants: ['trainee-1'] },
        { position: 2, scenario_version_id: 'v1', arrival: { kind: 'AT_OFFSET', offset_ms: 0, delay_ms: 0 }, weight: 1 },
        { position: 3, scenario_version_id: 'v1', arrival: { kind: 'AT_OFFSET', offset_ms: 0, delay_ms: 0 }, weight: 1 },
      ],
    });
    const proposals = {
      lesson_id: 'lesson-1',
      source: 'HEURISTIC',
      model_name: null,
      fallback_reason: 'LLM_UNAVAILABLE',
      requested_at: '2026-09-24T00:00:00Z',
      requested_by_user_id: 'instr-1',
      proposals: [1, 2, 3].map((position) => ({
        position,
        scenario_version_id: 'v1',
        current_weight: 1,
        proposed_weight: 5 + position,
        reason_ru: `reason ${position}`,
        accepted_at: null,
      })),
    };
    const accepted = {
      ...proposals,
      proposals: proposals.proposals.map((line) =>
        line.position === 2 ? line : { ...line, current_weight: line.proposed_weight, accepted_at: '2026-09-24T00:01:00Z' },
      ),
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/lessons/lesson-1' && method === 'GET') return jsonResponse(lesson);
      if (url === '/api/v1/scenarios/versions/v1/summary') return jsonResponse(SCENARIO_SUMMARY_RESPONSE);
      if (url === '/api/v1/users?role=TRAINEE')
        return jsonResponse({ items: [{ id: 'trainee-1', username: 't1', display_name_ru: 'Trainee One', user_role: 'TRAINEE', created_at: '2026-09-21T00:00:00Z' }], total: 1 });
      if (url === '/api/v1/trainee-groups?limit=200')
        return jsonResponse({ items: [{ group_id: 'group-1', name_ru: 'Shift A', created_by_user_id: 'instr-1', created_at: '2026-09-21T00:00:00Z', members: [] }], total: 1 });
      if (url === '/api/v1/lessons/lesson-1/weight-proposals' && method === 'GET') return notFound();
      if (url === '/api/v1/lessons/lesson-1/weight-proposals' && method === 'POST') return jsonResponse(proposals);
      if (url === '/api/v1/lessons/lesson-1/weight-proposals/accept' && method === 'POST') return jsonResponse(accepted);
      throw new Error(`unexpected fetch: ${method} ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    expect(await screen.findByText(ru.weightProposalsEmpty)).toBeInTheDocument();
    expect(await screen.findByText(`${ru.lessonDetailGroupLabel}: Shift A`)).toBeInTheDocument();
    expect((await screen.findAllByText(`${ru.difficultyLabel} 3`)).length).toBeGreaterThan(0);
    expect(await screen.findByText(`${ru.lessonDetailParticipantsLabel}: Trainee One`)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: ru.weightProposalsRequestButton }));
    expect(await screen.findByText('reason 1')).toBeInTheDocument();
    expect(
      screen.getByText(
        `${ru.weightProposalsSourceHeuristic} — ${ru.weightProposalsFallbackPrefix}: ${ru.weightProposalsFallbackLlmUnavailable}`,
      ),
    ).toBeInTheDocument();
    const acceptButton = screen.getByRole('button', { name: ru.weightProposalsAcceptButton });
    expect(acceptButton).toBeDisabled();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/accept'))).toBe(false);

    await user.click(screen.getByLabelText(`${ru.weightProposalsColumnAccept} 1`));
    await user.click(screen.getByLabelText(`${ru.weightProposalsColumnAccept} 3`));
    await user.click(acceptButton);

    const acceptCall = await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/weight-proposals/accept'));
      expect(call).toBeDefined();
      return call as [string, RequestInit];
    });
    expect(JSON.parse(acceptCall[1].body as string)).toEqual({ positions: [1, 3] });
    expect(await screen.findAllByText(ru.weightProposalsAccepted)).toHaveLength(2);
  });
  it('I5 E39: another instructor sees the lesson, but its controls are disabled with the ownership hint', async () => {
    signIn('instructor-2');
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/lessons/lesson-1' && method === 'GET') return jsonResponse(makeLesson({}));
      if (url === '/api/v1/scenarios/versions/v1/summary' && method === 'GET') return jsonResponse(SCENARIO_SUMMARY_RESPONSE);
      if (url === '/api/v1/users?role=TRAINEE') return jsonResponse({ items: [], total: 0 });
      if (url === '/api/v1/lessons/lesson-1/weight-proposals') return notFound();
      throw new Error(`unexpected fetch: ${method} ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    expect(await screen.findByRole('button', { name: ru.lessonDetailStartButton })).toBeDisabled();
    expect(screen.getByRole('button', { name: ru.lessonDetailAbortButton })).toBeDisabled();
    expect(screen.getByRole('button', { name: ru.weightProposalsRequestButton })).toBeDisabled();
    expect(screen.getAllByText(ru.ownershipHintLesson).length).toBeGreaterThan(0);
  });

  it('I5 E39: an ADMIN changes any lesson', async () => {
    signIn('admin-1', 'ADMIN');
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/lessons/lesson-1') return jsonResponse(makeLesson({}));
        if (url === '/api/v1/scenarios/versions/v1/summary') return jsonResponse(SCENARIO_SUMMARY_RESPONSE);
        if (url === '/api/v1/users?role=TRAINEE') return jsonResponse({ items: [], total: 0 });
        if (url === '/api/v1/lessons/lesson-1/weight-proposals') return notFound();
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderPage();

    expect(await screen.findByRole('button', { name: ru.lessonDetailStartButton })).toBeEnabled();
    expect(screen.queryByText(ru.ownershipHintLesson)).not.toBeInTheDocument();
  });
});
