// I3 E4b (manager follow-up): the instructor reaches «Занятия» from their own home page.
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InstructorPage } from './instructor-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
}

function renderPage() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <InstructorPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('InstructorPage — the lessons nav link (INSTRUCTOR/ADMIN only route)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
  });

  it('renders a link to /instructor/lessons, reachable only from this INSTRUCTOR/ADMIN-gated page', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/health/ready') {
          return jsonResponse({
            overall: 'NOT_READY',
            components: [],
            required_components: [],
            require_inference_ready: false,
            model_profile: 'DEV_3060TI',
          });
        }
        if (url === '/api/v1/scenarios') return jsonResponse({ items: [], total: 0 });
        if (url === '/api/v1/users?role=TRAINEE') return jsonResponse({ items: [], total: 0 });
        if (url === '/api/v1/sessions?scope=ALL') return jsonResponse({ items: [], total: 0 });
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderPage();

    const link = await screen.findByRole('link', { name: ru.navLessonsLink });
    expect(link).toHaveAttribute('href', '/instructor/lessons');
  });
});
