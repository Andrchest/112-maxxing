import { PlaceholderPage } from '@/shared/ui/placeholder-page';
import { t } from '@/shared/i18n';
import { useAuthStore } from '@/entities/session';

/** Route: /dds/*. Work item, resource board and dispatch UI land in E10. */
export function DdsPage() {
  // This route is TRAINEE-only (RequireRole), so the account role chip (D4) is always Стажёр.
  const userRole = useAuthStore((state) => state.user?.user_role);
  return <PlaceholderPage title={t('ddsTitle')} owningEpic="E10" role={userRole ? t('userRoleTrainee') : undefined} />;
}
