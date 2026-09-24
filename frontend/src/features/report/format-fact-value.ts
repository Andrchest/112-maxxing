// Renders one `OperatorCardView.values[field_path]` as Russian display text — the report's own
// copy of the small enum-label lookup `features/operator/card-form.tsx` and
// `features/dds/card-field-labels.ts` each already keep locally (same treatment, not a shared
// import: every feature that renders `CardFieldSpec`/`FactValue` keeps its own copy in this repo).
// `OperatorCardView.field_specs[].label_ru` is already Russian (server-rendered), so unlike the
// DDS side, no separate field-label catalog is needed here — only the per-option enum labels.
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import type { CardFieldSpec, FactValue } from '@/shared/api';
import { serviceTypeLabelRu } from './snapshot-card-fields';

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
    const items = Array.isArray(value) ? value : [];
    if (spec.field_path === 'recipients.services') {
      return items.map((item) => serviceTypeLabelRu(String(item))).join(', ');
    }
    return items.join(', ');
  }
  if (spec.value_type === 'ENUM' && spec.enum_name) {
    const enumLabelKeys = ENUM_LABEL_KEYS_BY_ENUM_NAME[spec.enum_name];
    const key = enumLabelKeys?.[String(value)];
    if (key) return t(key);
  }
  return String(value);
}
