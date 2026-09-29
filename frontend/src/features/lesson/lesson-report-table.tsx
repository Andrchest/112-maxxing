// I4 E33 (71 §71.10; ТЗ ¶329 REQ-2271–2275, ¶360, ¶379): the lesson report as a table — per
// scored card its points, weight, failed rules, critical errors and its times against the system's
// norms (`LessonReport.cards[].norms`, measured against the session's recorded timers) — plus
// «Скачать CSV» / «Скачать Excel» / «Скачать PDF» (`getLessonReportCsv`'s `?format=`, I7 E46b,
// the same numbers as a file). Every number is shown exactly as the server sent it (D11); a norm
// that was not measured says so rather than showing zero.
// I4 E35 (71 §71.12): a «Грамотность» column, the card's flagged-word/street count from
// `LessonReport.cards[].text_quality` (the same object the session report's own section reads);
// «—» for an unscored card or when the checker was unavailable for it.
// I5 E36 (Q-E9b-2, Q-E12-1, Q-E12-3): a `DDS_FILL` norm line (the ДДС's own 3-minute norm, beside
// `ACCEPT`, same measured moment, the 3-minute limit); a «Время реакции» column from
// `LessonReport.cards[].reaction_times` (delivery → open / delivery → first status, no norm); a
// «Рабочее место» column, the card's participants' logins (`LessonReport.cards[].workstation`).
// I5 E38 (Q-E9b-3): an «Итог» column — «Сдал» / «Не сдал» and the failed criteria, exactly as
// `LessonReport.cards[].pass_verdict` says; «—» for a card without a verdict.
import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { t } from '@/shared/i18n';
import { formatCallDurationMs } from '@/entities/call';
import { serviceLabelRu } from '@/entities/service-catalog';
import { formatDeviationMs } from '@/entities/statistics';
import { failedCriteriaLines, passVerdictLabel } from '@/entities/pass-verdict';
import { textQualityFlaggedCount } from '@/entities/text-quality';
import {
  getLessonReportCsv,
  problemMessageRu,
  type LegReactionTimeView,
  type LessonReport,
  type NormView,
  type ProblemCode,
  type ReportFileFormat,
} from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { saveBlob } from '@/shared/lib/download';

// (I7 E46b) CSV first, so `screen.getByRole('button', { name: ru.lessonReportDownloadCsv })`
// keeps matching exactly one button.
const EXPORT_FORMATS: readonly ReportFileFormat[] = ['csv', 'xlsx', 'pdf'];

function exportLabel(format: ReportFileFormat): string {
  return format === 'csv' ? t('lessonReportDownloadCsv') : format === 'xlsx' ? t('reportDownloadExcel') : t('reportDownloadPdf');
}

function normLabel(norm: NormView): string {
  if (norm.kind === 'FILL') return t('lessonReportNormFill');
  if (norm.kind === 'DDS_FILL') {
    return norm.service_id
      ? `${t('lessonReportNormDdsFill')}: ${serviceLabelRu(norm.service_id)}`
      : t('lessonReportNormDdsFill');
  }
  return norm.service_id ? `${t('lessonReportNormAccept')}: ${serviceLabelRu(norm.service_id)}` : t('lessonReportNormAccept');
}

function NormLine({ norm }: { norm: NormView }) {
  const against = `${t('lessonReportNormAgainst')} ${formatCallDurationMs(norm.norm_ms)}`;
  return (
    <li data-slot="report-norm" data-kind={norm.kind}>
      <span>{normLabel(norm)}</span>{' '}
      {norm.measured_ms === null ? (
        <span className="text-muted-foreground">
          {t('lessonReportNormNotMeasured')} ({against})
        </span>
      ) : (
        <span className="tabular-nums">
          {formatCallDurationMs(norm.measured_ms)} {against}
          {norm.deviation_ms === null ? null : (
            <span
              className={norm.deviation_ms > 0 ? 'text-destructive' : 'text-muted-foreground'}
              data-slot="report-norm-deviation"
            >
              {' '}
              ({formatDeviationMs(norm.deviation_ms)})
            </span>
          )}
        </span>
      )}
    </li>
  );
}

function ReactionTimeLine({ reaction }: { reaction: LegReactionTimeView }) {
  const service = reaction.service_id ? ` (${serviceLabelRu(reaction.service_id)})` : '';
  return (
    <li data-slot="report-reaction-time">
      <span className="text-muted-foreground">{t('lessonReportReactionToOpen')}{service}:</span>{' '}
      <span className="tabular-nums">
        {reaction.to_open_ms === null ? t('lessonReportNormNotMeasured') : formatCallDurationMs(reaction.to_open_ms)}
      </span>
      {', '}
      <span className="text-muted-foreground">{t('lessonReportReactionToStatus')}:</span>{' '}
      <span className="tabular-nums">
        {reaction.to_first_status_ms === null
          ? t('lessonReportNormNotMeasured')
          : formatCallDurationMs(reaction.to_first_status_ms)}
      </span>
    </li>
  );
}

