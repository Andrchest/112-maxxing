import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LessonBoardPage } from './lesson-board-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';

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

function renderPage(lessonId = 'lesson-1') {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/instructor/board/${lessonId}`]}>
        <Routes>
          <Route path="/instructor/board/:lessonId" element={<LessonBoardPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const LESSON_DETAIL = {
  lesson_id: 'lesson-1',
  title_ru: 'Lesson one',
  session_mode: 'MULTI_TRAINEE',
  state: 'ACTIVE',
  participants: [{ user_id: 'trainee-1', assigned_role_type: 'OPERATOR_112' }],
  scenario_plan: [],
  sessions: [
    { position: 1, session_id: 'sess-1', incident_id: 'inc-1', display_number: 1, state: 'ACTIVE', card_status: 'IN_PROGRESS', arrival: { kind: 'AT_OFFSET', delay_ms: 0, offset_ms: 0 }, variants: { card_source: 'GENERATED_CARD', dds_mode: 'RESOURCE_PICKER', dds_card_check: 'OFF', dds_brigade_call: 'OFF' } },
    { position: 2, session_id: 'sess-2', incident_id: 'inc-2', display_number: 2, state: 'READY', card_status: 'REGISTERED', arrival: { kind: 'AT_OFFSET', delay_ms: 0, offset_ms: 60000 }, variants: { card_source: 'GENERATED_CARD', dds_mode: 'RESOURCE_PICKER', dds_card_check: 'OFF', dds_brigade_call: 'OFF' } },
  ],
  created_at: '2026-09-25T00:00:00Z',
  started_at: '2026-09-25T00:00:00Z',
  completed_at: null,
  report_released_at: null,
  group_id: null,
};

const USERS_RESPONSE = {
  items: [{ id: 'trainee-1', username: 'trainee1', display_name_ru: 'Trainee One', user_role: 'TRAINEE', created_at: '2026-09-21T00:00:00Z' }],
  total: 1,
};

// I4 E32 (HLD 71 §71.9): the all-trainees board (ТЗ ¶224, ¶235).
describe('LessonBoardPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
  });

  it('lists every card of the lesson with its state and card status', async () => {
    signIn();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith('/users?limit=200') || String(input).includes('/users')) return jsonResponse(USERS_RESPONSE);
        return jsonResponse(LESSON_DETAIL);
      }),
    );
    renderPage();

    expect(await screen.findByText(/Lesson one/)).toBeInTheDocument();
    // Every card of the lesson (position 1 AND 2) is present, each with its own state.
    expect(screen.getByText('ACTIVE')).toBeInTheDocument();
    expect(screen.getByText('READY')).toBeInTheDocument();
    expect(screen.getByText('IN_PROGRESS')).toBeInTheDocument();
    expect(screen.getByText('REGISTERED')).toBeInTheDocument();
    expect(screen.getAllByText('Trainee One')).toHaveLength(2);
  });

  it('shows the empty state for a lesson with no cards', async () => {
    signIn();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes('/users')) return jsonResponse(USERS_RESPONSE);
        return jsonResponse({ ...LESSON_DETAIL, sessions: [] });
      }),
    );
    renderPage();
    expect(await screen.findByText(ru.instructorBoardEmpty)).toBeInTheDocument();
  });
});
