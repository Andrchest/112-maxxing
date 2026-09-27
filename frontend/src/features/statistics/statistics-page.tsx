// Route: /instructor/statistics (I4 E33, 71 §71.10; ТЗ ¶101, ¶138, ¶225, ¶232, ¶360, ¶379). One
// row per trainee — sessions, lessons, the average percent, failed rules by category and the mean
// deviations from the system's norms — optionally for one trainee group and a date window, plus
// «Скачать CSV» (`getTraineeStatisticsCsv`, the same rows as a file). Every number is the server's,
// read from stored scores (D11); the page only rounds it for display. Charts, heat maps and
// Excel/PDF are bonus items and are not built (Q-E12-2).
// I5 E36 (Q-E12-1, Q-E12-2): two reaction-time average columns beside the deviations, and a
// «Рейтинг» table (`getTraineeRating` / `getTraineeRatingCsv`), same filters, best trainee first.
import { useState } from 'react';
import { Link } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { AppShell } from '@/shared/ui/app-shell';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import {
  getTraineeRating,
  getTraineeRatingCsv,
  getTraineeStatistics,
  getTraineeStatisticsCsv,
  listTraineeGroups,
  problemMessageRu,
  queryKeys,
  type ProblemCode,
  type TraineeStatisticsQuery,
  type UserRole,
} from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { saveBlob } from '@/shared/lib/download';
import { failedRulesLines, formatMeanDeviationMs, formatMeanDurationMs, formatPercent } from '@/entities/statistics';
import { formatPassCount } from '@/entities/pass-verdict';

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

/** A `<input type="date">` value as the start of that local day, in ISO (the API is UTC). */
function dayStartIso(day: string): string | undefined {
  return day ? new Date(`${day}T00:00:00`).toISOString() : undefined;
}

function problemText(error: unknown): string {
  return error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
}

