// Route: /history (I4 E33, 71 §71.10; ТЗ ¶252 REQ-2210, ¶265/266 REQ-2220/2221): the trainee's
// own results — their statistics row (sessions, lessons, average percent, failed rules by category,
// mean deviations from the norms) and their completed sessions, newest first, each with its date,
// its score and a link to its report. A session whose report is not released to them yet is
// listed without a score (`score_percent: null`, the existing release rule). Every number is the
// server's (`getMyHistory`, D11); the page only rounds it for display.
import { Link } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { AppShell } from '@/shared/ui/app-shell';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import { getMyHistory, problemMessageRu, queryKeys, type ProblemCode, type UserRole } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { formatTimestampRu } from '@/shared/lib/format-timestamp';
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

export function HistoryPage() {
  const user = useAuthStore((state) => state.user);
  const historyQuery = useQuery({
    queryKey: queryKeys.statistics.myHistory(),
    queryFn: getMyHistory,
  });
  const history = historyQuery.data;
  const failed = history ? failedRulesLines(history.statistics.failed_rules_by_category) : [];

  return (
    <AppShell
      title={t('historyPageTitle')}
      role={user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined}
      userLabel={user?.display_name_ru}
      connectionIndicatorHidden
    >
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-lg font-semibold tracking-tight">{t('historyPageTitle')}</h1>
        <Link to="/sessions" className="text-sm text-primary underline-offset-2 hover:underline">
          {t('statisticsBackLink')}
        </Link>
      </div>
      {historyQuery.isLoading ? <p className="mt-2 text-sm text-muted-foreground">{t('historyLoading')}</p> : null}
      {historyQuery.isError ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {historyQuery.error instanceof ProblemError ? problemMessageRu(historyQuery.error.code as ProblemCode) : t('problemUnknown')}
        </p>
      ) : null}

      {history ? (
        <div className="mt-4 flex flex-col gap-4">
          <Card className="max-w-2xl">
            <CardHeader>
              <h2 className="font-heading text-base leading-snug font-medium">{t('historySummaryTitle')}</h2>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm" data-slot="history-summary">
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

          <Card className="max-w-2xl">
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
