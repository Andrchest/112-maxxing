// The DDS incoming work item panel (SPEC §10, §11; D3). Renders the frozen `card_values` the
// snapshot/`DdsStageView` carries, verbatim — never a live `OperatorCard` value (D3, SPEC §42
// test 3: DDS is constructed without a WorldTruth/OperatorCard repository, so there is nothing
// else this panel could show even if it wanted to). A field in `missing_field_paths` renders using
// the `ddsMissingFieldNotice` string (`ru.ts`), never a guessed value — SPEC §10: if the 112
// operator omitted a critical fact, the omission propagates.
//
// Renders from `DdsWorkItem.field_specs` (I3 E3a′/E3c, HLD 70 §70.5.4, D17) as flowing
// "label: value" sentences per group (ui-check D-9: readable, not a raw field dump), never from a
// hard-coded field-path catalog. Works identically for a v1 or a v2 card, and for a `GENERATED_CARD`
// session (§70.5.4's "generated-card mode") — this panel never branches on the card schema or the
// session's `card_source`, only on the specs the server sends. Empty values (never set) and fields
// `visible_when` hides for this card's own values are both omitted (`groupVisibleCardFields`).
//
// `DdsWorkItem` is manager-ruled to be ONE stage-wide work item — several recipient services
// inside it, resource-id lists unioned across them — so this panel never renders "N work items";
// it renders the one `work_item` the store holds.
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useWorkItemStore } from '@/entities/work-item';
import { formatCardValueRu, groupVisibleCardFields, isCardValueFilled, serviceTypeLabelRu } from './card-schema-render';

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

function groupLabel(key: string): string {
  return t(GROUP_LABEL_KEY[key] ?? 'operatorGroupOther');
}

export function WorkItemPanel() {
  const workItem = useWorkItemStore((state) => state.workItem);

  if (!workItem) {
    return null;
  }

  const missing = new Set(workItem.missing_field_paths);
  const fieldSpecs = workItem.field_specs ?? [];
  const groups = groupVisibleCardFields(
    fieldSpecs,
    workItem.card_values,
    (spec) => isCardValueFilled(workItem.card_values[spec.field_path]) || missing.has(spec.field_path),
  );

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('ddsWorkItemTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            {t('ddsWorkItemRecipientsLabel')}
          </span>
          {workItem.recipient_services.map((service) => (
            <Badge key={service} variant="outline">
              {serviceTypeLabelRu(service)}
            </Badge>
          ))}
        </div>
        {groups.map((group) => (
          <div key={group.key} className="flex flex-col gap-1">
            <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{groupLabel(group.key)}</h3>
            <p className="text-sm leading-relaxed">
              {group.fields.map((spec) => {
                const isMissing = missing.has(spec.field_path);
                return (
                  <span key={spec.field_path} className="mr-1">
                    <span className="text-muted-foreground">{spec.label_ru}: </span>
                    <span className={isMissing ? 'text-amber-600' : undefined}>
                      {isMissing ? t('ddsMissingFieldNotice') : formatCardValueRu(spec, workItem.card_values[spec.field_path])}
                    </span>
                    <span className="text-muted-foreground"> .</span>
                  </span>
                );
              })}
            </p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
