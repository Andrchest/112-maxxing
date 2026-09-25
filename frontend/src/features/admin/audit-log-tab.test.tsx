import { render, screen } from '@testing-library/react';
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
    expect(row).toHaveTextContent('INSTRUCTOR');
    expect(row).toHaveTextContent(ru.adminAuditOutcomeOk);
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
