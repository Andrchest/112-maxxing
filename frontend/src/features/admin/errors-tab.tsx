// «Ошибки» tab (I4 E30, 71 §71.7 → E29, 71 §71.6): `getErrorReport` (ТЗ ¶207) — backend error-log
// records, `MODEL_ERROR` session events and FATAL inference transitions merged, newest first. A
// record with a `session_id` links to that session's report.
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { ProblemError } from '@/shared/lib/api';
import { formatTimestampRu } from '@/shared/lib/format-timestamp';
import { getErrorReport, problemMessageRu, queryKeys, type ErrorRecordView, type ProblemCode } from '@/shared/api';

const SOURCE_LABEL_KEY: Record<ErrorRecordView['source'], keyof typeof ru> = {
  BACKEND_LOG: 'adminErrorsSourceBackendLog',
  VOICE_AGENT_LOG: 'adminErrorsSourceVoiceAgentLog', // additive, I7 E51 (G6)
  SIP_GATEWAY_LOG: 'adminErrorsSourceSipGatewayLog', // additive, I7 E51 (G6)
  MODEL_ERROR: 'adminErrorsSourceModelError',
  INFERENCE_FATAL: 'adminErrorsSourceInferenceFatal',
};

function dayStartIso(day: string): string | undefined {
  return day ? new Date(`${day}T00:00:00`).toISOString() : undefined;
}

function problemText(error: unknown): string {
  return error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
}

export function ErrorsTab() {
  const [fromDay, setFromDay] = useState('');
  const [toDay, setToDay] = useState('');
  const from = dayStartIso(fromDay);
  const to = dayStartIso(toDay);

  const errorsQuery = useQuery({
    queryKey: queryKeys.admin.errors(from, to),
    queryFn: () => getErrorReport({ from, to }),
  });

  const items = errorsQuery.data?.items ?? [];

  return (
    <Card data-slot="admin-errors">
      <CardHeader className="flex flex-row flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="admin-errors-from">{t('adminErrorsFromLabel')}</Label>
          <Input id="admin-errors-from" type="date" value={fromDay} onChange={(event) => setFromDay(event.target.value)} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="admin-errors-to">{t('adminErrorsToLabel')}</Label>
          <Input id="admin-errors-to" type="date" value={toDay} onChange={(event) => setToDay(event.target.value)} />
        </div>
      </CardHeader>
      <CardContent>
        {errorsQuery.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(errorsQuery.error)}
          </p>
        ) : null}
        {errorsQuery.data && items.length === 0 ? <p className="text-sm text-muted-foreground">{t('adminErrorsEmpty')}</p> : null}
        {items.length > 0 ? (
          <table className="w-full border-collapse text-sm" data-slot="admin-errors-table">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="p-2 font-medium">{t('adminErrorsColumnTime')}</th>
                <th className="p-2 font-medium">{t('adminErrorsColumnSource')}</th>
                <th className="p-2 font-medium">{t('adminErrorsColumnMessage')}</th>
                <th className="p-2 font-medium">{t('adminErrorsColumnSession')}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((record, index) => (
                <tr key={`${record.ts}-${index}`} className="border-b border-border/60 align-top" data-slot="admin-error-row">
                  <td className="p-2 tabular-nums">{formatTimestampRu(record.ts)}</td>
                  <td className="p-2">{t(SOURCE_LABEL_KEY[record.source])}</td>
                  <td className="p-2">{record.message}</td>
                  <td className="p-2">
                    {record.session_id ? (
                      <Link className="text-primary underline-offset-2 hover:underline" to={`/report/${record.session_id}`}>
                        {t('adminErrorsOpenSession')}
                      </Link>
                    ) : (
                      t('statisticsNoValue')
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </CardContent>
    </Card>
  );
}
