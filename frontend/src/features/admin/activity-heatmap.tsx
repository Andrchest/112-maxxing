// «Активность» weekday × hour heatmap (I7 E46a, admin item 6) — `getActivityHeatmap`'s own card
// on the «Статистика» tab, next to the per-day usage table above (E29/E30), neither touching the
// other. Rows are ISO weekdays (Monday first) in Moscow wall time, columns are Moscow hours
// (manager follow-up: admins read this as local hours, never UTC — the server buckets it the
// same way, `Europe/Moscow`); a cell is the count of sessions *started* in that bucket, `0` (not
// `null`) for a bucket the server did not list — a zero session count is a real measurement,
// never «no data» (module doc of `Heatmap`).
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent } from '@/shared/ui/card';
import { Heatmap } from '@/shared/ui/charts';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { getActivityHeatmap, problemMessageRu, queryKeys, type ProblemCode } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';

const WEEKDAY_LABEL_KEYS = [
  'adminActivityWeekdayMon',
  'adminActivityWeekdayTue',
  'adminActivityWeekdayWed',
  'adminActivityWeekdayThu',
  'adminActivityWeekdayFri',
  'adminActivityWeekdaySat',
  'adminActivityWeekdaySun',
] as const;

const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

function problemText(error: unknown): string {
  return error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
}

export function ActivityHeatmap() {
  const query = useQuery({
    queryKey: queryKeys.admin.activityHeatmap(),
    queryFn: getActivityHeatmap,
  });

  const cells = query.data?.cells ?? [];
  const hasAnyActivity = cells.length > 0;
  const grid: number[][] = WEEKDAY_LABEL_KEYS.map(() => HOURS.map(() => 0));
  let maxCount = 0;
  for (const cell of cells) {
    const row = cell.weekday - 1;
    if (grid[row]) {
      grid[row][cell.hour] = cell.session_count;
      maxCount = Math.max(maxCount, cell.session_count);
    }
  }

  return (
    <Card className="mt-4" data-slot="admin-activity-heatmap-card">
      <CardContent>
        {query.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(query.error)}
          </p>
        ) : (
          <Heatmap
            title={t('adminActivityHeatmapTitle')}
            rowLabels={hasAnyActivity ? WEEKDAY_LABEL_KEYS.map((key) => ru[key]) : []}
            columnLabels={hasAnyActivity ? HOURS.map((hour) => String(hour)) : []}
            values={grid}
            emptyMessage={t('adminActivityHeatmapEmpty')}
            legendLabel={t('adminActivityHeatmapLegendLabel')}
            colorScaleMax={Math.max(1, maxCount)}
            formatValue={(value) => String(Math.round(value))}
            columnLabelStep={3}
            rowLabelWidth={32}
            columnAxisLabel={t('adminActivityHourAxisLabel')}
          />
        )}
      </CardContent>
    </Card>
  );
}
