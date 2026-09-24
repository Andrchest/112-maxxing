// The DDS card summary (SPEC §10, §11; D3; I3 E5c manager review — restructured to the
// reference's left/right column shape, `ref/screenshot-dds/image6.png`). Renders the frozen
// `card_values` the snapshot/`DdsStageView` carries, verbatim — never a live `OperatorCard` value
// (D3, SPEC §42 test 3). A field in `missing_field_paths` renders using the `ddsMissingFieldNotice`
// string (`ru.ts`), never a guessed value — SPEC §10: if the 112 operator omitted a critical fact,
// the omission propagates.
//
// Renders from `DdsWorkItem.field_specs` (I3 E3a′/E3c, HLD 70 §70.5.4, D17) as flowing
// "label: value" sentences per group (ui-check D-9: readable, not a raw field dump), never from a
// hard-coded field-path catalog. Works identically for a v1 or a v2 card. The `header` group moved
// to `DdsHeaderStrip` (the reference's phone-row strip); everything else keeps the group it always
// had — `applicant`/`address`/`description` on the left, `flags`/the questionnaire groups
// (`q_fire`/`q_gas`/`q_explosion`, the reference's dark title bar)/`incident` on the right, any
// other group (a v1 schema's derived groups, `services`/`recipients` overflow fields) rendered
// below both columns so nothing the schema sends is ever silently dropped.
//
// `DdsWorkItem` is manager-ruled to be ONE stage-wide work item — several recipient services
// inside it, resource-id lists unioned across them — so this panel never renders "N work items";
// it renders the one `work_item` the store holds.
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useWorkItemStore } from '@/entities/work-item';
import { formatCallDurationMs } from '@/entities/call';
import type { CardFieldSpec, FactValue } from '@/entities/card';
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

const LEFT_COLUMN_GROUPS = ['applicant', 'address', 'description'];
const DARK_BAR_GROUPS = ['q_fire', 'q_gas', 'q_explosion'];
const RIGHT_COLUMN_GROUPS = [...DARK_BAR_GROUPS, 'incident'];
const KNOWN_GROUPS = new Set(['header', ...LEFT_COLUMN_GROUPS, 'flags', ...RIGHT_COLUMN_GROUPS]);

interface FieldSentenceProps {
  fields: readonly CardFieldSpec[];
  values: Readonly<Record<string, FactValue>>;
  missing: ReadonlySet<string>;
}

/** One "label: value . label: value ." line — the same flowing-sentence rule every group here
 * has always used (ui-check D-9). */
function FieldSentence({ fields, values, missing }: FieldSentenceProps) {
  return (
    <p className="text-sm leading-relaxed">
      {fields.map((spec) => {
        const isMissing = missing.has(spec.field_path);
        return (
          <span key={spec.field_path} className="mr-1">
            <span className="text-muted-foreground">{spec.label_ru}: </span>
            <span className={isMissing ? 'text-amber-600' : undefined}>
              {isMissing ? t('ddsMissingFieldNotice') : formatCardValueRu(spec, values[spec.field_path])}
            </span>
            <span className="text-muted-foreground"> .</span>
          </span>
        );
      })}
    </p>
  );
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
  const byKey = new Map(groups.map((group) => [group.key, group.fields]));
  const otherGroups = groups.filter((group) => !KNOWN_GROUPS.has(group.key));
  const flagsFields = byKey.get('flags') ?? [];

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

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* Left: applicant, address, a dated description entry (the reference's applicant/
              address/timestamped-description column, ref/screenshot-dds/image6.png). */}
          <div className="flex flex-col gap-3" data-slot="dds-card-left">
            {LEFT_COLUMN_GROUPS.filter((key) => key !== 'description').map((key) => {
              const fields = byKey.get(key);
              if (!fields || fields.length === 0) return null;
              return (
                <div key={key} className="flex flex-col gap-1">
                  <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{groupLabel(key)}</h3>
                  <FieldSentence fields={fields} values={workItem.card_values} missing={missing} />
                </div>
              );
            })}
            {byKey.get('description') && byKey.get('description')!.length > 0 ? (
              <div className="flex flex-col gap-1" data-slot="dds-description-entry">
                {/* The reference's dated description entry (image6.png: "17.09.2026 11:13:19 …
                    Пожар в квартире") — this UI has no wall-clock timestamp per entry, only the
                    simulation's elapsed offset (D7), used here instead; noted as a remaining
                    difference in the E5c report. */}
                <span className="text-xs text-muted-foreground">
                  {t('ddsWorkItemReceivedLabel')}: {formatCallDurationMs(workItem.received_at_offset_ms)}
                </span>
                <FieldSentence fields={byKey.get('description')!} values={workItem.card_values} missing={missing} />
              </div>
            ) : null}
          </div>

          {/* Right: the flags line, one dark title bar per questionnaire group present (the
              reference's «Происшествие 101» bar), then the incident/classifier line. */}
          <div className="flex flex-col gap-3" data-slot="dds-card-right">
            {flagsFields.length > 0 ? (
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm" data-slot="dds-flags-line">
                {flagsFields.map((spec) => {
                  const isMissing = missing.has(spec.field_path);
                  return (
                    <span key={spec.field_path}>
                      <span className="text-muted-foreground">{spec.label_ru}: </span>
                      <span className={isMissing ? 'text-amber-600' : undefined}>
                        {isMissing ? t('ddsMissingFieldNotice') : formatCardValueRu(spec, workItem.card_values[spec.field_path])}
                      </span>
                    </span>
                  );
                })}
              </div>
            ) : null}
            {DARK_BAR_GROUPS.map((key) => {
              const fields = byKey.get(key);
              if (!fields || fields.length === 0) return null;
              return (
                <div key={key} className="flex flex-col gap-1 rounded-md bg-foreground/90 p-2 text-background" data-slot="dds-questionnaire-bar">
                  <h3 className="text-xs font-semibold tracking-wide uppercase">{groupLabel(key)}</h3>
                  <FieldSentence fields={fields} values={workItem.card_values} missing={missing} />
                </div>
              );
            })}
            {byKey.get('incident') && byKey.get('incident')!.length > 0 ? (
              <FieldSentence fields={byKey.get('incident')!} values={workItem.card_values} missing={missing} />
            ) : null}
          </div>
        </div>

        {otherGroups.map((group) => (
          <div key={group.key} className="flex flex-col gap-1">
            <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{groupLabel(group.key)}</h3>
            <FieldSentence fields={group.fields} values={workItem.card_values} missing={missing} />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
