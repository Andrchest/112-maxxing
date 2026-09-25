import { describe, expect, it } from 'vitest';
import { categoryLabelRu, failedRulesLines, formatDeviationMs, formatMeanDeviationMs, formatPercent } from './format';
import { ru } from '@/shared/i18n/ru';

// I4 E33 (71 §71.10): display only — a missing value is a dash, never a zero.
describe('statistics display helpers', () => {
  it('signs a deviation: late is +, early is −, on time has no sign', () => {
    expect(formatDeviationMs(12_000)).toBe('+00:12');
    expect(formatDeviationMs(-65_000)).toBe('−01:05');
    expect(formatDeviationMs(0)).toBe('00:00');
    expect(formatMeanDeviationMs(null)).toBe(ru.statisticsNoValue);
  });

  it('rounds a percent for display and dashes a missing one', () => {
    expect(formatPercent(72.5)).toBe('73%');
    expect(formatPercent(0)).toBe('0%');
    expect(formatPercent(null)).toBe(ru.statisticsNoValue);
  });

  it('names each category with a failure', () => {
    expect(categoryLabelRu('TIMELINESS')).toBe(ru.scoringCategoryTimeliness);
    expect(categoryLabelRu('SOMETHING_NEW')).toBe('SOMETHING_NEW');
    expect(failedRulesLines({ WORKFLOW: 1, TIMELINESS: 0 })).toEqual([`${ru.scoringCategoryWorkflow}: 1`]);
  });
});
