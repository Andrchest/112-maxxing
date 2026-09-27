// I5 E38 (Q-E9b-3 variant г): «сдал / не сдал»'s three criteria as the instructor types them —
// shared by the single-session form (`SessionCreateRequest.pass_criteria`) and the lesson form
// (`LessonCreateRequest.pass_criteria`, every card). A criterion is on when its box is ticked;
// the two numeric ones take a whole number (percent 0…100, failed rules ≥ 0). The server's
// defaults are the form's starting point (70 %, no failed-rule limit, a critical error fails),
// and a form left at them sends no `pass_criteria` at all — the request is byte-identical to
// before this epic, and the server records the same defaults.
import type { PassCriteriaRequest } from '@/shared/api';

export interface PassCriteriaDraft {
  minScoreOn: boolean;
  minScore: string;
  maxFailedOn: boolean;
  maxFailed: string;
  failOnCritical: boolean;
}

export const DEFAULT_PASS_CRITERIA_DRAFT: PassCriteriaDraft = {
  minScoreOn: true,
  minScore: '70',
  maxFailedOn: false,
  maxFailed: '',
  failOnCritical: true,
};

function wholeNumber(value: string): number | null {
  const trimmed = value.trim();
  return /^\d+$/.test(trimmed) ? Number(trimmed) : null;
}

/** The threshold field is fine: off, or a whole percent 0…100. */
export function minScoreValid(draft: PassCriteriaDraft): boolean {
  if (!draft.minScoreOn) return true;
  const percent = wholeNumber(draft.minScore);
  return percent !== null && percent <= 100;
}

/** The failed-rule limit field is fine: off, or a whole number ≥ 0. */
export function maxFailedValid(draft: PassCriteriaDraft): boolean {
  return !draft.maxFailedOn || wholeNumber(draft.maxFailed) !== null;
}

/** Why the draft cannot be sent: every criterion off, or an enabled number out of range. */
export function passCriteriaProblem(draft: PassCriteriaDraft): 'NONE_ENABLED' | 'INVALID_VALUE' | null {
  if (!draft.minScoreOn && !draft.maxFailedOn && !draft.failOnCritical) return 'NONE_ENABLED';
  if (!minScoreValid(draft) || !maxFailedValid(draft)) return 'INVALID_VALUE';
  return null;
}

/** `{ pass_criteria }` for the request, or `{}` when the draft is the server's defaults. */
export function passCriteriaField(draft: PassCriteriaDraft): { pass_criteria?: PassCriteriaRequest } {
  const criteria: PassCriteriaRequest = {
    min_score_percent: draft.minScoreOn ? wholeNumber(draft.minScore) : null,
    max_failed_rules: draft.maxFailedOn ? wholeNumber(draft.maxFailed) : null,
    fail_on_critical: draft.failOnCritical,
  };
  const isDefault = criteria.min_score_percent === 70 && criteria.max_failed_rules === null && criteria.fail_on_critical;
  return isDefault ? {} : { pass_criteria: criteria };
}
