import { PlaceholderPage } from '@/shared/ui/placeholder-page';
import { t } from '@/shared/i18n';
import { useAuthStore } from '@/entities/session';

/** Route: /operator/*. Phone widget, incident card and services panel land in E8. */
export function OperatorPage() {
  // This route is TRAINEE-only (RequireRole), so the account role chip (D4) is always Стажёр.
  const userRole = useAuthStore((state) => state.user?.user_role);
  return <PlaceholderPage title={t('operatorTitle')} owningEpic="E8" role={userRole ? t('userRoleTrainee') : undefined} />;
}
