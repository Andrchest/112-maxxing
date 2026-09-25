import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DownloadLessonReportCsvButton, LessonReportTable } from './lesson-report-table';
import { ru } from '@/shared/i18n/ru';
import type { LessonReport } from '@/shared/api';
import { setAuthToken } from '@/shared/lib/api';

const SCORE = {
  scenario_version_id: 'v1',
  session_id: 'sess-1',
  total_points: 8,
  total_max_points: 10,
  by_category: [],
  critical_errors: [],
  results: [],
  computed_from_event_count: 12,
  checksum: 'abc',
};

const CARDS: LessonReport['cards'] = [
  {
    position: 1,
    session_id: 'sess-1',
    weight: 2.5,
    score: SCORE,
    unscored: null,
    norms: [
      { kind: 'FILL', service_id: null, measured_ms: 150_000, norm_ms: 180_000, deviation_ms: -30_000 },
      { kind: 'ACCEPT', service_id: 'FIRE_RESCUE', measured_ms: 42_000, norm_ms: 30_000, deviation_ms: 12_000 },
      { kind: 'ACCEPT', service_id: 'POLICE', measured_ms: null, norm_ms: 30_000, deviation_ms: null },
    ],
    failed_rule_count: 3,
    critical_error_count: 1,
  },
  {
    position: 2,
    session_id: 'sess-2',
    weight: 1,
    score: null,
    unscored: { state: 'ABORTED', timeline: [], times: { started_at: null, aborted_at: null, elapsed_ms: null } },
    norms: [],
    failed_rule_count: null,
    critical_error_count: null,
  },
];

// I4 E33 (71 §71.10): the lesson report table — norms, counters, «Скачать CSV».
describe('LessonReportTable', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('lists each scored card with its counters and its times against the norms, as sent', () => {
    render(<LessonReportTable cards={CARDS} />);

    const rows = screen.getAllByRole('row').filter((row) => row.getAttribute('data-slot') === 'lesson-report-row');
    expect(rows).toHaveLength(1);
    expect(screen.getByText('8 / 10')).toBeInTheDocument();
    expect(screen.getByText('2.5')).toBeInTheDocument();
    expect(screen.getByText('3')).toHaveAttribute('data-slot', 'report-card-failed-rules');

    const norms = document.querySelectorAll('[data-slot="report-norm"]');
    expect(Array.from(norms).map((norm) => norm.getAttribute('data-kind'))).toEqual(['FILL', 'ACCEPT', 'ACCEPT']);
    expect(norms[0]).toHaveTextContent(`${ru.lessonReportNormFill} 02:30 ${ru.lessonReportNormAgainst} 03:00 (−00:30)`);
    expect(norms[1]).toHaveTextContent(`${ru.lessonReportNormAccept}: ${ru.serviceTypeFireRescue} 00:42 ${ru.lessonReportNormAgainst} 00:30 (+00:12)`);
    expect(norms[2]).toHaveTextContent(`${ru.lessonReportNormNotMeasured} (${ru.lessonReportNormAgainst} 00:30)`);
    expect(norms[2]).not.toHaveTextContent('00:00');
  });

  it('downloads the report CSV with the bearer token and hands it to the browser', async () => {
    const fetchMock = vi.fn(async () => new Response('a;b\r\n', { status: 200, headers: { 'content-type': 'text/csv' } }));
    vi.stubGlobal('fetch', fetchMock);
    const original = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
    const createObjectURL = vi.fn(() => 'blob:report');
    const revokeObjectURL = vi.fn();
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    setAuthToken('jwt-token');

    try {
      render(<DownloadLessonReportCsvButton lessonId="lesson-1" />);
      await userEvent.setup().click(screen.getByRole('button', { name: ru.lessonReportDownloadCsv }));

      await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
      const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
      expect(url).toBe('/api/v1/lessons/lesson-1/report.csv');
      expect((init.headers as Record<string, string>).Authorization).toBe('Bearer jwt-token');
      expect(createObjectURL).toHaveBeenCalledTimes(1);
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:report');
    } finally {
      URL.createObjectURL = original.create;
      URL.revokeObjectURL = original.revoke;
      setAuthToken(null);
    }
  });

  it('shows the problem when the download is refused', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ title: 'Conflict', status: 409, code: 'REPORT_NOT_READY' }), {
            status: 409,
            headers: { 'content-type': 'application/problem+json' },
          }),
      ),
    );
    render(<DownloadLessonReportCsvButton lessonId="lesson-1" />);
    await userEvent.setup().click(screen.getByRole('button', { name: ru.lessonReportDownloadCsv }));
    expect(await screen.findByRole('alert')).toHaveTextContent(ru.problemReportNotReady);
  });
});
