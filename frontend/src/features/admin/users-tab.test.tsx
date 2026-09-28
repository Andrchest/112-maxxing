import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { UsersTab } from './users-tab';
import { ru } from '@/shared/i18n/ru';
import type { UserAccountI4 } from '@/shared/api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function renderTab() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <UsersTab />
    </QueryClientProvider>,
  );
}

// A Latin placeholder only because `no-cyrillic-guard.test.ts` forbids a Cyrillic literal in
// `src/features` (test files included) — the column renders whatever `display_name_ru` it is given.
const ACTIVE_USER: UserAccountI4 = {
  id: 'user-1',
  username: 'trainee1',
  display_name_ru: 'Trainee One',
  user_role: 'TRAINEE',
  created_at: '2026-09-20T10:00:00Z',
  is_active: true,
};

// I4 E30 (71 §71.7): the «Пользователи» tab lists accounts and offers block/unblock.
describe('UsersTab', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('lists accounts from the server and blocks one', async () => {
    let current: UserAccountI4 = ACTIVE_USER;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/v1/users' && (!init || init.method === undefined)) {
        return jsonResponse({ items: [current], total: 1 });
      }
      if (url === '/api/v1/admin/users/user-1' && init?.method === 'PATCH') {
        current = { ...current, is_active: false };
        return jsonResponse(current);
      }
      throw new Error(`unexpected fetch: ${url} ${init?.method ?? 'GET'}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderTab();

    expect(await screen.findByText('trainee1')).toBeInTheDocument();
    expect(screen.getByText(ru.adminUsersStatusActive)).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: ru.adminUsersBlockButton }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === 'PATCH')).toBe(true),
    );
    await waitFor(() => expect(screen.getByText(ru.adminUsersStatusBlocked)).toBeInTheDocument());
  });

  it('shows the empty state and creates a new user', async () => {
    const createdUser: UserAccountI4 = { ...ACTIVE_USER, id: 'user-2', username: 'newuser' };
    let usersCallCount = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/v1/users') {
        usersCallCount += 1;
        return jsonResponse({ items: usersCallCount === 1 ? [] : [createdUser], total: usersCallCount === 1 ? 0 : 1 });
      }
      if (url === '/api/v1/admin/users' && init?.method === 'POST') {
        return jsonResponse(createdUser, 201);
      }
      throw new Error(`unexpected fetch: ${url} ${init?.method ?? 'GET'}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderTab();
    expect(await screen.findByText(ru.adminUsersEmpty)).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: ru.adminUsersCreateButton }));
    await user.type(screen.getByLabelText(ru.adminUsersUsernameLabel), 'newuser');
    await user.type(screen.getByLabelText(ru.adminUsersDisplayNameLabel), 'New User');
    await user.type(screen.getByLabelText(ru.adminUsersPasswordLabel), 'a-strong-password');
    await user.click(screen.getByRole('button', { name: ru.adminUsersCreateSubmit }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === 'POST')).toBe(true),
    );
    expect(await screen.findByText('newuser')).toBeInTheDocument();
  });

  // I5 E37 (Q-E16-4): «Скачать профиль (JSON)» per row.
  it('downloads a row\'s profile as JSON', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/v1/users') return jsonResponse({ items: [ACTIVE_USER], total: 1 });
      if (url === '/api/v1/users/user-1/profile-export') {
        return new Response('{"id":"user-1"}', { status: 200, headers: { 'content-type': 'application/json' } });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const original = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
    const createObjectURL = vi.fn(() => 'blob:profile');
    const revokeObjectURL = vi.fn();
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    try {
      renderTab();
      await screen.findByText('trainee1');
      await userEvent.setup().click(screen.getByRole('button', { name: ru.adminUsersDownloadProfileButton }));

      await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
      expect(fetchMock.mock.calls.some(([requestInput]) => String(requestInput) === '/api/v1/users/user-1/profile-export')).toBe(true);
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:profile');
    } finally {
      URL.createObjectURL = original.create;
      URL.revokeObjectURL = original.revoke;
      click.mockRestore();
    }
  });

  // I6 FIX1 (S10): with more accounts than one page (server default 50), a newly created blocked
  // user sorted by login behind older ones was never shown. Every page is loaded now, newest first,
  // and «Поиск по логину» narrows the table.
  it('loads every page, lists the newest account first and filters by login', async () => {
    const older: UserAccountI4[] = Array.from({ length: 120 }, (_, index) => ({
      id: `old-${index}`,
      username: `e2e-a${String(index).padStart(3, '0')}-tempuser`,
      display_name_ru: `Old ${index}`,
      user_role: 'TRAINEE',
      created_at: `2026-09-01T10:${String(index % 60).padStart(2, '0')}:00Z`,
      is_active: false,
    }));
    const newest: UserAccountI4 = {
      id: 'new-1',
      username: 'zz-newest-blocked',
      display_name_ru: 'Newest',
      user_role: 'TRAINEE',
      created_at: '2026-09-28T12:00:00Z',
      is_active: false,
    };
    const roster = [...older, newest]; // `username` order, as the server pages it
    const requested: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      requested.push(url.pathname + url.search);
      if (url.pathname === '/api/v1/users') {
        const offset = Number(url.searchParams.get('offset') ?? '0');
        return jsonResponse({ items: roster.slice(offset, offset + 50), total: roster.length });
      }
      throw new Error(`unexpected fetch: ${url.pathname}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderTab();
    const user = userEvent.setup();
    await user.click(await screen.findByLabelText(ru.adminUsersIncludeInactiveLabel));

    expect(await screen.findByText('zz-newest-blocked')).toBeInTheDocument();
    const rows = screen.getAllByRole('row').filter((row) => row.getAttribute('data-slot') === 'admin-user-row');
    expect(rows).toHaveLength(121);
    expect(rows[0]).toHaveTextContent('zz-newest-blocked');
    expect(requested).toContain('/api/v1/users?include_inactive=true&offset=100');

    await user.type(screen.getByLabelText(ru.adminUsersSearchLabel), 'NEWEST');
    await waitFor(() =>
      expect(screen.getAllByRole('row').filter((row) => row.getAttribute('data-slot') === 'admin-user-row')).toHaveLength(1),
    );
    expect(screen.getByText('zz-newest-blocked')).toBeInTheDocument();

    await user.clear(screen.getByLabelText(ru.adminUsersSearchLabel));
    await user.type(screen.getByLabelText(ru.adminUsersSearchLabel), 'no-such-login');
    expect(await screen.findByText(ru.adminUsersSearchEmpty)).toBeInTheDocument();
  });
});
