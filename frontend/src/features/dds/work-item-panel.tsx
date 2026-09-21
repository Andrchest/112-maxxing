// The DDS incoming work item panel (SPEC §10, §11; D3). Renders the frozen `card_values` the
// snapshot/`DdsStageView` carries, verbatim — never a live `OperatorCard` value (D3, SPEC §42
// test 3: DDS is constructed without a WorldTruth/OperatorCard repository, so there is nothing
// else this panel could show even if it wanted to). A field in `missing_field_paths` renders using
// the `ddsMissingFieldNotice` string (`ru.ts`), never a guessed value — SPEC §10: if the 112
// operator omitted a critical fact, the omission propagates.
//
// `DdsWorkItem` is manager-ruled to be ONE stage-wide work item — several recipient services
// inside it, resource-id lists unioned across them — so this panel never renders "N work items";
// it renders the one `work_item` the store holds.
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { groupCardFields } from '@/entities/card';
import { useWorkItemStore } from '@/entities/work-item';
import { DDS_CARD_FIELDS, cardFieldLabelRu, formatFactValueRu } from './card-field-labels';
import { serviceTypeLabelRu } from './dds-labels';

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

export function WorkItemPanel() {
  const workItem = useWorkItemStore((state) => state.workItem);

  if (!workItem) {
    return null;
  }

  const missing = new Set(workItem.missing_field_paths);
  const relevantFields = DDS_CARD_FIELDS.filter(
    (spec) => spec.field_path in workItem.card_values || missing.has(spec.field_path),
  );
  const groups = groupCardFields(relevantFields);

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
          <div key={group.key} className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{groupLabel(group.key)}</h3>
            <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {group.fields.map((spec) => {
                const isMissing = missing.has(spec.field_path);
                return (
                  <div key={spec.field_path} className="flex flex-col gap-0.5">
                    <dt className="text-xs text-muted-foreground">{cardFieldLabelRu(spec.field_path)}</dt>
                    <dd className={isMissing ? 'text-sm text-amber-600' : 'text-sm'}>
                      {isMissing ? t('ddsMissingFieldNotice') : formatFactValueRu(spec, workItem.card_values[spec.field_path] ?? null)}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
