// `evaluateCardCondition` is a hand-ported mirror of the backend's `evaluate_condition`
// (`backend/app/domain/layers/card_schema.py`, HLD 70 §70.5.2) — this checks it against the one
// shared fixture file both sides run over, so a future edit to either evaluator that breaks the
// agreement fails here, not in production.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { cardOptionLabelRu, evaluateCardCondition, formatCardValueRu, isCardFieldVisible, isCardValueFilled } from './card-schema-render';
import type { CardCondition } from './card-schema-render';
import { ru } from '@/shared/i18n/ru';
import type { CardFieldSpec, FactValue } from '@/entities/card';

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
      field_path: 'q.fire.threat_to_people',
      value_type: 'STRING',
      enum_name: null,
      label_ru: 'Threat',
      scoring_relevant: false,
      required_for_handoff: false,
      visible_when: { field_path: 'incident.types', op: 'CONTAINS', value: '1' },
    };
    expect(isCardFieldVisible(spec, { 'incident.types': ['1'] })).toBe(true);
    expect(isCardFieldVisible(spec, { 'incident.types': ['13'] })).toBe(false);
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
    // code '5' is deliberately outside the reference-wording override table below (it only
    // covers '1'/'13'/'3') — this case exercises the plain "option code -> its own label_ru" path.
    options: [{ code: '5', label_ru: 'Пожар (открытое пламя / дым)' }],
  };

  it('maps a STRING_LIST option code to its label_ru', () => {
    expect(formatCardValueRu(chip, ['5'])).toBe('Пожар (открытое пламя / дым)');
  });

  it('cardOptionLabelRu falls back to the raw code for an unknown option', () => {
    expect(cardOptionLabelRu(chip, '99')).toBe('99');
  });

  it('I3 E7a carry-over fix (b): the questionnaire-backed «Что случилось?» codes render the reference wording, not the schema’s bare option label', () => {
    const questionnaireChip: CardFieldSpec = {
      ...chip,
      options: [
        { code: '1', label_ru: '101' },
        { code: '13', label_ru: '104' },
        { code: '3', label_ru: 'Взрыв' },
      ],
    };
    expect(formatCardValueRu(questionnaireChip, ['1'])).toBe(ru.operatorGroupQFire);
    expect(formatCardValueRu(questionnaireChip, ['13'])).toBe(ru.operatorGroupQGas);
    expect(formatCardValueRu(questionnaireChip, ['3'])).toBe(ru.operatorGroupQExplosion);
    expect(formatCardValueRu(questionnaireChip, ['1'])).not.toBe('101');
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
