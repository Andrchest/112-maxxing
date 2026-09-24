// Section titles for a card's own `group` (v2, §70.5.2) or the `field_path` prefix a v1 field
// falls back to (`entities/card`'s `groupCardFields`) — the same key table
// `features/dds/work-item-panel.tsx` and `features/report/{final-card-section,handoff-section}.tsx`
// each keep their own copy of (one per feature, established convention; not re-derived from a
// server DTO because no DTO carries a group's Russian label, §70.5.2's `CardFieldGroup.label_ru`
// is never serialized).
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';

const GROUP_LABEL_KEY: Record<string, keyof typeof ru> = {
  // v1 groups (derived from the `field_path` prefix — v1's `group` is always `null`)
  incident: 'operatorGroupIncident',
  address: 'operatorGroupAddress',
  caller: 'operatorGroupCaller',
  description: 'operatorGroupDescription',
  people: 'operatorGroupPeople',
  hazards: 'operatorGroupHazards',
  flags: 'operatorGroupFlags',
  notes: 'operatorGroupNotes',
  recipients: 'operatorGroupRecipients',
  // v2 groups (the schema's own explicit `group`, §70.5.2)
  header: 'operatorGroupHeader',
  applicant: 'operatorGroupApplicant',
  q_fire: 'operatorGroupQFire',
  q_gas: 'operatorGroupQGas',
  q_explosion: 'operatorGroupQExplosion',
  services: 'operatorGroupServices',
};

export function groupLabelRu(key: string): string {
  return t(GROUP_LABEL_KEY[key] ?? 'operatorGroupOther');
}
