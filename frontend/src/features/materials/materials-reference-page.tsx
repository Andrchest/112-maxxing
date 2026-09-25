// Route: /materials (I4 E34, HLD 71 §71.11, ТЗ ¶256). «Справочная база» — every authenticated
// role may open it; there is no per-trainee assignment yet (Q-E13-1 open), so every trainee sees
// the same unarchived list. Read-only: uploading and archiving are the instructor's own page
// (`/instructor/materials`).
import { AppShell } from '@/shared/ui/app-shell';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import type { UserRole } from '@/shared/api';
import { MaterialsList } from './materials-list';

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

export function MaterialsReferencePage() {
  const user = useAuthStore((state) => state.user);
  const roleLabel = user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined;

  return (
    <AppShell title={t('materialsTraineeTitle')} role={roleLabel} userLabel={user?.display_name_ru}>
      <h1 className="text-lg font-semibold tracking-tight">{t('materialsTraineeTitle')}</h1>
      <div className="mt-3">
        <MaterialsList canManage={false} />
      </div>
    </AppShell>
  );
}
