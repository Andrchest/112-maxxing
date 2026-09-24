import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LessonDetailPage } from './lesson-detail-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import type { LessonDetail, LessonReport } from '@/shared/api';

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
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

describe('LessonDetailPage — /instructor/lessons/:lessonId (70 §70.3)', () => {
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
        },
      ],
      weighted_total: 8,
      weighted_max: 10,
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/lessons/lesson-1') return jsonResponse(lesson);
        if (url === '/api/v1/lessons/lesson-1/report') return jsonResponse(report);
        if (url === '/api/v1/scenarios/versions/v1/summary') return jsonResponse(SCENARIO_SUMMARY_RESPONSE);
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderPage();

    expect(await screen.findByText('8 / 10')).toBeInTheDocument();
    expect(screen.getByText(`${ru.lessonDetailWeightedTotalLabel}: 8 / 10`)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: ru.lessonDetailReleaseButton })).toBeInTheDocument();
  });
});
