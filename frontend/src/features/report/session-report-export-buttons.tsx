// I7 E46b (owner item 6): the session report has no CSV, so it goes straight to «Скачать Excel» /
// «Скачать PDF» (`getSessionReportExport`, same access as `getSessionReport`) — same shape as
// `DownloadLessonReportCsvButton` (`../lesson/lesson-report-table.tsx`), minus the CSV button this
// report never had.
import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { t } from '@/shared/i18n';
import { getSessionReportExport, problemMessageRu, type ProblemCode, type ReportFileFormat } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { downloadBlob, reportDownloadFailed } from '@/shared/lib/download';

const EXPORT_FORMATS: ReadonlyArray<Extract<ReportFileFormat, 'xlsx' | 'pdf'>> = ['xlsx', 'pdf'];

function exportLabel(format: 'xlsx' | 'pdf'): string {
  return format === 'xlsx' ? t('reportDownloadExcel') : t('reportDownloadPdf');
}

export function SessionReportExportButtons({ sessionId }: { sessionId: string }) {
  const [busyFormat, setBusyFormat] = useState<'xlsx' | 'pdf' | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function handleDownload(format: 'xlsx' | 'pdf') {
    setBusyFormat(format);
    setError(null);
    const fileName = `session-${sessionId}-report.${format}`;
    try {
      downloadBlob(await getSessionReportExport(sessionId, format), fileName);
    } catch (caught) {
      setError(caught);
      reportDownloadFailed(fileName, caught);
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
