// §29 item 8: card final state. Renders `final_card` exactly as `getSessionReport` returned it —
// grouped by `entities/card`'s `groupCardFields` (the same field-path-prefix grouping the operator
// form uses), each value through {@link formatFactValueRu}.
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { groupCardFields } from '@/entities/card';
import type { OperatorCardView } from '@/shared/api';
import { formatFactValueRu } from './format-fact-value';

const GROUP_LABEL_KEY: Record<string, keyof typeof ru> = {
  incident: 'operatorGroupIncident',
  address: 'operatorGroupAddress',
  caller: 'operatorGroupCaller',
  description: 'operatorGroupDescription',
  people: 'operatorGroupPeople',
  hazards: 'operatorGroupHazards',
  flags: 'operatorGroupFlags',
  notes: 'operatorGroupNotes',
  recipients: 'operatorGroupRecipients',
};

function groupLabel(key: string): string {
  return t(GROUP_LABEL_KEY[key] ?? 'operatorGroupOther');
}

interface FinalCardSectionProps {
  card: OperatorCardView;
}

export function FinalCardSection({ card }: FinalCardSectionProps) {
  const groups = groupCardFields(card.field_specs);

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
