// Route: /history (I4 E33, 71 §71.10; ТЗ ¶252 REQ-2210, ¶265/266 REQ-2220/2221): the trainee's
// own results — their statistics row (sessions, lessons, average percent, failed rules by category,
// mean deviations from the norms) and their completed sessions, newest first, each with its date,
// its score and a link to its report. A session whose report is not released to them yet is
// listed without a score (`score_percent: null`, the existing release rule). Every number is the
// server's (`getMyHistory`, D11); the page only rounds it for display.
import { useState } from 'react';
import { Link } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { AppShell } from '@/shared/ui/app-shell';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import { exportUserProfile, getMyHistory, problemMessageRu, queryKeys, type ProblemCode, type UserRole } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { formatTimestampRu } from '@/shared/lib/format-timestamp';
import { downloadBlob, reportDownloadFailed } from '@/shared/lib/download';
import {
  failedRulesLines,
  formatMeanDeviationMs,
  formatPercent,
} from '@/entities/statistics';

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

/** «Результат» (I7 E50, G9): `passed` is `null` until the report is visible, exactly like
 * `score_percent` — rendered the same way (`statisticsNoValue`, «—»). */
function historyResultLabel(passed: boolean | null | undefined): string {
  if (passed === null || passed === undefined) return t('statisticsNoValue');
  return passed ? t('historyResultPassed') : t('historyResultFailed');
}

/** «Реакция: …, с» (I7 E50, G9): the server's own ms, rounded to whole seconds for this column —
 * `null`/absent renders as «—», never `0`. */
function formatReactionSeconds(valueMs: number | null | undefined): string {
  return valueMs === null || valueMs === undefined ? t('statisticsNoValue') : String(Math.round(valueMs / 1000));
}

