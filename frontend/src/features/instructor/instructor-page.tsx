import { PlaceholderPage } from '@/shared/ui/placeholder-page';
import { t } from '@/shared/i18n';

/** Route: /instructor/*. Minimal create+start session lands in E8; live
 * overview and report release land in E17. */
export function InstructorPage() {
  return <PlaceholderPage title={t('instructorTitle')} owningEpic="E8" />;
}
