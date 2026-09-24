// Card-schema-driven rendering for the DDS console (I3 E3c, HLD 70 §70.5.2/§70.5.4, D17). The
// server always sends `DdsWorkItem.field_specs` now (E3a′) — the same `CardFieldSpec`s
// `OperatorCardView` carries, options and all — so this is the one place the DDS side turns a
// `field_path`/`FactValue` pair into Russian text; the DDS side's old hand-written field-path ->
// label catalog is gone for good (D17: `label_ru` is server-rendered for every schema field, v1
// and v2 alike).
//
// `evaluateCardCondition` is a hand-ported mirror of the backend's `evaluate_condition`
// (`backend/app/domain/layers/card_schema.py`) — both run over the one shared fixture file
// `reference/card-schema/conditions.fixtures.json` (§70.5.2), checked in
// `card-schema-render.test.ts`.
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import type { components } from '@/shared/api';
import type { CardFieldSpec, FactValue } from '@/entities/card';
import { serviceTypeLabelRu } from './dds-labels';

export type CardCondition = components['schemas']['CardCondition'];

/** Mirrors the backend's `_is_filled`: not `null`, not `""`, not `[]`. `false` counts as set. */
export function isCardValueFilled(value: FactValue | undefined): boolean {
  if (value === undefined || value === null || value === '') {
    return false;
  }
  return !(Array.isArray(value) && value.length === 0);
}

/** Mirrors `evaluate_condition` (`backend/app/domain/layers/card_schema.py`) exactly — see
 * `card-schema-render.test.ts` for the shared-fixture cases this must agree with. */
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

/** Mirrors `CardSchema.visible()`: a field with no `visible_when` is always shown. */
export function isCardFieldVisible(spec: CardFieldSpec, values: Readonly<Record<string, FactValue>>): boolean {
  return spec.visible_when ? evaluateCardCondition(spec.visible_when, values) : true;
}

/** An option's `label_ru` by `code`, or the raw code when the spec carries no matching option
 * (defensive fallback, never a blank label). */
export function cardOptionLabelRu(spec: CardFieldSpec, code: string): string {
  const option = spec.options?.find((candidate) => candidate.code === code);
  return option ? option.label_ru : code;
}

const INCIDENT_TYPE_LABEL_KEY: Record<string, keyof typeof ru> = {
  FIRE: 'incidentTypeFire',
  MEDICAL: 'incidentTypeMedical',
  CRIME: 'incidentTypeCrime',
  TRAFFIC_ACCIDENT: 'incidentTypeTrafficAccident',
  GAS_LEAK: 'incidentTypeGasLeak',
  UTILITY_FAILURE: 'incidentTypeUtilityFailure',
  RESCUE: 'incidentTypeRescue',
  OTHER: 'incidentTypeOther',
};
const CALLER_RELATIONSHIP_LABEL_KEY: Record<string, keyof typeof ru> = {
  VICTIM: 'callerRelationshipVictim',
  WITNESS: 'callerRelationshipWitness',
  NEIGHBOUR: 'callerRelationshipNeighbour',
  RELATIVE: 'callerRelationshipRelative',
  PASSERBY: 'callerRelationshipPasserby',
  OFFICIAL: 'callerRelationshipOfficial',
  UNKNOWN: 'callerRelationshipUnknown',
};
// A v1 `ENUM` field carries `enum_name` but no `options` — the classifier-backed `options` the
// binding gives every v2 field (§70.5.2) does not exist for v1, so these two enums still need
// their value looked up by hand. This is not a field-path label catalog (every field's own
// `label_ru` already comes from `field_specs`); it is the same small enum-*value* table
// `features/operator/card-form.tsx` and `features/report/snapshot-card-fields.ts` each keep.
const ENUM_LABEL_KEYS_BY_ENUM_NAME: Record<string, Record<string, keyof typeof ru>> = {
  IncidentType: INCIDENT_TYPE_LABEL_KEY,
  CallerRelationship: CALLER_RELATIONSHIP_LABEL_KEY,
};

/** Renders one `card_values[field_path]` as Russian display text, options and all. `undefined`
 * (never set) and the "unfilled" scalars (`null`, `""`, `[]`) all render as `factValueEmpty`. */
export function formatCardValueRu(spec: CardFieldSpec, value: FactValue | undefined): string {
  if (!isCardValueFilled(value)) {
    return t('factValueEmpty');
  }
  if (spec.value_type === 'BOOLEAN') {
    return value === true ? t('factBooleanYes') : t('factBooleanNo');
  }
  if (spec.value_type === 'STRING_LIST') {
    const items = Array.isArray(value) ? value : [];
    if (spec.field_path === 'recipients.services') {
      return items.map((item) => serviceTypeLabelRu(item)).join(', ');
    }
    if (spec.options) {
      return items.map((item) => cardOptionLabelRu(spec, item)).join(', ');
    }
    return items.join(', ');
  }
  if (spec.value_type === 'ENUM') {
    if (spec.options) {
      return cardOptionLabelRu(spec, String(value));
    }
    if (spec.enum_name) {
      const key = ENUM_LABEL_KEYS_BY_ENUM_NAME[spec.enum_name]?.[String(value)];
      if (key) return t(key);
    }
  }
  return String(value);
}

export interface CardFieldGroup {
  key: string;
  fields: readonly CardFieldSpec[];
}

// v1 fields all carry `group: null` (`card_schema.py`: "a v1 document ... gets the neutral
// values"), so grouping falls back to the `field_path` prefix — the same derivation
// `entities/card`'s `groupCardFields` already used for v1. v2 fields carry an explicit `group`
// (header/applicant/address/…, §70.5.2) which always wins.
function derivedGroupKey(fieldPath: string): string {
  return fieldPath.split('.')[0] ?? fieldPath;
}

/** Groups the fields `shouldShow` selects, after dropping anything `visible_when` hides for
 * `values` (D-9: never a raw dump of every declared path — empty and hidden fields are omitted by
 * the caller's `shouldShow` and by this function respectively). Groups keep the order they first
 * appear in `fieldSpecs`; within a group, fields sort by the schema's own `order`. */
export function groupVisibleCardFields(
  fieldSpecs: readonly CardFieldSpec[],
  values: Readonly<Record<string, FactValue>>,
  shouldShow: (spec: CardFieldSpec) => boolean,
): CardFieldGroup[] {
  const groups: { key: string; fields: { spec: CardFieldSpec; position: number }[] }[] = [];
  const indexByKey = new Map<string, number>();

  fieldSpecs.forEach((spec, position) => {
    if (!shouldShow(spec) || !isCardFieldVisible(spec, values)) return;
    const key = spec.group ?? derivedGroupKey(spec.field_path);
    let index = indexByKey.get(key);
    if (index === undefined) {
      index = groups.length;
      indexByKey.set(key, index);
      groups.push({ key, fields: [] });
    }
    groups[index]!.fields.push({ spec, position });
  });

  return groups.map((group) => ({
    key: group.key,
    fields: group.fields
      .slice()
      .sort((a, b) => (a.spec.order ?? a.position) - (b.spec.order ?? b.position))
      .map((entry) => entry.spec),
  }));
}

export { serviceTypeLabelRu };