export function HistoryPage() {
  const user = useAuthStore((state) => state.user);
  const historyQuery = useQuery({
    queryKey: queryKeys.statistics.myHistory(),
    queryFn: getMyHistory,
  });
  const history = historyQuery.data;
  const failed = history ? failedRulesLines(history.statistics.failed_rules_by_category) : [];

  // I5 E37 (Q-E16-4): «Скачать профиль (JSON)» — the trainee's own account fields plus this same
  // history summary, never the password hash or SIP HA1.
  const [profileDownloading, setProfileDownloading] = useState(false);
  const [profileDownloadError, setProfileDownloadError] = useState<unknown>(null);

  async function handleProfileDownload() {
    if (!user) return;
    setProfileDownloading(true);
    setProfileDownloadError(null);
    const fileName = `profile-${user.username}.json`;
    try {
      downloadBlob(await exportUserProfile(user.id), fileName);
    } catch (error) {
      setProfileDownloadError(error);
      reportDownloadFailed(fileName, error);
    } finally {
      setProfileDownloading(false);
    }
  }

  return (
    <AppShell
      title={t('historyPageTitle')}
      role={user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined}
      userLabel={user?.display_name_ru}
      connectionIndicatorHidden
    >
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-lg font-semibold tracking-tight">{t('historyPageTitle')}</h1>
        <div className="flex items-center gap-3">
          <Button type="button" variant="outline" size="sm" disabled={profileDownloading} onClick={() => void handleProfileDownload()}>
            {profileDownloading ? t('profileExportDownloading') : t('historyDownloadProfileButton')}
          </Button>
          <Link to="/sessions" className="text-sm text-primary underline-offset-2 hover:underline">
            {t('statisticsBackLink')}
          </Link>
        </div>
      </div>
      {profileDownloadError ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {profileDownloadError instanceof ProblemError ? problemMessageRu(profileDownloadError.code as ProblemCode) : t('problemUnknown')}
        </p>
      ) : null}
      {historyQuery.isLoading ? <p className="mt-2 text-sm text-muted-foreground">{t('historyLoading')}</p> : null}
      {historyQuery.isError ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {historyQuery.error instanceof ProblemError ? problemMessageRu(historyQuery.error.code as ProblemCode) : t('problemUnknown')}
        </p>
      ) : null}

      {history ? (
        <div className="mt-4 flex flex-col gap-4">
          <Card data-tour="history-summary">
            <CardHeader>
              <h2 className="font-heading text-base leading-snug font-medium">{t('historySummaryTitle')}</h2>
            </CardHeader>
            <CardContent className="@container">
              {/* I6 layout: the summary card is now full width (`max-w-2xl` removed above), so its
                  7 rows spread into more columns instead of leaving most of a wide card empty. */}
              {/* Each `dt`/`dd` pair must land in the same row, so the column count stays a
                  multiple of 2 (one pair per column pair), never 3. */}
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm @lg:grid-cols-4 @4xl:grid-cols-6" data-slot="history-summary">
                <dt className="text-muted-foreground">{t('statisticsColumnSessions')}</dt>
                <dd className="tabular-nums">{history.statistics.session_count}</dd>
                <dt className="text-muted-foreground">{t('statisticsColumnLessons')}</dt>
                <dd className="tabular-nums">{history.statistics.lesson_count}</dd>
                <dt className="text-muted-foreground">{t('statisticsColumnAverage')}</dt>
                <dd className="tabular-nums" data-slot="history-average">
                  {formatPercent(history.statistics.average_percent)}
                </dd>
                <dt className="text-muted-foreground">{t('statisticsColumnAcceptDeviation')}</dt>
                <dd className="tabular-nums">{formatMeanDeviationMs(history.statistics.accept_deviation_ms_avg)}</dd>
                <dt className="text-muted-foreground">{t('statisticsColumnFillDeviation')}</dt>
                <dd className="tabular-nums">{formatMeanDeviationMs(history.statistics.fill_deviation_ms_avg)}</dd>
                <dt className="text-muted-foreground">{t('statisticsColumnFailedRules')}</dt>
                <dd>{failed.length === 0 ? t('statisticsNoValue') : failed.map((line) => <div key={line}>{line}</div>)}</dd>
              </dl>
            </CardContent>
          </Card>

          <Card data-tour="history-sessions">
            <CardHeader>
              <h2 className="font-heading text-base leading-snug font-medium">{t('historySessionsTitle')}</h2>
            </CardHeader>
            <CardContent>
              {history.sessions.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t('historyEmpty')}</p>
              ) : (
                <table className="w-full border-collapse text-sm" data-slot="history-table">
                  <thead>
                    <tr className="border-b border-border text-left text-xs text-muted-foreground">
                      <th className="p-2 font-medium">{t('historyColumnDate')}</th>
                      <th className="p-2 font-medium">{t('historyColumnScenario')}</th>
                      <th className="p-2 font-medium">{t('historyColumnScore')}</th>
                      <th className="p-2 font-medium">{t('historyColumnFailedRules')}</th>
                      {/* I7 E50 (G9, ТЗ ¶265): the four additive fields on `MyHistorySession`,
                          reusing the same per-session data the lesson report already computes. */}
                      <th className="p-2 font-medium">{t('historyColumnResult')}</th>
                      <th className="p-2 font-medium">{t('historyColumnReactionOpen')}</th>
                      <th className="p-2 font-medium">{t('historyColumnReactionFirstStatus')}</th>
                      <th className="p-2 font-medium">{t('historyColumnTextQualityIssues')}</th>
                      <th className="p-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {history.sessions.map((session) => (
                      <tr key={session.session_id} className="border-b border-border/60" data-slot="history-row">
                        <td className="p-2 tabular-nums">{formatTimestampRu(session.completed_at)}</td>
                        <td className="p-2">{session.scenario_title_ru}</td>
                        <td className="p-2 tabular-nums">
                          {session.score_percent === null ? (
                            <span className="text-muted-foreground">{t('historyScoreNotReleased')}</span>
                          ) : (
                            formatPercent(session.score_percent)
                          )}
                        </td>
                        <td className="p-2 tabular-nums">{session.failed_rule_count ?? t('statisticsNoValue')}</td>
                        <td className="p-2" data-slot="history-passed-cell">{historyResultLabel(session.passed)}</td>
                        <td className="p-2 tabular-nums">{formatReactionSeconds(session.reaction_open_ms)}</td>
                        <td className="p-2 tabular-nums">{formatReactionSeconds(session.reaction_first_status_ms)}</td>
                        <td className="p-2 tabular-nums">{session.text_quality_issue_count ?? t('statisticsNoValue')}</td>
                        <td className="p-2 text-right">
                          <Link className="text-primary underline-offset-2 hover:underline" to={`/report/${session.session_id}`}>
                            {t('historyOpenReport')}
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>
        </div>
      ) : null}
    </AppShell>
  );
}
