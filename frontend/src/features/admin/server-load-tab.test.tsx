import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ServerLoadTab } from './server-load-tab';
import { ru } from '@/shared/i18n/ru';
import type { ServerLoad } from '@/shared/api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function renderTab() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ServerLoadTab />
    </QueryClientProvider>,
  );
}

// I4 E30 (71 §71.7 → SPEC §27): an absent metric renders the ru.adminNoData placeholder, never 0.
describe('ServerLoadTab', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders a present metric with its value and unit', async () => {
    const load: ServerLoad = {
      sampled_at: '2026-09-25T06:00:00Z',
      cpu_percent: 12.3,
      memory_used_mb: 2048,
      memory_total_mb: 8192,
      disk_used_gb: 10,
      disk_total_gb: 100,
      gpu_memory_used_mb: null,
      gpu_memory_total_mb: null,
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(load)),
    );

    renderTab();

    expect(await screen.findByText('12.3 %')).toBeInTheDocument();
    expect(screen.getByText(`2048 ${ru.adminUnitMb} / 8192 ${ru.adminUnitMb}`)).toBeInTheDocument();
  });

  it('renders the no-data placeholder for every null metric, never a bare 0', async () => {
    const load: ServerLoad = {
      sampled_at: '2026-09-25T06:00:00Z',
      cpu_percent: null,
      memory_used_mb: null,
      memory_total_mb: null,
      disk_used_gb: null,
      disk_total_gb: null,
      gpu_memory_used_mb: null,
      gpu_memory_total_mb: null,
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(load)),
    );

    renderTab();

    const noDataCells = await screen.findAllByText(ru.adminNoData);
    expect(noDataCells).toHaveLength(4); // cpu, memory, disk, gpu
    expect(screen.queryByText('0')).not.toBeInTheDocument();
    expect(screen.queryByText(/^0 /)).not.toBeInTheDocument();
  });
});
