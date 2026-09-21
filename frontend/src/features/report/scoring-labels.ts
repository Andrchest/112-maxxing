// Exhaustive `ScoringCategory -> ru.ts key` table (D12 design decision #5, the same pattern
// `client.ts`'s `PROBLEM_MESSAGE_KEYS` and `features/dds/dds-labels.ts` already use):
// `Record<ScoringCategory, …>` fails `tsc` the moment `schema.d.ts` grows a new category and this
// file is not updated.
import { ru } from '@/shared/i18n/ru';
import { t } from '@/shared/i18n';
import type { ScoringCategory } from '@/shared/api';

export const SCORING_CATEGORY_LABEL_KEY: Record<ScoringCategory, keyof typeof ru> = {
  INFORMATION_GATHERING: 'scoringCategoryInformationGathering',
  CARD_QUALITY: 'scoringCategoryCardQuality',
  SERVICE_ROUTING: 'scoringCategoryServiceRouting',
  TIMELINESS: 'scoringCategoryTimeliness',
  WORKFLOW: 'scoringCategoryWorkflow',
  RESOURCE_MANAGEMENT: 'scoringCategoryResourceManagement',
  COMMUNICATION: 'scoringCategoryCommunication',
};

export function scoringCategoryLabelRu(value: ScoringCategory): string {
  return t(SCORING_CATEGORY_LABEL_KEY[value]);
}
