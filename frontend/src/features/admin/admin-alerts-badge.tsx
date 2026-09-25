// I4 E30 (71 §71.7): "the app shell shows an alerts badge for ADMIN". Purely presentational (same
// discipline `AppShell` itself documents) — `AdminPage` is the only caller, and it is the layer
// that fetches `listAdminAlerts` and hands the result down here.
import { Badge } from '@/shared/ui/badge';
import { t } from '@/shared/i18n';
import type { AdminAlertView } from '@/shared/api';

interface AdminAlertsBadgeProps {
  alerts: AdminAlertView[];
}

export function AdminAlertsBadge({ alerts }: AdminAlertsBadgeProps) {
  if (alerts.length === 0) {
    return (
      <Badge variant="outline" className="font-mono text-xs" data-slot="admin-alerts-badge">
        {t('adminAlertsBadgeNone')}
      </Badge>
    );
  }

  return (
    <Badge variant="destructive" className="font-mono text-xs" data-slot="admin-alerts-badge">
      {t('adminAlertsBadgeLabel')}: {alerts.length}
    </Badge>
  );
}
