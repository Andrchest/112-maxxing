// «Статистика» tab (I4 E30, 71 §71.7 → E29, 71 §71.6): per-day counts of logins, sessions,
// lessons and active users (`getUsageStats`, Q-E14-3 confirms only the metric set — the set itself
// is built as proposed). An absent `from`/`to` uses the server's own 30-day default window.
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { t } from '@/shared/i18n';
import { ProblemError } from '@/shared/lib/api';
import { getUsageStats, problemMessageRu, queryKeys, type ProblemCode } from '@/shared/api';

function dayStartIso(day: string): string | undefined {
  return day ? new Date(`${day}T00:00:00`).toISOString() : undefined;
}

function problemText(error: unknown): string {
  return error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
}

export function UsageStatsTab() {
  const [fromDay, setFromDay] = useState('');
  const [toDay, setToDay] = useState('');
  const from = dayStartIso(fromDay);
  const to = dayStartIso(toDay);

  const usageQuery = useQuery({
    queryKey: queryKeys.admin.usageStats(from, to),
    queryFn: () => getUsageStats({ from, to }),
  });

  const days = usageQuery.data?.days ?? [];

  return (
    <Card data-slot="admin-usage-stats">
      <CardHeader className="flex flex-row flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="admin-usage-from">{t('adminUsageFromLabel')}</Label>
          <Input id="admin-usage-from" type="date" value={fromDay} onChange={(event) => setFromDay(event.target.value)} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="admin-usage-to">{t('adminUsageToLabel')}</Label>
          <Input id="admin-usage-to" type="date" value={toDay} onChange={(event) => setToDay(event.target.value)} />
        </div>
      </CardHeader>
      <CardContent>
        {usageQuery.isLoading ? <p className="text-sm text-muted-foreground">{t('adminUsageLoading')}</p> : null}
        {usageQuery.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(usageQuery.error)}
          </p>
        ) : null}
        {usageQuery.data && days.length === 0 ? <p className="text-sm text-muted-foreground">{t('adminUsageEmpty')}</p> : null}
        {days.length > 0 ? (
          <table className="w-full border-collapse text-sm" data-slot="admin-usage-table">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="p-2 font-medium">{t('adminUsageColumnDate')}</th>
                <th className="p-2 font-medium">{t('adminUsageColumnLogins')}</th>
                <th className="p-2 font-medium">{t('adminUsageColumnSessions')}</th>
                <th className="p-2 font-medium">{t('adminUsageColumnLessons')}</th>
                <th className="p-2 font-medium">{t('adminUsageColumnActiveUsers')}</th>
              </tr>
            </thead>
            <tbody>
              {days.map((day) => (
                <tr key={day.date} className="border-b border-border/60" data-slot="admin-usage-row">
                  <td className="p-2 tabular-nums">{day.date}</td>
                  <td className="p-2 tabular-nums">{day.logins}</td>
                  <td className="p-2 tabular-nums">{day.sessions}</td>
                  <td className="p-2 tabular-nums">{day.lessons}</td>
                  <td className="p-2 tabular-nums">{day.active_users}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </CardContent>
    </Card>
  );
}
