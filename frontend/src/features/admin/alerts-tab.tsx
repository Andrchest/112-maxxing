// «Оповещения» tab (I4 E30, 71 §71.7 → E29, 71 §71.6): current alerts (`listAdminAlerts`, derived
// not stored — ТЗ ¶308) plus the backup status (`getBackupStatus`, ТЗ ¶143/¶216). The design
// places the backup status "on the admin page" without naming a tab (71 §71.7); this tab is the
// natural home for it — both are E29's derived monitoring reads a technical grouping choice, not
// a product one.
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { ProblemError } from '@/shared/lib/api';
import { formatTimestampRu } from '@/shared/lib/format-timestamp';
import { getBackupStatus, listAdminAlerts, problemMessageRu, queryKeys, type AdminAlertView, type ProblemCode } from '@/shared/api';

const ALERT_KIND_LABEL_KEY: Record<AdminAlertView['kind'], keyof typeof ru> = {
  INFERENCE_FATAL: 'adminAlertsKindInferenceFatal',
  BACKUP_STALE: 'adminAlertsKindBackupStale',
  BACKUP_FAILED: 'adminAlertsKindBackupFailed',
  LOGIN_FAILURES: 'adminAlertsKindLoginFailures',
};

function problemText(error: unknown): string {
  return error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
}

/** Bytes -> whole megabytes, `null` -> «нет данных» (same SPEC §27 rule the load tab uses — a
 * backup size the server never recorded is not a real zero). */
function formatBytesMb(bytes: number | null): string {
  if (bytes === null) return t('adminNoData');
  return `${Math.round(bytes / 1_000_000)} ${t('adminUnitMb')}`;
}

function BackupStatusCard() {
  const backupQuery = useQuery({
    queryKey: queryKeys.admin.backupStatus(),
    queryFn: getBackupStatus,
  });
  const backup = backupQuery.data;

  return (
    <Card data-slot="admin-backup-status">
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('adminBackupStatusTitle')}</h2>
      </CardHeader>
      <CardContent>
        {backupQuery.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(backupQuery.error)}
          </p>
        ) : null}
        {backup && !backup.available ? <p className="text-sm text-muted-foreground">{t('adminBackupStatusUnavailable')}</p> : null}
        {backup?.available ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted-foreground">{t('adminBackupStatusStatusLabel')}</dt>
            <dd>{backup.status === 'FAILED' ? t('adminBackupStatusStatusFailed') : t('adminBackupStatusStatusOk')}</dd>
            <dt className="text-muted-foreground">{t('adminBackupStatusFinishedAtLabel')}</dt>
            <dd className="tabular-nums">{backup.finished_at ? formatTimestampRu(backup.finished_at) : t('statisticsNoValue')}</dd>
            <dt className="text-muted-foreground">{t('adminBackupStatusDatabaseSizeLabel')}</dt>
            <dd className="tabular-nums">{formatBytesMb(backup.database_bytes)}</dd>
            <dt className="text-muted-foreground">{t('adminBackupStatusRecordingsSizeLabel')}</dt>
            <dd className="tabular-nums">{formatBytesMb(backup.recordings_bytes)}</dd>
          </dl>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function AlertsTab() {
  // Same query key/fn `AdminPage`'s header badge uses — one shared cache entry (TanStack Query).
  const alertsQuery = useQuery({
    queryKey: queryKeys.admin.alerts(),
    queryFn: listAdminAlerts,
  });
  const alerts = alertsQuery.data?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <Card data-slot="admin-alerts">
        <CardContent className="pt-4">
          {alertsQuery.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {problemText(alertsQuery.error)}
            </p>
          ) : null}
          {alertsQuery.data && alerts.length === 0 ? <p className="text-sm text-muted-foreground">{t('adminAlertsEmpty')}</p> : null}
          {alerts.length > 0 ? (
            <ul className="flex flex-col gap-2">
              {alerts.map((alert, index) => (
                <li
                  key={`${alert.kind}-${index}`}
                  className="rounded-md border border-border p-2 text-sm"
                  data-slot="admin-alert-row"
                >
                  <p className="font-medium">{t(ALERT_KIND_LABEL_KEY[alert.kind])}</p>
                  <p className="text-xs text-muted-foreground">
                    {t('adminAlertsSinceLabel')} {formatTimestampRu(alert.since)}
                  </p>
                  <p>{alert.detail_ru}</p>
                </li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>
      <BackupStatusCard />
    </div>
  );
}
