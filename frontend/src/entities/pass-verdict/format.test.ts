import { describe, expect, it } from 'vitest';
import { criteriaLines, failedCriteriaLines, formatPassCount, formatVerdictPercent, passVerdictLabel } from './format';
import { ru } from '@/shared/i18n/ru';
import type { PassVerdictView } from '@/shared/api';

const FAILED: PassVerdictView = {
  passed: false,
  failed_criteria: ['MIN_SCORE_PERCENT', 'MAX_FAILED_RULES', 'CRITICAL_ERRORS'],
  criteria: { min_score_percent: 70, max_failed_rules: 2, fail_on_critical: true },
  score_percent: 69.96,
  failed_rule_count: 3,
  critical_error_count: 1,
};

// I5 E38 (Q-E9b-3): display only — the verdict and its numbers are the server's.
describe('pass verdict display helpers', () => {
  it('labels a verdict, and dashes a card without one', () => {
    expect(passVerdictLabel({ ...FAILED, passed: true, failed_criteria: [] })).toBe(ru.passVerdictPassed);
    expect(passVerdictLabel(FAILED)).toBe(ru.passVerdictFailed);
    expect(passVerdictLabel(null)).toBe(ru.passVerdictNone);
    expect(passVerdictLabel(undefined)).toBe('—');
  });

  it('never rounds a missed threshold up to it', () => {
    expect(formatVerdictPercent(69.96)).toBe('69,9%');
    expect(formatVerdictPercent(70)).toBe('70%');
    expect(formatVerdictPercent(null)).toBe(ru.statisticsNoValue);
  });

  it('names each failed criterion with its numbers', () => {
    expect(failedCriteriaLines(FAILED)).toEqual([
      `${ru.passVerdictCriterionMinScore}: 69,9% (${ru.passVerdictThreshold} 70%)`,
      `${ru.passVerdictCriterionMaxFailedRules}: 3 (${ru.passVerdictAllowed} 2)`,
      `${ru.passVerdictCriterionCriticalErrors}: 1`,
    ]);
  });

  it('lists only the enabled criteria', () => {
    expect(criteriaLines(FAILED.criteria)).toEqual([
      `${ru.passVerdictCriteriaMinScore} 70%`,
      `${ru.passVerdictCriteriaMaxFailedRules} 2`,
      ru.passVerdictCriteriaNoCritical,
    ]);
    expect(criteriaLines({ min_score_percent: null, max_failed_rules: null, fail_on_critical: true })).toEqual([
      ru.passVerdictCriteriaNoCritical,
    ]);
  });

  it('formats a pass count with its share', () => {
    expect(formatPassCount(3, 60)).toBe('3 (60%)');
    expect(formatPassCount(0, null)).toBe(`0 (${ru.statisticsNoValue})`);
    expect(formatPassCount(undefined, undefined)).toBe(ru.statisticsNoValue);
  });
});
