// Route: /admin (I4 E30, HLD 71 §71.7; ТЗ ¶195-¶197, ¶205-¶209, ¶216, ¶289, ¶308). ADMIN only —
// the screens over E28's accounts backend and E29's monitoring backend. Six tabs, exactly as
// named by the design: Пользователи / Журнал / Статистика / Нагрузка / Ошибки / Оповещения.
// No new API: every tab is a thin read/write layer over the E28/E29 operations already in
// `shared/api/client.ts`.
import { useQuery } from '@tanstack/react-query';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/ui/tabs';
import { AppShell } from '@/shared/ui/app-shell';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { listAdminAlerts, queryKeys, type UserRole } from '@/shared/api';
import { useAuthStore } from '@/entities/session';
import { LogoutButton } from '@/features/auth/logout-button';
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
        <LogoutButton />
      </div>

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
