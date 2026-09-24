// Route: /dds/incidents (I3 E4b, 70 §70.3.6). The ДДС «Список происшествий» (ui-check D-8): every
// card of the trainee's lessons where their ДДС stage has arrived (`listMyIncidents` already
// filters to `ACTIVE`-or-terminal sessions server-side). Opening a row goes to that session's
// existing `/dds/:sessionId` console — the same page/socket the console route already builds —
// never a new one built for this list.
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

export function DdsIncidentListPage() {
  const user = useAuthStore((state) => state.user);
  const roleLabel = user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined;

  return (
    <AppShell
      title={t('ddsIncidentListPageTitle')}
      role={roleLabel}
      userLabel={user?.display_name_ru}
      connectionIndicatorHidden
      referenceTheme
    >
      <h1 className="text-lg font-semibold tracking-tight">{t('ddsIncidentListPageTitle')}</h1>
      <div className="mt-3">
        <IncidentListScreen roleType="DDS" consoleBasePath="/dds" searchInputId="dds-incident-search" />
      </div>
    </AppShell>
  );
}
