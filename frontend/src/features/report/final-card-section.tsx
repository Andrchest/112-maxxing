// §29 item 8: card final state. Renders `final_card` exactly as `getSessionReport` returned it,
// grouped and ordered by its own `field_specs` (I3 E3c, HLD 70 §70.5.4, D17) — the schema's `group`
// for a v2 card, the `field_path` prefix for v1 (whose `group` is always `null`) — each value
// through {@link formatFactValueRu}. A field `visible_when` hides for this card's own `values` is
// omitted, same as the DDS sentence view (ui-check D-9); every other declared field renders, filled
// or not.
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import type { OperatorCardView } from '@/shared/api';
import { formatFactValueRu } from './format-fact-value';
import { groupVisibleCardFields } from './snapshot-card-fields';

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
  q_ambulance: 'operatorGroupQAmbulance', // I7 E55
  services: 'operatorGroupServices',
};

function groupLabel(key: string): string {
  return t(GROUP_LABEL_KEY[key] ?? 'operatorGroupOther');
}

interface FinalCardSectionProps {
  card: OperatorCardView;
}

export function FinalCardSection({ card }: FinalCardSectionProps) {
  const groups = groupVisibleCardFields(card.field_specs, card.values);

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportFinalCardTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {groups.map((group) => (
          <div key={group.key} className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{groupLabel(group.key)}</h3>
            <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {group.fields.map((spec) => (
                <div key={spec.field_path} className="flex flex-col gap-0.5">
                  <dt className="text-xs text-muted-foreground">{spec.label_ru}</dt>
                  <dd className="text-sm">{formatFactValueRu(spec, card.values[spec.field_path])}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
