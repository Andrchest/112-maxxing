// Field labels for `HandoffSnapshotView.card_values` (§29 item 10). Like `DdsWorkItem.card_values`
// (`features/dds/card-field-labels.ts`), `HandoffSnapshotView` carries no `field_specs` of its
// own — only `OperatorCardView` does — so this is the report's own copy of the same static
// `CARD_FIELDS` catalog (`docs/hld/10-domain-model.md` §10.6), the same duplication-over-cross-
// feature-import treatment every other feature that needs it already uses (see the report's "HLD
// gaps"). Grouping reuses `entities/card`'s `groupCardFields` — only labels/formatting live here.
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import type { CardFieldSpec, FactValue, ServiceType } from '@/shared/api';

export const SNAPSHOT_CARD_FIELDS: readonly CardFieldSpec[] = [
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
export function snapshotFieldLabelRu(fieldPath: string): string {
  const key = FIELD_LABEL_KEY[fieldPath];
  return key ? t(key) : fieldPath;
}

const SERVICE_TYPE_LABEL_KEY: Record<ServiceType, keyof typeof ru> = {
  FIRE_RESCUE: 'serviceTypeFireRescue',
  POLICE: 'serviceTypePolice',
  AMBULANCE: 'serviceTypeAmbulance',
  GAS_SERVICE: 'serviceTypeGasService',
  UTILITY_EMERGENCY: 'serviceTypeUtilityEmergency',
  EDDS: 'serviceTypeEdds',
};
export function serviceTypeLabelRu(value: ServiceType): string {
  return t(SERVICE_TYPE_LABEL_KEY[value]);
}

/** `snapshot.card_values` has no `CardFieldSpec` attached to each value (unlike
 * `OperatorCardView`) — {@link SNAPSHOT_CARD_FIELDS} supplies the spec by `field_path` so the same
 * boolean/enum/list formatting `features/report/format-fact-value.ts` gives `final_card` applies
 * here too. */
export function formatSnapshotValueRu(fieldPath: string, value: FactValue | undefined): string {
  if (value === undefined || value === null) {
    return t('factValueEmpty');
  }
  if (typeof value === 'boolean') {
    return value ? t('factBooleanYes') : t('factBooleanNo');
  }
  if (Array.isArray(value)) {
    if (fieldPath === 'recipients.services') {
      return value.map((item) => serviceTypeLabelRu(item as ServiceType)).join(', ');
    }
    return value.join(', ');
  }
  return String(value);
}
