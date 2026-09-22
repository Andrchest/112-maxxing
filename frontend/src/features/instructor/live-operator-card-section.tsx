// Live operator card panel (SPEC §9, §10.8; R4). `card` is `null` before the Operator 112 stage
// starts or once the session skips it entirely (DDS-only `SINGLE_ROLE`/`prefab_handoff`) — rendered
// as the empty state, not an error, same treatment `features/report/handoff-section.tsx` uses for
// its own nullable snapshot. Renders straight from `OperatorCardView.field_specs`/`values` (D8),
// grouped the same way `entities/card`'s `groupCardFields` groups it for the trainee-facing form.
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

interface LiveOperatorCardSectionProps {
  card: OperatorCardView | null;
}

export function LiveOperatorCardSection({ card }: LiveOperatorCardSectionProps) {
  if (!card) {
    return (
      <Card>
        <CardHeader>
          <h2 className="font-heading text-base leading-snug font-medium">{t('instructorOperatorCardTitle')}</h2>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{t('instructorOperatorCardEmpty')}</p>
        </CardContent>
      </Card>
    );
  }

  const groups = groupCardFields(card.field_specs);

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('instructorOperatorCardTitle')}</h2>
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
