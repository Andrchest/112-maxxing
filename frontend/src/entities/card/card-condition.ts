// The card-local `CardCondition` evaluator (HLD 70 §70.5.2, I3 E3b). A hand-ported mirror of the
// backend's `evaluate_condition` (`backend/app/domain/layers/card_schema.py`) — both sides run
// over the one shared fixture file `reference/card-schema/conditions.fixtures.json`, checked in
// `card-condition.test.ts`. This is the one `CardCondition` evaluator `entities/card` owns (I3
// row of `90-tbd-epics.md`'s E3b): `features/operator/card/**` renders `visible_when` through
// `isCardFieldVisible` below, never by re-deriving a condition's meaning itself.
import type { CardCondition, CardFieldSpec, FactValue } from './card-store';

/** Mirrors the backend's `_is_filled`: not `null`, not `""`, not `[]`. `false` counts as set (a
 * toggle that was explicitly answered "no"). */
export function isCardValueFilled(value: FactValue | undefined): boolean {
  if (value === undefined || value === null || value === '') {
    return false;
  }
  return !(Array.isArray(value) && value.length === 0);
}

/** Mirrors `evaluate_condition` exactly: `EQ`/`NE` compare a filled value, `IN` checks a scalar
 * or list card value against a listed set, `CONTAINS` checks the card value (must itself be a
 * list) holds every wanted item, `PRESENT` is `isCardValueFilled`. Codes are compared exactly. */
export function evaluateCardCondition(condition: CardCondition, values: Readonly<Record<string, FactValue>>): boolean {
  if ('all' in condition) {
    return condition.all.every((branch) => evaluateCardCondition(branch, values));
  }
  if ('any' in condition) {
    return condition.any.some((branch) => evaluateCardCondition(branch, values));
  }
  if ('not' in condition) {
    return !evaluateCardCondition(condition.not, values);
  }
  const actual = values[condition.field_path];
  const expected = condition.value;
  switch (condition.op) {
    case 'EQ':
      return isCardValueFilled(actual) && actual === expected;
    case 'NE':
      return !(isCardValueFilled(actual) && actual === expected);
    case 'IN': {
      if (!Array.isArray(expected) || !isCardValueFilled(actual)) return false;
      if (Array.isArray(actual)) {
        return actual.some((item) => expected.includes(item));
      }
      return expected.includes(actual as string);
    }
    case 'CONTAINS': {
      if (!Array.isArray(actual)) return false;
      const wanted = Array.isArray(expected) ? expected : [expected as string];
      return wanted.every((item) => actual.includes(item));
    }
    case 'PRESENT':
      return isCardValueFilled(actual);
    default:
      return false;
  }
}

/** Mirrors `CardSchema.visible()`: a field with no `visible_when` is always shown; advisory only
 * — a hidden field is still a valid `setCardField` target (never blocks the command). */
export function isCardFieldVisible(spec: CardFieldSpec, values: Readonly<Record<string, FactValue>>): boolean {
  return spec.visible_when ? evaluateCardCondition(spec.visible_when, values) : true;
}

export type { CardCondition };
