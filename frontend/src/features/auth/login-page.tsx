import { PlaceholderPage } from '@/shared/ui/placeholder-page';
import { t } from '@/shared/i18n';

/** Route: /login. Real JWT auth form lands in E7 (backend) / E8 (frontend). */
export function LoginPage() {
  return <PlaceholderPage title={t('loginTitle')} owningEpic="E8" />;
}
