import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { AppShell } from '@/shared/ui/app-shell';
import { Button } from '@/shared/ui/button';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { getHealthReady, queryKeys } from '@/shared/api';
import { useAuthStore } from '@/entities/session';
import { LogoutButton } from '@/features/auth/logout-button';
import type { UserRole } from '@/shared/api';
import { CreateSessionForm } from './create-session-form';
import { InstructorSessionsList } from './instructor-sessions-list';

const HEALTH_POLL_INTERVAL_MS = 5000;

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

/** Route: /instructor. Minimal create+start session flow (E8-A) plus the sessions list linking
 * into the live overview (`/instructor/sessions/:sessionId`, E17-C) and, for a terminal session,
 * the report. */
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
        <nav className="flex items-center gap-2">
          <Button asChild variant="ghost" size="sm">
            <Link to="/instructor/lessons">{t('navLessonsLink')}</Link>
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link to="/instructor/scenarios">{t('navScenariosLink')}</Link>
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link to="/instructor/materials">{t('navMaterialsLink')}</Link>
          </Button>
          {/* I4 E33 (71 §71.10): per-trainee statistics and their CSV. */}
          <Button asChild variant="ghost" size="sm">
            <Link to="/instructor/statistics">{t('navStatisticsLink')}</Link>
          </Button>
          <LogoutButton />
        </nav>
      </div>
      <div className="mt-4 flex flex-col gap-4">
        <CreateSessionForm />
        <InstructorSessionsList />
      </div>
    </AppShell>
  );
}