export function StatisticsPage() {
  const user = useAuthStore((state) => state.user);
  const [groupId, setGroupId] = useState('');
  const [fromDay, setFromDay] = useState('');
  const [toDay, setToDay] = useState('');
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<unknown>(null);
  const [ratingDownloading, setRatingDownloading] = useState(false);
  const [ratingDownloadError, setRatingDownloadError] = useState<unknown>(null);

  const query: TraineeStatisticsQuery = {
    group_id: groupId || undefined,
    from: dayStartIso(fromDay),
    to: dayStartIso(toDay),
  };
  const statisticsQuery = useQuery({
    queryKey: queryKeys.statistics.list(query.group_id, query.from, query.to),
    queryFn: () => getTraineeStatistics(query),
  });
  const groupsQuery = useQuery({
    queryKey: queryKeys.traineeGroups.list(),
    queryFn: listTraineeGroups,
  });
  // I5 E36, Q-E12-2: the same filters, ranked by average score percent.
  const ratingQuery = useQuery({
    queryKey: queryKeys.statistics.rating(query.group_id, query.from, query.to),
    queryFn: () => getTraineeRating(query),
  });

  async function handleDownload() {
    setDownloading(true);
    setDownloadError(null);
    try {
      saveBlob(await getTraineeStatisticsCsv(query), 'statistics.csv');
    } catch (error) {
      setDownloadError(error);
    } finally {
      setDownloading(false);
    }
  }

  async function handleRatingDownload() {
    setRatingDownloading(true);
    setRatingDownloadError(null);
    try {
      saveBlob(await getTraineeRatingCsv(query), 'trainee-rating.csv');
    } catch (error) {
      setRatingDownloadError(error);
    } finally {
      setRatingDownloading(false);
    }
  }

  const rows = statisticsQuery.data?.rows ?? [];
  const ratingRows = ratingQuery.data?.rows ?? [];

  return (
    <AppShell
      title={t('statisticsPageTitle')}
      role={user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined}
      userLabel={user?.display_name_ru}
      connectionIndicatorHidden
    >
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-lg font-semibold tracking-tight">{t('statisticsPageTitle')}</h1>
        <Link to="/instructor" className="text-sm text-primary underline-offset-2 hover:underline">
          {t('statisticsBackLink')}
        </Link>
      </div>

      <Card className="mt-4">
        <CardHeader className="flex flex-row flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="statistics-group">{t('statisticsGroupLabel')}</Label>
            <select
              id="statistics-group"
              className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
              value={groupId}
              onChange={(event) => setGroupId(event.target.value)}
            >
              <option value="">{t('statisticsGroupAll')}</option>
              {(groupsQuery.data?.items ?? []).map((group) => (
                <option key={group.group_id} value={group.group_id}>
                  {group.name_ru}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="statistics-from">{t('statisticsFromLabel')}</Label>
            <Input id="statistics-from" type="date" value={fromDay} onChange={(event) => setFromDay(event.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="statistics-to">{t('statisticsToLabel')}</Label>
            <Input id="statistics-to" type="date" value={toDay} onChange={(event) => setToDay(event.target.value)} />
          </div>
          <Button type="button" variant="outline" size="sm" onClick={() => void handleDownload()} disabled={downloading}>
            {downloading ? t('lessonReportDownloadingCsv') : t('lessonReportDownloadCsv')}
          </Button>
          {downloadError ? (
            <span role="alert" className="text-sm text-destructive">
              {problemText(downloadError)}
            </span>
          ) : null}
        </CardHeader>
        <CardContent>
          {statisticsQuery.isLoading ? <p className="text-sm text-muted-foreground">{t('statisticsLoading')}</p> : null}
          {statisticsQuery.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {problemText(statisticsQuery.error)}
            </p>
          ) : null}
          {statisticsQuery.data && rows.length === 0 ? <p className="text-sm text-muted-foreground">{t('statisticsEmpty')}</p> : null}
          {rows.length > 0 ? (
            <table className="w-full border-collapse text-sm" data-slot="statistics-table">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="p-2 font-medium">{t('statisticsColumnTrainee')}</th>
                  <th className="p-2 font-medium">{t('statisticsColumnSessions')}</th>
                  <th className="p-2 font-medium">{t('statisticsColumnLessons')}</th>
                  <th className="p-2 font-medium">{t('statisticsColumnAverage')}</th>
                  <th className="p-2 font-medium">{t('statisticsColumnPassed')}</th>
                  <th className="p-2 font-medium">{t('statisticsColumnAcceptDeviation')}</th>
                  <th className="p-2 font-medium">{t('statisticsColumnFillDeviation')}</th>
                  <th className="p-2 font-medium">{t('statisticsColumnReactionToOpen')}</th>
                  <th className="p-2 font-medium">{t('statisticsColumnReactionToStatus')}</th>
                  <th className="p-2 font-medium">{t('statisticsColumnFailedRules')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const failed = failedRulesLines(row.failed_rules_by_category);
                  return (
                    <tr key={row.trainee_user_id} className="border-b border-border/60 align-top" data-slot="statistics-row">
                      <td className="p-2">{row.display_name_ru}</td>
                      <td className="p-2 tabular-nums">{row.session_count}</td>
                      <td className="p-2 tabular-nums">{row.lesson_count}</td>
                      <td className="p-2 tabular-nums" data-slot="statistics-average">
                        {formatPercent(row.average_percent)}
                      </td>
                      <td className="p-2 tabular-nums" data-slot="statistics-passed">
                        {formatPassCount(row.pass_count, row.pass_rate)}
                      </td>
                      <td className="p-2 tabular-nums">{formatMeanDeviationMs(row.accept_deviation_ms_avg)}</td>
                      <td className="p-2 tabular-nums">{formatMeanDeviationMs(row.fill_deviation_ms_avg)}</td>
                      <td className="p-2 tabular-nums">{formatMeanDurationMs(row.reaction_to_open_ms_avg ?? null)}</td>
                      <td className="p-2 tabular-nums">{formatMeanDurationMs(row.reaction_to_status_ms_avg ?? null)}</td>
                      <td className="p-2 text-xs">
                        {failed.length === 0 ? t('statisticsNoValue') : failed.map((line) => <div key={line}>{line}</div>)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : null}
        </CardContent>
      </Card>

      <Card className="mt-4" data-slot="statistics-rating-card">
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold tracking-tight">{t('statisticsRatingTitle')}</h2>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void handleRatingDownload()}
              disabled={ratingDownloading}
            >
              {ratingDownloading ? t('lessonReportDownloadingCsv') : t('lessonReportDownloadCsv')}
            </Button>
            {ratingDownloadError ? (
              <span role="alert" className="text-sm text-destructive">
                {problemText(ratingDownloadError)}
              </span>
            ) : null}
          </div>
        </CardHeader>
        <CardContent>
          {ratingQuery.isLoading ? <p className="text-sm text-muted-foreground">{t('statisticsRatingLoading')}</p> : null}
          {ratingQuery.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {problemText(ratingQuery.error)}
            </p>
          ) : null}
          {ratingQuery.data && ratingRows.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('statisticsRatingEmpty')}</p>
          ) : null}
          {ratingRows.length > 0 ? (
            <table className="w-full border-collapse text-sm" data-slot="statistics-rating-table">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="p-2 font-medium">{t('statisticsRatingColumnRank')}</th>
                  <th className="p-2 font-medium">{t('statisticsRatingColumnTrainee')}</th>
                  <th className="p-2 font-medium">{t('statisticsRatingColumnAverage')}</th>
                  <th className="p-2 font-medium">{t('statisticsRatingColumnPassed')}</th>
                </tr>
              </thead>
              <tbody>
                {ratingRows.map((row) => (
                  <tr key={row.trainee_user_id} className="border-b border-border/60" data-slot="statistics-rating-row">
                    <td className="p-2 tabular-nums">{row.rank}</td>
                    <td className="p-2">{row.display_name_ru}</td>
                    <td className="p-2 tabular-nums">{formatPercent(row.average_percent)}</td>
                    <td className="p-2 tabular-nums" data-slot="statistics-rating-passed">
                      {formatPassCount(row.pass_count, row.pass_rate)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </CardContent>
      </Card>
    </AppShell>
  );
}