export function DownloadLessonReportCsvButton({ lessonId }: { lessonId: string }) {
  const [busyFormat, setBusyFormat] = useState<ReportFileFormat | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function handleDownload(format: ReportFileFormat) {
    setBusyFormat(format);
    setError(null);
    try {
      saveBlob(await getLessonReportCsv(lessonId, format), `lesson-${lessonId}-report.${format}`);
    } catch (caught) {
      setError(caught);
    } finally {
      setBusyFormat(null);
    }
  }

  return (
    <div className="flex items-center gap-2">
      {EXPORT_FORMATS.map((format) => (
        <Button
          key={format}
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void handleDownload(format)}
          disabled={busyFormat !== null}
        >
          {busyFormat === format ? t('lessonReportDownloadingCsv') : exportLabel(format)}
        </Button>
      ))}
      {error ? (
        <span role="alert" className="text-sm text-destructive">
          {error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown')}
        </span>
      ) : null}
    </div>
  );
}

/** The scored cards of the report (an unscored card is listed by the page, I4 E31). */
export function LessonReportTable({ cards }: { cards: LessonReport['cards'] }) {
  const scored = cards.filter((card) => card.score !== null);
  if (scored.length === 0) return null;
  return (
    <table className="w-full border-collapse text-sm" data-slot="lesson-report-table">
      <thead>
        <tr className="border-b border-border text-left text-xs text-muted-foreground">
          <th className="p-2 font-medium">{t('lessonReportTableColumnPosition')}</th>
          <th className="p-2 font-medium">{t('lessonReportTableColumnWorkstation')}</th>
          <th className="p-2 font-medium">{t('lessonReportTableColumnScore')}</th>
          <th className="p-2 font-medium">{t('lessonReportTableColumnWeight')}</th>
          <th className="p-2 font-medium">{t('lessonReportTableColumnFailedRules')}</th>
          <th className="p-2 font-medium">{t('lessonReportTableColumnCriticalErrors')}</th>
          <th className="p-2 font-medium">{t('lessonReportTableColumnVerdict')}</th>
          <th className="p-2 font-medium">{t('lessonReportTableColumnNorms')}</th>
          <th className="p-2 font-medium">{t('lessonReportTableColumnReactionTimes')}</th>
          <th className="p-2 font-medium">{t('lessonReportTableColumnTextQuality')}</th>
        </tr>
      </thead>
      <tbody>
        {scored.map((card) => {
          const norms = card.norms ?? [];
          const reactionTimes = card.reaction_times ?? [];
          const textQualityCount = textQualityFlaggedCount(card.text_quality);
          const verdict = card.pass_verdict ?? null;
          return (
            <tr key={card.session_id} className="border-b border-border/60 align-top" data-slot="lesson-report-row">
              <td className="p-2">{card.position}</td>
              <td className="p-2" data-slot="report-card-workstation">
                {card.workstation || t('lessonReportNormNone')}
              </td>
              <td className="p-2 tabular-nums">
                {card.score?.total_points} / {card.score?.total_max_points}
              </td>
              <td className="p-2 tabular-nums" data-slot="report-card-weight">
                {card.weight}
              </td>
              <td className="p-2 tabular-nums" data-slot="report-card-failed-rules">
                {card.failed_rule_count ?? t('lessonReportNormNone')}
              </td>
              <td className="p-2 tabular-nums" data-slot="report-card-critical-errors">
                {card.critical_error_count ?? t('lessonReportNormNone')}
              </td>
              <td className="p-2" data-slot="report-card-verdict">
                <span className={verdict && !verdict.passed ? 'font-medium text-destructive' : 'font-medium'}>
                  {passVerdictLabel(verdict)}
                </span>
                {verdict && verdict.failed_criteria.length > 0 ? (
                  <ul className="mt-0.5 flex flex-col gap-0.5 text-xs text-muted-foreground">
                    {failedCriteriaLines(verdict).map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                ) : null}
              </td>
              <td className="p-2">
                {norms.length === 0 ? (
                  t('lessonReportNormNone')
                ) : (
                  <ul className="flex flex-col gap-0.5 text-xs">
                    {norms.map((norm, index) => (
                      <NormLine key={`${norm.kind}-${norm.service_id ?? ''}-${index}`} norm={norm} />
                    ))}
                  </ul>
                )}
              </td>
              <td className="p-2" data-slot="report-card-reaction-times">
                {reactionTimes.length === 0 ? (
                  t('lessonReportNormNone')
                ) : (
                  <ul className="flex flex-col gap-0.5 text-xs">
                    {reactionTimes.map((reaction, index) => (
                      <ReactionTimeLine key={`${reaction.service_id ?? ''}-${index}`} reaction={reaction} />
                    ))}
                  </ul>
                )}
              </td>
              <td className="p-2 tabular-nums" data-slot="report-card-text-quality">
                {textQualityCount === null ? t('lessonReportNormNone') : textQualityCount}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
