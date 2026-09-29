// §29 item 10: handoff snapshot. `null` when the session never reached a handoff (a DDS-only run,
// 10.14 reading #9) — rendered as the empty state, not an error.
//
// `HandoffSnapshotView` carries no `field_specs` of its own (I3 E3a′ left it that way, HLD 70
// §70.5.4). Its `card_values` are a frozen deep copy of the same card `final_card` describes, so
// `report-page.tsx` passes `report.final_card.field_specs` in as `fieldSpecs` — the one schema for
// both sections. Only paths present in `card_values` render, grouped/ordered by the schema's own
// `group`/`order` and with `visible_when`-hidden fields dropped, same as `final-card-section.tsx`.
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { formatCallDurationMs } from '@/entities/call';
import type { CardFieldSpec, HandoffSnapshotView } from '@/shared/api';
import { formatFactValueRu } from './format-fact-value';
import { groupVisibleCardFields, serviceTypeLabelRu } from './snapshot-card-fields';

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

interface HandoffSectionProps {
  handoff: HandoffSnapshotView | null;
  /** The session's card schema — `SessionReport.final_card.field_specs` (see the file comment). */
  fieldSpecs: readonly CardFieldSpec[];
}

export function HandoffSection({ handoff, fieldSpecs }: HandoffSectionProps) {
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

  const cardValues = handoff.card_values;
  const groups = groupVisibleCardFields(fieldSpecs, cardValues, (spec) => spec.field_path in cardValues);

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
                  <dt className="text-xs text-muted-foreground">{spec.label_ru}</dt>
                  <dd className="text-sm">{formatFactValueRu(spec, cardValues[spec.field_path])}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
