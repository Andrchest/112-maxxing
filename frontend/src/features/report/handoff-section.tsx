// §29 item 10: handoff snapshot. `null` when the session never reached a handoff (a DDS-only run,
// 10.14 reading #9) — rendered as the empty state, not an error.
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { formatCallDurationMs } from '@/entities/call';
import { groupCardFields } from '@/entities/card';
import type { HandoffSnapshotView } from '@/shared/api';
import { SNAPSHOT_CARD_FIELDS, formatSnapshotValueRu, serviceTypeLabelRu, snapshotFieldLabelRu } from './snapshot-card-fields';

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

interface HandoffSectionProps {
  handoff: HandoffSnapshotView | null;
}

export function HandoffSection({ handoff }: HandoffSectionProps) {
  if (!handoff) {
    return (
      <Card>
        <CardHeader>
          <h2 className="font-heading text-base leading-snug font-medium">{t('reportHandoffTitle')}</h2>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{t('reportHandoffEmpty')}</p>
        </CardContent>
      </Card>
    );
  }

  const relevantFields = SNAPSHOT_CARD_FIELDS.filter((spec) => spec.field_path in handoff.card_values);
  const groups = groupCardFields(relevantFields);

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportHandoffTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{t('reportHandoffRecipientsLabel')}</span>
          {handoff.recipient_services.map((service) => (
            <Badge key={service} variant="outline">
              {serviceTypeLabelRu(service)}
            </Badge>
          ))}
          <span className="ml-auto text-xs text-muted-foreground">
            {t('reportHandoffCreatedAtLabel')}: {formatCallDurationMs(handoff.created_at_offset_ms)}
          </span>
        </div>
        {groups.map((group) => (
          <div key={group.key} className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{groupLabel(group.key)}</h3>
            <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {group.fields.map((spec) => (
                <div key={spec.field_path} className="flex flex-col gap-0.5">
                  <dt className="text-xs text-muted-foreground">{snapshotFieldLabelRu(spec.field_path)}</dt>
                  <dd className="text-sm">{formatSnapshotValueRu(spec.field_path, handoff.card_values[spec.field_path])}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
