import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LessonsPage } from './lessons-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
}

function stubEverythingBut(lessonsResponse: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/v1/lessons')) return jsonResponse(lessonsResponse);
      if (url === '/api/v1/scenarios') return jsonResponse({ items: [], total: 0 });
      if (url === '/api/v1/scenarios?limit=200') return jsonResponse({ items: [], total: 0 });
      if (url === '/api/v1/trainee-groups?limit=200') return jsonResponse({ items: [], total: 0 });
      if (url === '/api/v1/users?role=TRAINEE') return jsonResponse({ items: [], total: 0 });
      throw new Error(`unexpected fetch: ${url}`);
    }),
  );
}

function renderPage() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <LessonsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('LessonsPage — /instructor/lessons (70 §70.3)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
  });

  it('shows the empty state with no lessons', async () => {
    stubEverythingBut({ items: [], total: 0 });
    renderPage();
    expect(await screen.findByText(ru.lessonsListEmpty)).toBeInTheDocument();
  });

  it('lists a lesson with its Russian state label and links into its detail page', async () => {
    stubEverythingBut({
      items: [
        {
          lesson_id: 'lesson-1',
          title_ru: 'Fire drill, three cards',
          session_mode: 'SINGLE_ROLE',
          state: 'ACTIVE',
          card_count: 3,
          created_at: '2026-09-24T00:00:00Z',
          created_by_user_id: 'instr-1',
        },
      ],
      total: 1,
    });
    renderPage();

    expect(await screen.findByText('Fire drill, three cards')).toBeInTheDocument();
    expect(screen.getByText(ru.lessonStateActive, { exact: false })).toBeInTheDocument();
    const link = screen.getByRole('link', { name: ru.lessonsListOpenButton });
    expect(link).toHaveAttribute('href', '/instructor/lessons/lesson-1');
  });
});
