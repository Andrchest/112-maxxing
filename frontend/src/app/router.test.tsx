import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';
import { AppRoutes } from '@/app/router';
import { useAuthStore, type UserAccount } from '@/entities/session';
import { ru } from '@/shared/i18n/ru';

function renderAt(path: string) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function signIn(userRole: UserAccount['user_role']): void {
  useAuthStore.setState({
    isAuthenticated: true,
    token: 'jwt-token',
    user: {
      id: 'u1',
      username: 'test-user',
      display_name_ru: 'Test User',
      user_role: userRole,
      created_at: '2026-09-21T00:00:00Z',
    },
  });
}

describe('AppRoutes', () => {
  afterEach(() => {
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
    sessionStorage.clear();
  });

  it('renders the login page with its Russian title when signed out', () => {
    renderAt('/login');
    expect(screen.getByRole('heading', { name: ru.loginTitle })).toBeInTheDocument();
  });

  it('redirects / to /login when signed out', () => {
    renderAt('/');
    expect(screen.getByRole('heading', { name: ru.loginTitle })).toBeInTheDocument();
  });

  it('redirects / to /sessions for a signed-in TRAINEE', () => {
    signIn('TRAINEE');
    renderAt('/');
    expect(screen.getByRole('heading', { name: ru.sessionsTitle })).toBeInTheDocument();
  });

  it('redirects / to /instructor for a signed-in INSTRUCTOR', () => {
    signIn('INSTRUCTOR');
    renderAt('/');
    expect(screen.getByRole('heading', { name: ru.instructorTitle })).toBeInTheDocument();
  });

  it('renders a Russian 404 for an unknown path regardless of auth state', () => {
    renderAt('/this-route-does-not-exist');
    expect(screen.getByRole('heading', { name: ru.notFoundTitle })).toBeInTheDocument();
  });

  describe('RequireAuth — signed out', () => {
    it.each(['/operator', '/operator/session-1', '/dds', '/instructor', '/report', '/sessions'])(
      'redirects %s to /login when signed out',
      (path) => {
        renderAt(path);
        expect(screen.getByRole('heading', { name: ru.loginTitle })).toBeInTheDocument();
      },
    );
  });

  describe('RequireRole — TRAINEE routes', () => {
    it('renders the operator placeholder for a signed-in TRAINEE', () => {
      signIn('TRAINEE');
      renderAt('/operator');
      expect(screen.getByRole('heading', { name: ru.operatorTitle })).toBeInTheDocument();
    });

    it('renders the dds placeholder for a signed-in TRAINEE', () => {
      signIn('TRAINEE');
      renderAt('/dds');
      expect(screen.getByRole('heading', { name: ru.ddsTitle })).toBeInTheDocument();
    });

    it('redirects an INSTRUCTOR away from /operator to their own home route', () => {
      signIn('INSTRUCTOR');
      renderAt('/operator');
      expect(screen.getByRole('heading', { name: ru.instructorTitle })).toBeInTheDocument();
    });

    it('renders "my sessions" for a signed-in TRAINEE at /sessions (E8-B)', () => {
      signIn('TRAINEE');
      renderAt('/sessions');
      expect(screen.getByRole('heading', { name: ru.sessionsTitle })).toBeInTheDocument();
    });

    it('renders the operator console for a signed-in TRAINEE at /operator/:sessionId (E8-B)', () => {
      signIn('TRAINEE');
      renderAt('/operator/session-1');
      expect(screen.getByText(ru.operatorConsoleLoading)).toBeInTheDocument();
    });

    it('redirects an INSTRUCTOR away from /operator/:sessionId to their own home route', () => {
      signIn('INSTRUCTOR');
      renderAt('/operator/session-1');
      expect(screen.getByRole('heading', { name: ru.instructorTitle })).toBeInTheDocument();
    });

    it('renders the DDS console for a signed-in TRAINEE at /dds/:sessionId (E10)', () => {
      signIn('TRAINEE');
      renderAt('/dds/session-1');
      expect(screen.getByText(ru.ddsConsoleLoading)).toBeInTheDocument();
    });

    it('redirects an INSTRUCTOR away from /dds/:sessionId to their own home route', () => {
      signIn('INSTRUCTOR');
      renderAt('/dds/session-1');
      expect(screen.getByRole('heading', { name: ru.instructorTitle })).toBeInTheDocument();
    });

    it('renders the session-open resolver for a signed-in TRAINEE at /sessions/:sessionId/open (E10)', () => {
      signIn('TRAINEE');
      renderAt('/sessions/session-1/open');
      expect(screen.getByText(ru.sessionsOpeningConsole)).toBeInTheDocument();
    });
  });

  describe('RequireRole — INSTRUCTOR|ADMIN routes', () => {
    it('renders the instructor placeholder for a signed-in INSTRUCTOR', () => {
      signIn('INSTRUCTOR');
      renderAt('/instructor');
      expect(screen.getByRole('heading', { name: ru.instructorTitle })).toBeInTheDocument();
    });

    it('renders the instructor placeholder for a signed-in ADMIN', () => {
      signIn('ADMIN');
      renderAt('/instructor');
      expect(screen.getByRole('heading', { name: ru.instructorTitle })).toBeInTheDocument();
    });

    it('redirects a TRAINEE away from /instructor to their own home route', () => {
      signIn('TRAINEE');
      renderAt('/instructor');
      expect(screen.getByRole('heading', { name: ru.sessionsTitle })).toBeInTheDocument();
    });
  });

  // -- E16: /report admits all three account roles; the release gate is a backend concern -----
  describe('RequireRole — /report routes (TRAINEE|INSTRUCTOR|ADMIN, E16)', () => {
    it('renders the report index for a signed-in INSTRUCTOR at /report', () => {
      signIn('INSTRUCTOR');
      renderAt('/report');
      expect(screen.getByRole('heading', { name: ru.reportIndexTitle })).toBeInTheDocument();
    });

    it('renders the report index for a signed-in TRAINEE at /report (no longer redirected away)', () => {
      signIn('TRAINEE');
      renderAt('/report');
      expect(screen.getByRole('heading', { name: ru.reportIndexTitle })).toBeInTheDocument();
    });

    it('renders the report page for a signed-in TRAINEE at /report/:sessionId', () => {
      signIn('TRAINEE');
      renderAt('/report/session-1');
      expect(screen.getByRole('heading', { name: ru.reportTitle })).toBeInTheDocument();
    });

    it('renders the report page for a signed-in INSTRUCTOR at /report/:sessionId', () => {
      signIn('INSTRUCTOR');
      renderAt('/report/session-1');
      expect(screen.getByRole('heading', { name: ru.reportTitle })).toBeInTheDocument();
    });
  });

  // -- I4 E33 (71 §71.10): the statistics are the instructor's, the history the trainee's --------
  describe('I4 E33 — /instructor/statistics and /history', () => {
    it('renders the statistics for a signed-in INSTRUCTOR', () => {
      signIn('INSTRUCTOR');
      renderAt('/instructor/statistics');
      expect(screen.getByRole('heading', { name: ru.statisticsPageTitle })).toBeInTheDocument();
    });

    it('sends a TRAINEE away from /instructor/statistics', () => {
      signIn('TRAINEE');
      renderAt('/instructor/statistics');
      expect(screen.getByRole('heading', { name: ru.sessionsTitle })).toBeInTheDocument();
    });

    it('renders the own history for a signed-in TRAINEE at /history', () => {
      signIn('TRAINEE');
      renderAt('/history');
      expect(screen.getByRole('heading', { name: ru.historyPageTitle })).toBeInTheDocument();
    });
  });

  // -- I4 E30 (71 §71.7): /admin is ADMIN only, unlike /instructor above -----------------------
  describe('RequireRole — /admin (ADMIN only)', () => {
    it('renders the admin page for a signed-in ADMIN', () => {
      signIn('ADMIN');
      renderAt('/admin');
      expect(screen.getByRole('heading', { name: ru.adminPageTitle })).toBeInTheDocument();
    });

    it('redirects an INSTRUCTOR away from /admin to their own home route', () => {
      signIn('INSTRUCTOR');
      renderAt('/admin');
      expect(screen.getByRole('heading', { name: ru.instructorTitle })).toBeInTheDocument();
    });

    it('redirects a TRAINEE away from /admin to their own home route', () => {
      signIn('TRAINEE');
      renderAt('/admin');
      expect(screen.getByRole('heading', { name: ru.sessionsTitle })).toBeInTheDocument();
    });

    it('redirects / to /admin for a signed-in ADMIN (homeRouteForRole)', () => {
      signIn('ADMIN');
      renderAt('/');
      expect(screen.getByRole('heading', { name: ru.adminPageTitle })).toBeInTheDocument();
    });
  });
});
