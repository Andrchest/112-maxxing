import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LoginPage } from './login-page';
import { useAuthStore } from '@/entities/session';
import { ru } from '@/shared/i18n/ru';

function renderLoginPage() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          {/* I6 NAV2: an INSTRUCTOR's home route is now `/instructor/lessons` (`homeRouteForRole`). */}
          <Route path="/instructor/lessons" element={<div>instructor-home</div>} />
          <Route path="/operator" element={<div>operator-home</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('LoginPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
    sessionStorage.clear();
  });

  it('signs in and redirects to the role home route on success', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            access_token: 'jwt-token',
            token_type: 'bearer',
            expires_in: 3600,
            user: {
              id: 'u1',
              username: 'instr',
              display_name_ru: 'Test Instructor',
              user_role: 'INSTRUCTOR',
              created_at: '2026-09-21T00:00:00Z',
            },
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
    );
    vi.stubGlobal('fetch', fetchMock);

    renderLoginPage();
    await user.type(screen.getByLabelText(ru.loginUsernameLabel), 'instr');
    await user.type(screen.getByLabelText(ru.loginPasswordLabel), 'secret');
    await user.click(screen.getByRole('button', { name: ru.loginSubmit }));

    await waitFor(() => expect(screen.getByText('instructor-home')).toBeInTheDocument());
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
    expect(useAuthStore.getState().token).toBe('jwt-token');

    const [firstCallUrl] = fetchMock.mock.calls[0] as unknown as [string];
    expect(firstCallUrl).toBe('/api/v1/auth/login');
  });

  it('shows the Russian message for the problem code on failure and does not sign in', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ title: 'Unauthorized', status: 401, code: 'UNAUTHENTICATED' }), {
          status: 401,
          headers: { 'content-type': 'application/problem+json' },
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    renderLoginPage();
    await user.type(screen.getByLabelText(ru.loginUsernameLabel), 'instr');
    await user.type(screen.getByLabelText(ru.loginPasswordLabel), 'wrong');
    await user.click(screen.getByRole('button', { name: ru.loginSubmit }));

    expect(await screen.findByRole('alert')).toHaveTextContent(ru.problemUnauthenticated);
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });
});
