// §29 item 1: total score. Displays exactly `score_report.total_points`/`total_max_points` as
// `getSessionReport` returned them — never computed client-side (see `no-score-math-guard.test.ts`).
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import type { ScoreReportView } from '@/shared/api';

interface TotalsSectionProps {
  scoreReport: ScoreReportView;
}

export function TotalsSection({ scoreReport }: TotalsSectionProps) {
  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportTotalsTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-1">
        <p className="text-2xl font-semibold tabular-nums">
          {scoreReport.total_points} / {scoreReport.total_max_points}
        </p>
        <p className="text-xs text-muted-foreground">
          {t('reportTotalsScoreLabel')} · {t('reportTotalsComputedFromLabel')}: {scoreReport.computed_from_event_count}
        </p>
      </CardContent>
    </Card>
  );
}
