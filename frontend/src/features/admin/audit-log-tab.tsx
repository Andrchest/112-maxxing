// «Журнал» tab (I4 E30, 71 §71.7 → E29, 71 §71.6): pages `listAuditLog`, newest first. Filters by
// action and a `completed_at`-style date window (`from` inclusive, `to` exclusive, like the E33
// statistics filter); `user_id` is left to a future pass — the server accepts it, but this tab has
// no user picker of its own yet (a technical simplification, not a product choice).
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { ProblemError } from '@/shared/lib/api';
import { formatTimestampRu } from '@/shared/lib/format-timestamp';
import { listAuditLog, problemMessageRu, queryKeys, type AuditAction, type AuditOutcome, type ProblemCode } from '@/shared/api';

const ACTION_LABEL_KEY: Record<AuditAction, keyof typeof ru> = {
  HTTP_REQUEST: 'adminAuditActionHttpRequest',
  LOGIN_SUCCEEDED: 'adminAuditActionLoginSucceeded',
  LOGIN_FAILED: 'adminAuditActionLoginFailed',
  ACCESS_DENIED: 'adminAuditActionAccessDenied',
  WS_CONNECTED: 'adminAuditActionWsConnected',
};
const ACTIONS: AuditAction[] = ['HTTP_REQUEST', 'LOGIN_SUCCEEDED', 'LOGIN_FAILED', 'ACCESS_DENIED', 'WS_CONNECTED'];

const OUTCOME_LABEL_KEY: Record<AuditOutcome, keyof typeof ru> = {
  OK: 'adminAuditOutcomeOk',
  DENIED: 'adminAuditOutcomeDenied',
  ERROR: 'adminAuditOutcomeError',
};

const PAGE_SIZE = 50;

function dayStartIso(day: string): string | undefined {
  return day ? new Date(`${day}T00:00:00`).toISOString() : undefined;
}

function problemText(error: unknown): string {
  return error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
}

export function AuditLogTab() {
  const [action, setAction] = useState<AuditAction | ''>('');
  const [fromDay, setFromDay] = useState('');
  const [toDay, setToDay] = useState('');
  const [offset, setOffset] = useState(0);

  const from = dayStartIso(fromDay);
  const to = dayStartIso(toDay);

  const auditQuery = useQuery({
    queryKey: queryKeys.admin.auditLog(undefined, action || undefined, from, to, offset),
    queryFn: () => listAuditLog({ action: action || undefined, from, to, limit: PAGE_SIZE, offset }),
  });

  const items = auditQuery.data?.items ?? [];
  const total = auditQuery.data?.total ?? 0;

  return (
    <Card data-slot="admin-audit-log">
      <CardHeader className="flex flex-row flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="admin-audit-action">{t('adminAuditFilterActionLabel')}</Label>
          <select
            id="admin-audit-action"
            className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            value={action}
            onChange={(event) => {
              setOffset(0);
              setAction(event.target.value as AuditAction | '');
            }}
          >
            <option value="">{t('adminAuditFilterActionAll')}</option>
            {ACTIONS.map((candidate) => (
              <option key={candidate} value={candidate}>
                {t(ACTION_LABEL_KEY[candidate])}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="admin-audit-from">{t('adminAuditFilterFromLabel')}</Label>
          <Input
            id="admin-audit-from"
            type="date"
            value={fromDay}
            onChange={(event) => {
              setOffset(0);
              setFromDay(event.target.value);
            }}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="admin-audit-to">{t('adminAuditFilterToLabel')}</Label>
          <Input
            id="admin-audit-to"
            type="date"
            value={toDay}
            onChange={(event) => {
              setOffset(0);
              setToDay(event.target.value);
            }}
          />
        </div>
      </CardHeader>
      <CardContent>
        {auditQuery.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(auditQuery.error)}
          </p>
        ) : null}
        {auditQuery.data && items.length === 0 ? <p className="text-sm text-muted-foreground">{t('adminAuditEmpty')}</p> : null}
        {items.length > 0 ? (
          <table className="w-full border-collapse text-sm" data-slot="admin-audit-table">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="p-2 font-medium">{t('adminAuditColumnTime')}</th>
                <th className="p-2 font-medium">{t('adminAuditColumnUser')}</th>
                <th className="p-2 font-medium">{t('adminAuditColumnAction')}</th>
                <th className="p-2 font-medium">{t('adminAuditColumnRequest')}</th>
                <th className="p-2 font-medium">{t('adminAuditColumnStatus')}</th>
                <th className="p-2 font-medium">{t('adminAuditColumnOutcome')}</th>
                <th className="p-2 font-medium">{t('adminAuditColumnIp')}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((entry) => (
                <tr key={entry.id} className="border-b border-border/60" data-slot="admin-audit-row">
                  <td className="p-2 tabular-nums">{formatTimestampRu(entry.ts)}</td>
                  <td className="p-2">{entry.role ?? entry.user_id ?? t('statisticsNoValue')}</td>
                  <td className="p-2">{t(ACTION_LABEL_KEY[entry.action])}</td>
                  <td className="p-2 font-mono text-xs">
                    {entry.method} {entry.path_template}
                  </td>
                  <td className="p-2 tabular-nums">{entry.status}</td>
                  <td className="p-2">{t(OUTCOME_LABEL_KEY[entry.outcome])}</td>
                  <td className="p-2 font-mono text-xs">{entry.client_ip ?? t('statisticsNoValue')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {total > offset + items.length ? (
          <div className="mt-2">
            <Button type="button" size="sm" variant="outline" onClick={() => setOffset(offset + PAGE_SIZE)}>
              {t('adminAuditLoadMore')}
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
