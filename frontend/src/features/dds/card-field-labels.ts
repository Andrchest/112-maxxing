// The static `CARD_FIELDS` catalog (`docs/hld/10-domain-model.md` §10.6), copied here as
// presentation data because `DdsWorkItem.card_values` (openapi.yaml) carries no `field_specs` —
// unlike `OperatorCardView`, the DDS side of the contract has nowhere to put per-field
// `label_ru`/`value_type`. This is a frontend-only concern (see the report's "HLD gaps"), the
// same treatment `features/operator/card-form.tsx` already gives `CardFieldSpec.enum_name` option
// labels. Field order and grouping (`entities/card`'s `groupCardFields`, by the `field_path`
// prefix) are structural — this file only supplies the label/value-type/required-for-handoff data
// the server does not send to DDS.
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { serviceTypeLabelRu } from './dds-labels';
import type { CardFieldSpec, FactValue } from '@/entities/card';

export const DDS_CARD_FIELDS: readonly CardFieldSpec[] = [
  { field_path: 'incident.type', value_type: 'ENUM', enum_name: 'IncidentType', label_ru: '', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'incident.subtype', value_type: 'STRING', enum_name: null, label_ru: '', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'incident.reported_at_offset_ms', value_type: 'INTEGER', enum_name: null, label_ru: '', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'address.locality', value_type: 'STRING', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'address.street', value_type: 'STRING', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'address.house', value_type: 'STRING', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'address.building', value_type: 'STRING', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: false },
  { field_path: 'address.entrance', value_type: 'STRING', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: false },
  { field_path: 'address.floor', value_type: 'INTEGER', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: false },
  { field_path: 'address.apartment', value_type: 'STRING', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: false },
  { field_path: 'address.landmark', value_type: 'STRING', enum_name: null, label_ru: '', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'address.comment', value_type: 'STRING', enum_name: null, label_ru: '', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'caller.full_name', value_type: 'STRING', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: false },
  { field_path: 'caller.phone', value_type: 'STRING', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'caller.relationship', value_type: 'ENUM', enum_name: 'CallerRelationship', label_ru: '', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'caller.callback_possible', value_type: 'BOOLEAN', enum_name: null, label_ru: '', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'description.text', value_type: 'STRING', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'people.total_affected', value_type: 'INTEGER', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: false },
  { field_path: 'people.victims_count', value_type: 'INTEGER', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: false },
  { field_path: 'people.trapped_count', value_type: 'INTEGER', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: false },
  { field_path: 'people.children_present', value_type: 'BOOLEAN', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: false },
  { field_path: 'people.evacuation_needed', value_type: 'BOOLEAN', enum_name: null, label_ru: '', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'people.notes', value_type: 'STRING', enum_name: null, label_ru: '', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'hazards.open_fire', value_type: 'BOOLEAN', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: false },
  { field_path: 'hazards.smoke', value_type: 'BOOLEAN', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: false },
  { field_path: 'hazards.gas_leak', value_type: 'BOOLEAN', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: false },
  { field_path: 'hazards.electrical', value_type: 'BOOLEAN', enum_name: null, label_ru: '', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'hazards.chemical', value_type: 'BOOLEAN', enum_name: null, label_ru: '', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'hazards.collapse_risk', value_type: 'BOOLEAN', enum_name: null, label_ru: '', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'hazards.other', value_type: 'STRING', enum_name: null, label_ru: '', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'flags.threat_to_life', value_type: 'BOOLEAN', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'flags.mass_event', value_type: 'BOOLEAN', enum_name: null, label_ru: '', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'flags.repeat_call', value_type: 'BOOLEAN', enum_name: null, label_ru: '', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'flags.requires_escalation', value_type: 'BOOLEAN', enum_name: null, label_ru: '', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'flags.false_call', value_type: 'BOOLEAN', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: false },
  { field_path: 'notes.free_text', value_type: 'STRING', enum_name: null, label_ru: '', scoring_relevant: false, required_for_handoff: false },
  { field_path: 'recipients.services', value_type: 'STRING_LIST', enum_name: null, label_ru: '', scoring_relevant: true, required_for_handoff: true },
  { field_path: 'recipients.comment', value_type: 'STRING', enum_name: null, label_ru: '', scoring_relevant: false, required_for_handoff: false },
];

