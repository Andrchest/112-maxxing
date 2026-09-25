import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AlertsTab } from './alerts-tab';
import { ru } from '@/shared/i18n/ru';
import type { AdminAlertView, BackupStatus } from '@/shared/api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function renderTab() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AlertsTab />
    </QueryClientProvider>,
  );
}

// The server sends this text already rendered; the fixture uses a Latin placeholder only because
// `no-cyrillic-guard.test.ts` forbids a Cyrillic literal in `src/features` (test files included) —
// the component itself renders whatever `detail_ru` it is given, untranslated.
const ALERT: AdminAlertView = {
  kind: 'BACKUP_STALE',
  since: '2026-09-23T00:00:00Z',
  detail_ru: 'Backup is older than 26 hours.',
};

// I4 E30 (71 §71.7 → E29, ТЗ ¶308, ¶143/¶216): the «Оповещения» tab plus the backup status.
describe('AlertsTab', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders an active alert and the backup status', async () => {
    const backup: BackupStatus = {
      available: true,
      finished_at: '2026-09-25T02:00:00Z',
      status: 'OK',
      database_bytes: 5_000_000,
      recordings_bytes: 12_000_000,
      database_sha256: 'abc',
      recordings_sha256: 'def',
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/admin/alerts') return jsonResponse({ items: [ALERT] });
        if (url === '/api/v1/admin/backup-status') return jsonResponse(backup);
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderTab();

    expect(await screen.findByText(ru.adminAlertsKindBackupStale)).toBeInTheDocument();
    expect(screen.getByText(ALERT.detail_ru)).toBeInTheDocument();
    expect(await screen.findByText(`5 ${ru.adminUnitMb}`)).toBeInTheDocument();
    expect(screen.getByText(`12 ${ru.adminUnitMb}`)).toBeInTheDocument();
  });

  it('shows no active alerts and an unavailable backup', async () => {
    const backup: BackupStatus = {
      available: false,
      finished_at: null,
      status: null,
      database_bytes: null,
      recordings_bytes: null,
      database_sha256: null,
      recordings_sha256: null,
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/admin/alerts') return jsonResponse({ items: [] });
        if (url === '/api/v1/admin/backup-status') return jsonResponse(backup);
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderTab();

    expect(await screen.findByText(ru.adminAlertsEmpty)).toBeInTheDocument();
    expect(await screen.findByText(ru.adminBackupStatusUnavailable)).toBeInTheDocument();
  });
});
