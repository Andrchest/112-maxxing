import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AdminPage } from './admin-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function signIn(): void {
  useAuthStore.setState({
    token: 'jwt-token',
    isAuthenticated: true,
    user: { id: 'admin-1', username: 'admin', display_name_ru: 'Admin', user_role: 'ADMIN', created_at: '2026-09-21T00:00:00Z' },
  });
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/admin']}>
        <AdminPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// I4 E30 (71 §71.7): one vitest per admin tab — Пользователи / Журнал / Статистика / Нагрузка /
// Ошибки / Оповещения all switch in from the same page and each shows its own server data.
describe('AdminPage — the six tabs', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.setState({ token: null, isAuthenticated: false, user: null });
  });

  it('shows the users tab by default, and every other tab on click', async () => {
    signIn();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/admin/alerts') return jsonResponse({ items: [] });
        if (url === '/api/v1/users') return jsonResponse({ items: [], total: 0 });
        if (url.startsWith('/api/v1/admin/audit-log')) return jsonResponse({ items: [], total: 0 });
        if (url.startsWith('/api/v1/admin/usage-stats')) return jsonResponse({ days: [] });
        if (url === '/api/v1/admin/server-load') {
          return jsonResponse({
            sampled_at: '2026-09-25T06:00:00Z',
            cpu_percent: null,
            memory_used_mb: null,
            memory_total_mb: null,
            disk_used_gb: null,
            disk_total_gb: null,
            gpu_memory_used_mb: null,
            gpu_memory_total_mb: null,
          });
        }
        if (url.startsWith('/api/v1/admin/errors')) return jsonResponse({ items: [] });
        if (url === '/api/v1/admin/backup-status') return jsonResponse({ available: false, finished_at: null, status: null, database_bytes: null, recordings_bytes: null, database_sha256: null, recordings_sha256: null });
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderPage();
    const user = userEvent.setup();

    expect(screen.getByRole('heading', { name: ru.adminPageTitle })).toBeInTheDocument();
    expect(await screen.findByText(ru.adminUsersEmpty)).toBeInTheDocument();
    // Header badge (no alerts) — proves the app-shell slot from I4 E30 is wired.
    expect(await screen.findByText(ru.adminAlertsBadgeNone)).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: ru.adminTabAuditLog }));
    expect(await screen.findByText(ru.adminAuditEmpty)).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: ru.adminTabUsageStats }));
    expect(await screen.findByText(ru.adminUsageEmpty)).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: ru.adminTabServerLoad }));
    expect((await screen.findAllByText(ru.adminNoData)).length).toBeGreaterThan(0);

    await user.click(screen.getByRole('tab', { name: ru.adminTabErrors }));
    expect(await screen.findByText(ru.adminErrorsEmpty)).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: ru.adminTabAlerts }));
    expect(await screen.findByText(ru.adminAlertsEmpty)).toBeInTheDocument();
    expect(await screen.findByText(ru.adminBackupStatusUnavailable)).toBeInTheDocument();
  });
});