const FIELD_LABEL_KEY: Record<string, keyof typeof ru> = {
  'incident.type': 'cardFieldIncidentType',
  'incident.subtype': 'cardFieldIncidentSubtype',
  'incident.reported_at_offset_ms': 'cardFieldIncidentReportedAt',
  'address.locality': 'cardFieldAddressLocality',
  'address.street': 'cardFieldAddressStreet',
  'address.house': 'cardFieldAddressHouse',
  'address.building': 'cardFieldAddressBuilding',
  'address.entrance': 'cardFieldAddressEntrance',
  'address.floor': 'cardFieldAddressFloor',
  'address.apartment': 'cardFieldAddressApartment',
  'address.landmark': 'cardFieldAddressLandmark',
  'address.comment': 'cardFieldAddressComment',
  'caller.full_name': 'cardFieldCallerFullName',
  'caller.phone': 'cardFieldCallerPhone',
  'caller.relationship': 'cardFieldCallerRelationship',
  'caller.callback_possible': 'cardFieldCallerCallbackPossible',
  'description.text': 'cardFieldDescriptionText',
  'people.total_affected': 'cardFieldPeopleTotalAffected',
  'people.victims_count': 'cardFieldPeopleVictimsCount',
  'people.trapped_count': 'cardFieldPeopleTrappedCount',
  'people.children_present': 'cardFieldPeopleChildrenPresent',
  'people.evacuation_needed': 'cardFieldPeopleEvacuationNeeded',
  'people.notes': 'cardFieldPeopleNotes',
  'hazards.open_fire': 'cardFieldHazardsOpenFire',
  'hazards.smoke': 'cardFieldHazardsSmoke',
  'hazards.gas_leak': 'cardFieldHazardsGasLeak',
  'hazards.electrical': 'cardFieldHazardsElectrical',
  'hazards.chemical': 'cardFieldHazardsChemical',
  'hazards.collapse_risk': 'cardFieldHazardsCollapseRisk',
  'hazards.other': 'cardFieldHazardsOther',
  'flags.threat_to_life': 'cardFieldFlagsThreatToLife',
  'flags.mass_event': 'cardFieldFlagsMassEvent',
  'flags.repeat_call': 'cardFieldFlagsRepeatCall',
  'flags.requires_escalation': 'cardFieldFlagsRequiresEscalation',
  'flags.false_call': 'cardFieldFlagsFalseCall',
  'notes.free_text': 'cardFieldNotesFreeText',
  'recipients.services': 'cardFieldRecipientsServices',
  'recipients.comment': 'cardFieldRecipientsComment',
};

/** The label for one `field_path`, or the raw path itself for a field this static catalog does
 * not (yet) know — defensive fallback, never a blank label. */
export function cardFieldLabelRu(fieldPath: string): string {
  const key = FIELD_LABEL_KEY[fieldPath];
  return key ? t(key) : fieldPath;
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
const ENUM_LABEL_KEYS_BY_ENUM_NAME: Record<string, Record<string, keyof typeof ru>> = {
  IncidentType: INCIDENT_TYPE_LABEL_KEY,
  CallerRelationship: CALLER_RELATIONSHIP_LABEL_KEY,
};

/** Renders one frozen `card_values[field_path]` as Russian display text. `undefined` (the field
 * was never set — SPEC §10: "the omission propagates") is the caller's job to render as
 * `ddsMissingFieldNotice`, not this function's. */
export function formatFactValueRu(spec: CardFieldSpec, value: FactValue): string {
  if (value === null) {
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
