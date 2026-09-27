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
      { kind: 'DDS_FILL', service_id: 'FIRE_RESCUE', measured_ms: 42_000, norm_ms: 180_000, deviation_ms: -138_000 },
      { kind: 'ACCEPT', service_id: 'POLICE', measured_ms: null, norm_ms: 30_000, deviation_ms: null },
    ],
    failed_rule_count: 3,
    critical_error_count: 1,
    text_quality: {
      available: true,
      fields: [{ source: 'ADDRESS_STREET', text: 'a street', misspellings: [], street: { status: 'UNKNOWN', suggestions: [] } }],
      dictionary_sha256: 'd',
      street_list_sha256: 's',
      unavailable_message_ru: null,
    },
    reaction_times: [
      { service_id: 'FIRE_RESCUE', to_open_ms: 5_000, to_first_status_ms: 42_000 },
      { service_id: 'POLICE', to_open_ms: null, to_first_status_ms: null },
    ],
    workstation: 'trainee2',
    pass_verdict: {
      passed: false,
      failed_criteria: ['CRITICAL_ERRORS'],
      criteria: { min_score_percent: 70, max_failed_rules: null, fail_on_critical: true },
      score_percent: 80,
      failed_rule_count: 3,
      critical_error_count: 1,
    },
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
    text_quality: null,
    reaction_times: [],
    workstation: '',
    pass_verdict: null,
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
    expect(document.querySelector('[data-slot="report-card-text-quality"]')).toHaveTextContent('1'); // one flagged street

    const norms = document.querySelectorAll('[data-slot="report-norm"]');
    expect(Array.from(norms).map((norm) => norm.getAttribute('data-kind'))).toEqual(['FILL', 'ACCEPT', 'DDS_FILL', 'ACCEPT']);
    expect(norms[0]).toHaveTextContent(`${ru.lessonReportNormFill} 02:30 ${ru.lessonReportNormAgainst} 03:00 (−00:30)`);
    expect(norms[1]).toHaveTextContent(`${ru.lessonReportNormAccept}: ${ru.serviceTypeFireRescue} 00:42 ${ru.lessonReportNormAgainst} 00:30 (+00:12)`);
    expect(norms[2]).toHaveTextContent(`${ru.lessonReportNormDdsFill}: ${ru.serviceTypeFireRescue} 00:42 ${ru.lessonReportNormAgainst} 03:00`);
    expect(norms[3]).toHaveTextContent(`${ru.lessonReportNormNotMeasured} (${ru.lessonReportNormAgainst} 00:30)`);
    expect(norms[3]).not.toHaveTextContent('00:00');

    // (I5 E36, Q-E12-1, Q-E12-3) the reaction times and the workstation column.
    expect(document.querySelector('[data-slot="report-card-workstation"]')).toHaveTextContent('trainee2');
    const reactions = document.querySelectorAll('[data-slot="report-reaction-time"]');
    expect(reactions).toHaveLength(2);
    expect(reactions[0]).toHaveTextContent(`${ru.lessonReportReactionToOpen} (${ru.serviceTypeFireRescue}): 00:05`);
    expect(reactions[0]).toHaveTextContent(`${ru.lessonReportReactionToStatus}: 00:42`);
    expect(reactions[1]).toHaveTextContent(ru.lessonReportNormNotMeasured);
  });

  it('shows the verdict of each scored card with the criteria it failed, as sent (I5 E38)', () => {
    const [scoredCard] = CARDS;
    const failedVerdict = scoredCard?.pass_verdict;
    if (!scoredCard || !failedVerdict) throw new Error('fixture has a scored card with a verdict');
    const passed: LessonReport['cards'][number] = {
      ...scoredCard,
      session_id: 'sess-3',
      position: 3,
      pass_verdict: { ...failedVerdict, passed: true, failed_criteria: [] },
    };
    render(<LessonReportTable cards={[...CARDS, passed]} />);
    const verdicts = document.querySelectorAll('[data-slot="report-card-verdict"]');
    expect(verdicts).toHaveLength(2);
    expect(verdicts[0]).toHaveTextContent(ru.passVerdictFailed);
    expect(verdicts[0]).toHaveTextContent(`${ru.passVerdictCriterionCriticalErrors}: 1`);
    expect(verdicts[1]).toHaveTextContent(ru.passVerdictPassed);
    expect(verdicts[1]).not.toHaveTextContent(ru.passVerdictCriterionCriticalErrors);
    expect(screen.getByRole('columnheader', { name: ru.lessonReportTableColumnVerdict })).toBeInTheDocument();
  });

  it('shows a dash for a scored card the server sent no verdict for', () => {
    const [scoredCard] = CARDS;
    if (!scoredCard) throw new Error('fixture has a scored card');
    render(<LessonReportTable cards={[{ ...scoredCard, pass_verdict: undefined }]} />);
    expect(document.querySelector('[data-slot="report-card-verdict"]')).toHaveTextContent(ru.passVerdictNone);
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
