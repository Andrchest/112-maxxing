import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TimingMetricsSection } from './timing-metrics-section';
import { ru } from '@/shared/i18n/ru';
import { makeTimingMetrics } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function renderSection(timingMetrics = makeTimingMetrics()) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <TimingMetricsSection sessionId="sess-1" timingMetrics={timingMetrics} />
    </QueryClientProvider>,
  );
}

describe('TimingMetricsSection — a null metric renders reportTimingMetricsNoData, never 0 (SPEC §27)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the aggregate stats', () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], total: 0, timing_metrics: makeTimingMetrics() })));
    renderSection(makeTimingMetrics({ turn_count: 8, speech_end_to_first_audio_ms_p50: 900 }));
    expect(screen.getByText('8')).toBeInTheDocument();
    expect(screen.getByText('900')).toBeInTheDocument();
  });

  it('renders reportTimingMetricsNoData for a null metric, never 0', () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], total: 0, timing_metrics: makeTimingMetrics() })));
    // `fallback_count` stays a real, non-null 0 here on purpose — this test only asserts that the
    // two *null* metrics never render as a fake "0", not that "0" never appears anywhere (a real
    // zero fallback count is a legitimate value, not a missing one).
    renderSection(makeTimingMetrics({ speech_end_to_first_audio_ms_p50: null, asr_latency_ms_p50: null, turn_count: 8, fallback_count: 0 }));
    const noDataCells = screen.getAllByText(ru.reportTimingMetricsNoData);
    expect(noDataCells.length).toBeGreaterThanOrEqual(2);
  });

  it('renders the raw per-call metrics once loaded', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          items: [
            {
              id: 'metric-1',
              session_id: 'sess-1',
              request_id: 'request-1',
              component: 'ASR',
              provider: 'giga-am',
              model: 'v3_e2e_ctc',
              model_version: null,
              turn_index: 0,
              input_tokens: null,
              input_duration_ms: 2000,
              output_tokens: null,
              output_audio_ms: null,
              started_at: '2026-09-21T00:00:01Z',
              first_output_at: '2026-09-21T00:00:01.3Z',
              finished_at: '2026-09-21T00:00:01.4Z',
              ttft_ms: 300,
              total_latency_ms: 400,
              tokens_per_second: null,
              realtime_factor: null,
              gpu_memory_mb: null,
              fallback_count: 0,
              retry_count: 0,
            },
          ],
          total: 1,
          timing_metrics: makeTimingMetrics(),
        }),
      ),
    );
    renderSection();
    expect(await screen.findByText('ASR')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/giga-am/)).toBeInTheDocument());
  });
});
