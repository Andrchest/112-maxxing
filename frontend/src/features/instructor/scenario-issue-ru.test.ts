import { describe, expect, it } from 'vitest';
import { ru } from '@/shared/i18n/ru';
import { scenarioIssueMessageRu } from './scenario-issue-ru';

// I7 E53 (G19): Russian scenario validation messages, keyed by rule number.
describe('scenarioIssueMessageRu', () => {
  it('has a Russian template for every rule the backend registers (R1-R44)', () => {
    for (let rule = 1; rule <= 44; rule += 1) {
      const text = scenarioIssueMessageRu({ rule_number: rule, severity: 'ERROR', location: 'x', message: 'english' });
      expect(text).not.toBe('english');
      expect(text).toMatch(/[Ѐ-ӿ]/);
    }
  });

  it('keeps the English text for an unknown rule number', () => {
    expect(scenarioIssueMessageRu({ rule_number: 77, severity: 'ERROR', location: 'x', message: 'english' })).toBe('english');
  });

  it('translates the caller-belief warning and keeps any other warning as sent', () => {
    const belief = "world_events['e1']: MUTATE_CALLER_BELIEF on an event with caller_observable=false is dropped at runtime (D7)";
    expect(scenarioIssueMessageRu({ rule_number: 1, severity: 'WARNING', location: 'x', message: belief })).toBe(
      ru.scenarioIssueWarningCallerBelief,
    );
    expect(scenarioIssueMessageRu({ rule_number: 1, severity: 'WARNING', location: 'x', message: 'other' })).toBe('other');
  });
});
