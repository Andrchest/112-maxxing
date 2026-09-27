// I5 E38 (Q-E9b-3 variant г): the display helpers `features/report`, `features/lesson` and
// `features/statistics` share for «сдал / не сдал» (an entity, so no feature imports another).
// Display only: the verdict, its failed criteria and every number are the server's
// (`PassVerdictView`, derived from the stored score, D11) — nothing is judged here.
import { t } from '@/shared/i18n';
import { formatPercent } from '@/entities/statistics';
import type { PassCriteriaView, PassCriterion, PassVerdictView } from '@/shared/api';

/** «Сдал» / «Не сдал», or «—» for a card with no verdict (unscored / aborted). */
export function passVerdictLabel(verdict: PassVerdictView | null | undefined): string {
  if (!verdict) return t('passVerdictNone');
  return verdict.passed ? t('passVerdictPassed') : t('passVerdictFailed');
}

/** A verdict percent, truncated (never rounded up) to one decimal with a decimal comma — so a
 * card that missed a 70 % threshold never reads «70%». */
export function formatVerdictPercent(value: number | null): string {
  if (value === null) return t('statisticsNoValue');
  // The epsilon keeps a float like 57.3 (572.999… tenths) from truncating to 57.2.
  const truncated = Math.floor(value * 10 + 1e-9) / 10;
  return `${Number.isInteger(truncated) ? truncated : truncated.toFixed(1).replace('.', ',')}%`;
}

function failedCriterionLine(criterion: PassCriterion, verdict: PassVerdictView): string {
  const { criteria } = verdict;
  switch (criterion) {
    case 'MIN_SCORE_PERCENT':
      return `${t('passVerdictCriterionMinScore')}: ${formatVerdictPercent(verdict.score_percent)} (${t('passVerdictThreshold')} ${criteria.min_score_percent ?? t('statisticsNoValue')}%)`;
    case 'MAX_FAILED_RULES':
      return `${t('passVerdictCriterionMaxFailedRules')}: ${verdict.failed_rule_count} (${t('passVerdictAllowed')} ${criteria.max_failed_rules ?? t('statisticsNoValue')})`;
    case 'CRITICAL_ERRORS':
      return `${t('passVerdictCriterionCriticalErrors')}: ${verdict.critical_error_count}`;
  }
}

/** Which enabled criteria did not hold, one line each, in the server's order. */
export function failedCriteriaLines(verdict: PassVerdictView): string[] {
  return verdict.failed_criteria.map((criterion) => failedCriterionLine(criterion, verdict));
}

/** The criteria the session was judged by, one line per enabled criterion. */
export function criteriaLines(criteria: PassCriteriaView): string[] {
  const lines: string[] = [];
  if (criteria.min_score_percent !== null) {
    lines.push(`${t('passVerdictCriteriaMinScore')} ${criteria.min_score_percent}%`);
  }
  if (criteria.max_failed_rules !== null) {
    lines.push(`${t('passVerdictCriteriaMaxFailedRules')} ${criteria.max_failed_rules}`);
  }
  if (criteria.fail_on_critical) lines.push(t('passVerdictCriteriaNoCritical'));
  return lines;
}

/** «N (P%)» — the sessions judged «сдал» and their share; «—» when the server sent none. */
export function formatPassCount(count: number | undefined, rate: number | null | undefined): string {
  if (count === undefined) return t('statisticsNoValue');
  return `${count} (${formatPercent(rate ?? null)})`;
}
