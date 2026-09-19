import { PlaceholderPage } from '@/shared/ui/placeholder-page';
import { t } from '@/shared/i18n';

/** Route: /report/*. Full post-session report UI (SPEC §29) lands in E16. */
export function ReportPage() {
  return <PlaceholderPage title={t('reportTitle')} owningEpic="E16" />;
}
