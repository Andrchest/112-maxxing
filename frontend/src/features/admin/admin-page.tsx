// Route: /admin (I4 E30, HLD 71 §71.7; ТЗ ¶195-¶197, ¶205-¶209, ¶216, ¶289, ¶308). ADMIN only —
// the screens over E28's accounts backend and E29's monitoring backend. Six tabs, exactly as
// named by the design: Пользователи / Журнал / Статистика / Нагрузка / Ошибки / Оповещения.
// No new API: every tab is a thin read/write layer over the E28/E29 operations already in
// `shared/api/client.ts`.
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/ui/tabs';
import { AppShell } from '@/shared/ui/app-shell';
import { Button } from '@/shared/ui/button';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { exportSettingsXml, listAdminAlerts, problemMessageRu, queryKeys, type ProblemCode, type UserRole } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { saveBlob } from '@/shared/lib/download';
import { useAuthStore } from '@/entities/session';
import { AdminAlertsBadge } from './admin-alerts-badge';
import { UsersTab } from './users-tab';
import { AuditLogTab } from './audit-log-tab';
import { UsageStatsTab } from './usage-stats-tab';
import { ServerLoadTab } from './server-load-tab';
import { ErrorsTab } from './errors-tab';
import { AlertsTab } from './alerts-tab';

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

export function AdminPage() {
  const user = useAuthStore((state) => state.user);
  // Same query key/fn `AlertsTab` uses below — TanStack Query dedupes and shares the one cache
  // entry, so this header badge causes no extra network traffic while that tab is open.
  const alertsQuery = useQuery({
    queryKey: queryKeys.admin.alerts(),
    queryFn: listAdminAlerts,
  });

  // I5 E37 (Q-E16-1): «Экспорт настроек (XML)» — the effective, non-secret settings; import is
  // CLI only (`make settings-import`, docs/RUNBOOK.md), there is no matching upload here.
  const [settingsDownloading, setSettingsDownloading] = useState(false);
  const [settingsDownloadError, setSettingsDownloadError] = useState<unknown>(null);

  async function handleSettingsExport() {
    setSettingsDownloading(true);
    setSettingsDownloadError(null);
    try {
      saveBlob(await exportSettingsXml(), 'settings.xml');
    } catch (error) {
      setSettingsDownloadError(error);
    } finally {
      setSettingsDownloading(false);
    }
  }

  return (
    <AppShell
      title={t('adminPageTitle')}
      role={user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined}
      userLabel={user?.display_name_ru}
      connectionIndicatorHidden
      adminAlertsBadge={<AdminAlertsBadge alerts={alertsQuery.data?.items ?? []} />}
    >
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-lg font-semibold tracking-tight">{t('adminPageTitle')}</h1>
        <div className="flex items-center gap-3">
          <Button type="button" variant="outline" size="sm" disabled={settingsDownloading} onClick={() => void handleSettingsExport()}>
            {settingsDownloading ? t('profileExportDownloading') : t('adminSettingsExportXmlButton')}
          </Button>
        </div>
      </div>
      {settingsDownloadError ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {settingsDownloadError instanceof ProblemError ? problemMessageRu(settingsDownloadError.code as ProblemCode) : t('problemUnknown')}
        </p>
      ) : null}

      <Tabs defaultValue="users" className="mt-4">
        <TabsList>
          <TabsTrigger value="users">{t('adminTabUsers')}</TabsTrigger>
          <TabsTrigger value="audit-log">{t('adminTabAuditLog')}</TabsTrigger>
          <TabsTrigger value="usage-stats">{t('adminTabUsageStats')}</TabsTrigger>
          <TabsTrigger value="server-load">{t('adminTabServerLoad')}</TabsTrigger>
          <TabsTrigger value="errors">{t('adminTabErrors')}</TabsTrigger>
          <TabsTrigger value="alerts">{t('adminTabAlerts')}</TabsTrigger>
        </TabsList>
        <TabsContent value="users" className="mt-4">
          <UsersTab />
        </TabsContent>
        <TabsContent value="audit-log" className="mt-4">
          <AuditLogTab />
        </TabsContent>
        <TabsContent value="usage-stats" className="mt-4">
          <UsageStatsTab />
        </TabsContent>
        <TabsContent value="server-load" className="mt-4">
          <ServerLoadTab />
        </TabsContent>
        <TabsContent value="errors" className="mt-4">
          <ErrorsTab />
        </TabsContent>
        <TabsContent value="alerts" className="mt-4">
          <AlertsTab />
        </TabsContent>
      </Tabs>
    </AppShell>
  );
}
