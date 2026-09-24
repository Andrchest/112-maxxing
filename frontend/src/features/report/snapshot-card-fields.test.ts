// `evaluateCardCondition` is a hand-ported mirror of the backend's `evaluate_condition`
// (`backend/app/domain/layers/card_schema.py`, HLD 70 §70.5.2) — this checks it against the one
// shared fixture file both sides run over, so a future edit to either evaluator that breaks the
// agreement fails here, not in production. Mirrors `features/dds/card-schema-render.test.ts`
// (each feature keeps its own copy of the evaluator, same treatment as the label lookups).
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { cardOptionLabelRu, evaluateCardCondition, formatCardValueRu, isCardFieldVisible, isCardValueFilled } from './snapshot-card-fields';
import type { CardCondition } from './snapshot-card-fields';
import { ru } from '@/shared/i18n/ru';
import type { CardFieldSpec, FactValue } from '@/shared/api';

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
  it('defers to evaluateCardCondition when visible_when is set, else always visible', () => {
    const alwaysVisible: CardFieldSpec = { field_path: 'address.house', value_type: 'STRING', enum_name: null, label_ru: 'Дом', scoring_relevant: true, required_for_handoff: true };
    expect(isCardFieldVisible(alwaysVisible, {})).toBe(true);

    const conditional: CardFieldSpec = {
      field_path: 'address.building',
      value_type: 'STRING',
      enum_name: null,
      label_ru: 'Корпус',
      scoring_relevant: false,
      required_for_handoff: false,
      visible_when: { field_path: 'address.house', op: 'EQ', value: '27' },
    };
    expect(isCardFieldVisible(conditional, { 'address.house': '27' })).toBe(true);
    expect(isCardFieldVisible(conditional, { 'address.house': '72' })).toBe(false);
  });
});

describe('cardOptionLabelRu / formatCardValueRu — v2 options over v1 enum fallback', () => {
  const chip: CardFieldSpec = {
    field_path: 'incident.types',
    value_type: 'STRING_LIST',
    enum_name: null,
    label_ru: 'Что случилось',
    scoring_relevant: false,
    required_for_handoff: false,
    options: [{ code: '1', label_ru: 'Пожар (открытое пламя / дым)' }],
  };

  it('maps a STRING_LIST option code to its label_ru', () => {
    expect(formatCardValueRu(chip, ['1'])).toBe('Пожар (открытое пламя / дым)');
  });

  it('cardOptionLabelRu falls back to the raw code for an unknown option', () => {
    expect(cardOptionLabelRu(chip, '99')).toBe('99');
  });

  it('falls back to the v1 enum_name table when a field has no options', () => {
    const enumSpec: CardFieldSpec = { field_path: 'incident.type', value_type: 'ENUM', enum_name: 'IncidentType', label_ru: 'Тип происшествия', scoring_relevant: true, required_for_handoff: true };
    expect(formatCardValueRu(enumSpec, 'FIRE')).toBe(ru.incidentTypeFire);
  });

  it('renders an unfilled value as factValueEmpty', () => {
    const spec: CardFieldSpec = { field_path: 'address.house', value_type: 'STRING', enum_name: null, label_ru: 'Дом', scoring_relevant: true, required_for_handoff: true };
    expect(formatCardValueRu(spec, null)).toBe(ru.factValueEmpty);
    expect(formatCardValueRu(spec, undefined)).toBe(ru.factValueEmpty);
  });
});
