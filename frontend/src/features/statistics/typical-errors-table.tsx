// «Типичные ошибки» — G11 (ТЗ ¶233, I7 E54). Renders `TypicalErrors.rows` verbatim, in the
// server's own order (worst rule first, at most 10) — used on the instructor statistics page
// (`StatisticsPage`, its own filter) and embedded in the lesson report
// (`lesson-detail-page.tsx`'s `LessonReportSection`, that lesson's own scope). Its own
// section/component on purpose (owner note, `E42-gaps.md` §2 item 13): a parallel epic (E46a) may
// add charts to the same statistics page without touching this table.
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { scoringCategoryLabelRu } from '@/features/report/scoring-labels';
import type { TypicalErrorRow } from '@/shared/api';

export function TypicalErrorsTable({ rows }: { rows: readonly TypicalErrorRow[] }) {
  return (
    <Card data-slot="typical-errors">
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('typicalErrorsTitle')}</h2>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-slot="typical-errors-empty">
            {t('typicalErrorsEmpty')}
          </p>
        ) : (
          <table className="w-full border-collapse text-sm" data-slot="typical-errors-table">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="p-2 font-medium">{t('typicalErrorsColumnRule')}</th>
                <th className="p-2 font-medium">{t('typicalErrorsColumnCategory')}</th>
                <th className="p-2 font-medium">{t('typicalErrorsColumnSessions')}</th>
                <th className="p-2 font-medium">{t('typicalErrorsColumnShare')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.rule_id} className="border-b border-border/60" data-slot="typical-errors-row">
                  <td className="p-2">{row.name_ru}</td>
                  <td className="p-2">{scoringCategoryLabelRu(row.category)}</td>
                  <td className="p-2 tabular-nums">
                    {row.failed_session_count} / {row.session_count}
                  </td>
                  <td className="p-2 tabular-nums">{Math.round(row.share_percent)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}
