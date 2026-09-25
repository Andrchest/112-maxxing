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
});
