// `evaluateCardCondition` is a hand-ported mirror of the backend's `evaluate_condition`
// (`backend/app/domain/layers/card_schema.py`, HLD 70 §70.5.2) — this checks it against the one
// shared fixture file both sides run over (and `features/dds/card-schema-render.ts` also runs
// over independently), so a future edit to either evaluator that breaks the agreement fails here.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { evaluateCardCondition, isCardFieldVisible, isCardValueFilled } from './card-condition';
import type { CardCondition } from './card-condition';
import type { CardFieldSpec, FactValue } from './card-store';

interface ConditionFixtureCase {
  name: string;
  condition: CardCondition;
  values: Record<string, FactValue>;
  expected: boolean;
}

const FIXTURES_PATH = join(process.cwd(), '..', 'reference/card-schema/conditions.fixtures.json');
const FIXTURES = JSON.parse(readFileSync(FIXTURES_PATH, 'utf-8')) as { cases: ConditionFixtureCase[] };

describe('evaluateCardCondition matches the backend evaluator (shared fixtures, HLD 70 §70.5.2)', () => {
  it.each(FIXTURES.cases.map((testCase) => [testCase.name, testCase] as const))('%s', (_name, testCase) => {
    expect(evaluateCardCondition(testCase.condition, testCase.values)).toBe(testCase.expected);
  });
});

describe('isCardValueFilled', () => {
  it('treats null, "" and [] as unfilled; false as filled', () => {
    expect(isCardValueFilled(null)).toBe(false);
    expect(isCardValueFilled('')).toBe(false);
    expect(isCardValueFilled([])).toBe(false);
    expect(isCardValueFilled(undefined)).toBe(false);
    expect(isCardValueFilled(false)).toBe(true);
    expect(isCardValueFilled('27')).toBe(true);
  });
});

describe('isCardFieldVisible', () => {
  it('is always visible with no visible_when', () => {
    const spec: CardFieldSpec = { field_path: 'address.house', value_type: 'STRING', enum_name: null, label_ru: 'Дом', scoring_relevant: true, required_for_handoff: true };
    expect(isCardFieldVisible(spec, {})).toBe(true);
  });

  it('defers to evaluateCardCondition when visible_when is set', () => {
    const spec: CardFieldSpec = {
      field_path: 'q.fire.where',
      value_type: 'STRING_LIST',
      enum_name: null,
      label_ru: 'Где',
      scoring_relevant: false,
      required_for_handoff: false,
      visible_when: { field_path: 'incident.types', op: 'CONTAINS', value: '1' },
    };
    expect(isCardFieldVisible(spec, { 'incident.types': ['1'] })).toBe(true);
    expect(isCardFieldVisible(spec, { 'incident.types': ['13'] })).toBe(false);
  });
});
