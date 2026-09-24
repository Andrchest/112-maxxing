// Route: /operator/register (I3 E4b, 70 §70.3.6). The 112 «реестр» (ui-check D-2): every card of
// the trainee's lessons on the 112 side. Opening a row goes to that session's existing
// `/operator/:sessionId` console — the same page/socket the console route already builds — never
// a new one built for this list.
import { AppShell } from '@/shared/ui/app-shell';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import type { UserRole } from '@/shared/api';
import { IncidentListScreen } from '@/features/lesson/incident-list-screen';

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

export function RegisterPage() {
  const user = useAuthStore((state) => state.user);
  const roleLabel = user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined;

  return (
    <AppShell
      title={t('registerPageTitle')}
      role={roleLabel}
      userLabel={user?.display_name_ru}
      connectionIndicatorHidden
    >
      <h1 className="text-lg font-semibold tracking-tight">{t('registerPageTitle')}</h1>
      <div className="mt-3">
        <IncidentListScreen roleType="OPERATOR_112" consoleBasePath="/operator" searchInputId="operator-register-search" />
      </div>
    </AppShell>
  );
}
