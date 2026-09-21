import { useQuery } from '@tanstack/react-query';
import { AppShell } from '@/shared/ui/app-shell';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { getHealthReady, queryKeys } from '@/shared/api';
import { useAuthStore } from '@/entities/session';
import { LogoutButton } from '@/features/auth/logout-button';
import type { UserRole } from '@/shared/api';
import { CreateSessionForm } from './create-session-form';

const HEALTH_POLL_INTERVAL_MS = 5000;

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

/** Route: /instructor. Minimal create+start session flow (E8-A); live overview and report
 * release land in E17. */
export function InstructorPage() {
  const user = useAuthStore((state) => state.user);
  const readinessQuery = useQuery({
    queryKey: queryKeys.health.ready(),
    queryFn: getHealthReady,
    refetchInterval: HEALTH_POLL_INTERVAL_MS,
  });

  return (
    <AppShell
      title={t('instructorTitle')}
      userLabel={user?.display_name_ru}
      role={user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined}
      readiness={readinessQuery.data?.overall}
    >
      <div className="flex items-start justify-between gap-4">
        <h1 className="text-lg font-semibold tracking-tight">{t('instructorTitle')}</h1>
        <LogoutButton />
      </div>
      <div className="mt-4">
        <CreateSessionForm />
      </div>
    </AppShell>
  );
}
