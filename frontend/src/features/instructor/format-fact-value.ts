// Renders one `OperatorCardView.values[field_path]` / `HandoffSnapshotView.card_values[field_path]`
// as Russian display text — the instructor feature's own copy of the small enum-label lookup every
// feature that renders `CardFieldSpec`/`FactValue` keeps locally (`features/report/format-fact-
// value.ts`, `features/dds/card-field-labels.ts`; same treatment, not a shared import).
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import type { CardFieldSpec, FactValue } from '@/shared/api';

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
const ENUM_LABEL_KEYS_BY_ENUM_NAME: Record<string, Record<string, keyof typeof ru>> = {
  IncidentType: INCIDENT_TYPE_LABEL_KEY,
  CallerRelationship: CALLER_RELATIONSHIP_LABEL_KEY,
};

/** `undefined`/`null` render as `factValueEmpty` ("—") — never a guessed value. */
export function formatFactValueRu(spec: CardFieldSpec, value: FactValue | undefined): string {
  if (value === undefined || value === null) {
    return t('factValueEmpty');
  }
  if (spec.value_type === 'BOOLEAN') {
    return value === true ? t('factBooleanYes') : t('factBooleanNo');
  }
  if (spec.value_type === 'STRING_LIST') {
    return Array.isArray(value) ? value.join(', ') : String(value);
  }
  if (spec.value_type === 'ENUM' && spec.enum_name) {
    const enumLabelKeys = ENUM_LABEL_KEYS_BY_ENUM_NAME[spec.enum_name];
    const key = enumLabelKeys?.[String(value)];
    if (key) return t(key);
  }
  return String(value);
}

/** Raw fallback for a value that has no `CardFieldSpec` (e.g. a `handoff.card_values` field the
 * live `card`'s `field_specs` no longer carries) — the value itself, never a guessed label. */
export function formatRawFactValueRu(value: FactValue | undefined): string {
  if (value === undefined || value === null) {
    return t('factValueEmpty');
  }
  if (value === true) return t('factBooleanYes');
  if (value === false) return t('factBooleanNo');
  if (Array.isArray(value)) return value.join(', ');
  return String(value);
}
