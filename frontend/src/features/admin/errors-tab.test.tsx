import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ErrorsTab } from './errors-tab';
import { ru } from '@/shared/i18n/ru';
import type { ErrorRecordView } from '@/shared/api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function renderTab() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ErrorsTab />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const RECORD: ErrorRecordView = {
  ts: '2026-09-24T09:00:00Z',
  source: 'MODEL_ERROR',
  message: 'ASR provider timed out',
  session_id: 'session-1',
};

// I4 E30 (71 §71.7 → E29, ТЗ ¶207): the «Ошибки» tab merges backend/model/inference errors.
describe('ErrorsTab', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders each merged error record with a link to its session report', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith('/api/v1/admin/errors')) return jsonResponse({ items: [RECORD] });
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderTab();

    expect(await screen.findByText('ASR provider timed out')).toBeInTheDocument();
    expect(screen.getByText(ru.adminErrorsSourceModelError)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: ru.adminErrorsOpenSession })).toHaveAttribute('href', '/report/session-1');
  });

  it('shows the empty state for no errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ items: [] })),
    );

    renderTab();
    expect(await screen.findByText(ru.adminErrorsEmpty)).toBeInTheDocument();
  });
});
