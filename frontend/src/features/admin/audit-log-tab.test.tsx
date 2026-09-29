import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuditLogTab } from './audit-log-tab';
import { ru } from '@/shared/i18n/ru';
import type { AuditEntryView } from '@/shared/api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function renderTab() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuditLogTab />
    </QueryClientProvider>,
  );
}

const ENTRY: AuditEntryView = {
  id: 'audit-1',
  ts: '2026-09-24T08:15:00Z',
  user_id: 'user-1',
  role: 'INSTRUCTOR',
  action: 'LOGIN_SUCCEEDED',
  operation_id: 'loginUser',
  method: 'POST',
  path_template: '/api/v1/auth/login',
  target_ids: {},
  status: 200,
  client_ip: '10.0.0.5',
  outcome: 'OK',
};

// I4 E30 (71 §71.7): the «Журнал» tab pages the audit log E25/E29 wrote.
describe('AuditLogTab', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows the audit entries the server sent, newest first', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith('/api/v1/admin/audit-log')) return jsonResponse({ items: [ENTRY], total: 1 });
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderTab();

    // `findByText` for the action label alone would also match its option in the filter
    // dropdown, present before any fetch resolves — wait on the row-only IP text instead.
    expect(await screen.findByText('10.0.0.5')).toBeInTheDocument();
    const row = screen.getByText('10.0.0.5').closest('tr');
    expect(row).toHaveTextContent(ru.adminAuditActionLoginSucceeded);
    expect(row).toHaveTextContent(ru.userRoleInstructor);
    expect(row).toHaveTextContent(ru.adminAuditOutcomeOk);
  });

  // I6 FIX1: the «Пользователь» cell names the account (login and display name), never the bare
  // role enum; a failed login names the attempted login.
  it('names the acting account, and the attempted login for a failed one', async () => {
    const named: AuditEntryView = { ...ENTRY, id: 'audit-2', username: 'instructor', display_name_ru: 'Ivanov', client_ip: '10.0.0.6' };
    const failed: AuditEntryView = {
      ...ENTRY,
      id: 'audit-3',
      user_id: null,
      role: null,
      action: 'LOGIN_FAILED',
      status: 401,
      outcome: 'DENIED',
      target_ids: { username: 'nobody' },
      client_ip: '10.0.0.7',
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ items: [named, failed], total: 2 })),
    );

    renderTab();

    expect(await screen.findByText('10.0.0.6')).toBeInTheDocument();
    const namedCell = screen.getByText('10.0.0.6').closest('tr')?.querySelectorAll('td')[1];
    expect(namedCell).toHaveTextContent('instructor');
    expect(namedCell).toHaveTextContent('Ivanov');
    expect(namedCell).toHaveTextContent(ru.userRoleInstructor);
    expect(namedCell).not.toHaveTextContent('INSTRUCTOR');
    const failedCell = screen.getByText('10.0.0.7').closest('tr')?.querySelectorAll('td')[1];
    expect(failedCell).toHaveTextContent('nobody');
    expect(failedCell).toHaveTextContent(ru.adminAuditAttemptedLogin);
  });

  // I7 E43 (Q-E15-3): a row that changed something expands into «поле: было → стало» lines with
  // Russian field labels and values; a secret shows only «изменён»; a row without changes has
  // no toggle.
  it('expands and collapses the before/after list of a row with changes', async () => {
    const changed: AuditEntryView = {
      ...ENTRY,
      id: 'audit-4',
      action: 'HTTP_REQUEST',
      operation_id: 'updateUser',
      method: 'PATCH',
      path_template: '/api/v1/admin/users/{user_id}',
      client_ip: '10.0.0.8',
      changes: [
        { field: 'user.user_role', before: 'TRAINEE', after: 'INSTRUCTOR' },
        { field: 'user.is_active', before: true, after: false },
        { field: 'user.password', before: null, after: null },
        { field: 'lesson.weight[2]', before: 1, after: 2.5 },
      ],
    };
    const plain: AuditEntryView = { ...ENTRY, id: 'audit-5', client_ip: '10.0.0.9', changes: [] };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ items: [changed, plain], total: 2 })),
    );
    const user = userEvent.setup();

    renderTab();

    expect(await screen.findByText('10.0.0.8')).toBeInTheDocument();
    const plainRow = screen.getByText('10.0.0.9').closest('tr');
    expect(plainRow?.querySelector('button')).toBeNull();
    expect(screen.queryByRole('list', { name: ru.adminAuditChangesListLabel })).toBeNull();

    const toggle = screen.getByRole('button', { name: `${ru.adminAuditChangesShow} (4)` });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);

    const list = screen.getByRole('list', { name: ru.adminAuditChangesListLabel });
    const lines = within(list).getAllByRole('listitem').map((item) => item.textContent);
    expect(lines).toEqual([
      `${ru.adminAuditFieldUserRole}: ${ru.userRoleTrainee} → ${ru.userRoleInstructor}`,
      `${ru.adminAuditFieldUserIsActive}: ${ru.adminAuditChangeYes} → ${ru.adminAuditChangeNo}`,
      `${ru.adminAuditFieldUserPassword}: ${ru.adminAuditChangeSecret}`,
      `${ru.adminAuditFieldLessonWeight} (${ru.adminAuditChangeCardNumber}2): 1 → 2,5`,
    ]);
    expect(list).not.toHaveTextContent('user.user_role');

    await user.click(screen.getByRole('button', { name: `${ru.adminAuditChangesHide} (4)` }));
    expect(screen.queryByRole('list', { name: ru.adminAuditChangesListLabel })).toBeNull();
  });

  it('asks the server for rows with changes only when the changes-only checkbox is on', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    renderTab();
    expect(await screen.findByText(ru.adminAuditEmpty)).toBeInTheDocument();
    const firstCall = String((fetchMock.mock.calls[0] as unknown[])[0]);
    expect(firstCall).not.toContain('with_changes');

    await user.click(screen.getByRole('checkbox', { name: ru.adminAuditFilterWithChanges }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some((call) => String((call as unknown[])[0]).includes('with_changes=true'))).toBe(true),
    );
  });

  it('shows the empty state for no entries', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ items: [], total: 0 })),
    );

    renderTab();
    expect(await screen.findByText(ru.adminAuditEmpty)).toBeInTheDocument();
  });
});
