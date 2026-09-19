import { PlaceholderPage } from '@/shared/ui/placeholder-page';
import { t } from '@/shared/i18n';

/** Route: /operator/*. Phone widget, incident card and services panel land in E8. */
export function OperatorPage() {
  return <PlaceholderPage title={t('operatorTitle')} owningEpic="E8" />;
}
