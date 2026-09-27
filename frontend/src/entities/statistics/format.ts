// I4 E33 (71 §71.10): the display helpers `features/statistics` and `features/history` share (an
// entity, so neither feature imports the other). Exhaustive `ScoringCategory -> ru.ts key` table —
// the same keys `features/report/scoring-labels.ts` uses — so `tsc` fails the moment
// `schema.d.ts` grows a category this file does not name. Display only: every number is the
// server's (D11), at most rounded here.
import { ru } from '@/shared/i18n/ru';
import { t } from '@/shared/i18n';
import { formatCallDurationMs } from '@/entities/call';
import type { ScoringCategory } from '@/shared/api';

const SCORING_CATEGORY_LABEL_KEY: Record<ScoringCategory, keyof typeof ru> = {
  INFORMATION_GATHERING: 'scoringCategoryInformationGathering',
  CARD_QUALITY: 'scoringCategoryCardQuality',
  SERVICE_ROUTING: 'scoringCategoryServiceRouting',
  TIMELINESS: 'scoringCategoryTimeliness',
  WORKFLOW: 'scoringCategoryWorkflow',
  RESOURCE_MANAGEMENT: 'scoringCategoryResourceManagement',
  COMMUNICATION: 'scoringCategoryCommunication',
};

export function categoryLabelRu(category: string): string {
  const key = SCORING_CATEGORY_LABEL_KEY[category as ScoringCategory];
  return key ? t(key) : category;
}

/** A stored percent for display: rounded to a whole percent, `—` when there is none. */
export function formatPercent(value: number | null): string {
  return value === null ? t('statisticsNoValue') : `${Math.round(value)}%`;
}

/** A deviation from a norm: `+00:12` late / `−00:18` early (whole seconds, as the call timer). */
export function formatDeviationMs(deviationMs: number): string {
  const rounded = Math.round(deviationMs);
  const sign = rounded > 0 ? '+' : rounded < 0 ? '−' : '';
  return `${sign}${formatCallDurationMs(Math.abs(rounded))}`;
}

/** A mean deviation, `—` when nothing was measured. */
export function formatMeanDeviationMs(value: number | null): string {
  return value === null ? t('statisticsNoValue') : formatDeviationMs(value);
}

/** (I5 E36, Q-E12-1) A mean reaction time: a plain duration, no +/− sign (it is not a deviation
 * from a norm) — `—` when nothing was measured. */
export function formatMeanDurationMs(value: number | null): string {
  return value === null ? t('statisticsNoValue') : formatCallDurationMs(Math.round(value));
}

/** `failed_rules_by_category` as «Категория: N» pairs, in the server's order. */
export function failedRulesLines(byCategory: Record<string, number>): string[] {
  return Object.entries(byCategory)
    .filter(([, count]) => count > 0)
    .map(([category, count]) => `${categoryLabelRu(category)}: ${count}`);
}
