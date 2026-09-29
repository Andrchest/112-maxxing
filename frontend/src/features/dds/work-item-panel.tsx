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
// I4 E21 (owner decision 2026-09-25, docs/owner-decisions.md): the memo workstation has no «Получатели»
// badge row — the reference screen has none, and the services tab bar (`legs-panel.tsx`) already
// shows one tab per recipient service. `RESOURCE_PICKER`, which has no tab bar and keeps its UI
// unchanged, still passes `showRecipients`.
//
// `DdsWorkItem` is manager-ruled to be ONE stage-wide work item — several recipient services
// inside it, resource-id lists unioned across them — so this panel never renders "N work items";
// it renders the one `work_item` the store holds.
import { useState } from 'react';
import { Pencil } from 'lucide-react';
import { Badge } from '@/shared/ui/badge';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { hasAvailableAction, useWorkItemStore } from '@/entities/work-item';
import { problemMessageRu, setDdsCardMarks, type ProblemCode } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { formatCallDurationMs } from '@/entities/call';
import type { CardFieldSpec, FactValue } from '@/entities/card';
import { cardOptionLabelRu, formatCardValueRu, groupVisibleCardFields, isCardFieldVisible, isCardValueFilled, serviceTypeLabelRu } from './card-schema-render';

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

const LEFT_COLUMN_GROUPS = ['applicant', 'address', 'description'];
const DARK_BAR_GROUPS = ['q_fire', 'q_gas', 'q_explosion', 'q_ambulance'];
const RIGHT_COLUMN_GROUPS = [...DARK_BAR_GROUPS, 'incident'];
const KNOWN_GROUPS = new Set(['header', ...LEFT_COLUMN_GROUPS, 'flags', ...RIGHT_COLUMN_GROUPS]);

// I3 E7a (manager review): the dark bar's own title IS the selected incident type's label (the
// reference's «Происшествие 101»), not a static group heading — the same three questionnaire-
// backed `incident.types` codes `card-schema-render.ts`'s own override table keys off.
const DARK_BAR_GROUP_TO_INCIDENT_TYPE_CODE: Record<string, string> = {
  q_fire: '1',
  q_gas: '13',
  q_explosion: '3',
  q_ambulance: '22', // I7 E55: «Происшествие 103»
};

/** The ДДС screen's «[ВИС] Класс.:» row (`screenshot-dds/image6.png`, REQ-3040) shows the 112
 * card's own classifier code, read-only — owner decision 2026-09-29, Q9 (I7 E55). It reuses the
 * «Класс.:» row this panel already rendered for `incident.classifier_code` (I3 E7a) under the
 * reference's own «[ВИС] Класс.» label, and — like the reference — keeps the row when empty. */
const CLASSIFIER_CODE_PATH = 'incident.classifier_code';

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

/** One "value . value ." line — no labels, the reference's own dark-bar sentence shape
 * (`screenshot-dds/image6.png`: «Дом . Открытое пламя / Дым (дом), Запах гари (дом) . …»,
 * manager review). Still driven entirely by `field_specs`/`values` — only the label prefix
 * `FieldSentence` prints is dropped. */
function ValueSentence({ fields, values, missing }: FieldSentenceProps) {
  return (
    <p className="text-sm leading-relaxed">
      {fields.map((spec) => {
        const isMissing = missing.has(spec.field_path);
        return (
          <span key={spec.field_path} className="mr-1">
            <span className={isMissing ? 'text-amber-400' : undefined}>
              {isMissing ? t('ddsMissingFieldNotice') : valueSentenceText(spec, values[spec.field_path])}
            </span>
            <span className="opacity-80"> .</span>
          </span>
        );
      })}
    </p>
  );
}

/** A value of the dark-bar sentence. A one-option `BOOLEAN` that is on reads as its option — the
 * reference's own wording («Отказ от реагирования Скорой», I7 E55), never a bare «да» without a
 * label; off, it keeps its label («Отказ от реагирования: нет»). */
function valueSentenceText(spec: CardFieldSpec, value: FactValue | undefined): string {
  if (spec.value_type === 'BOOLEAN' && spec.options?.length === 1) {
    return value === true ? spec.options[0]!.label_ru : `${spec.label_ru}: ${formatCardValueRu(spec, value)}`;
  }
  return formatCardValueRu(spec, value);
}

/** The actions a memo stage offers while the ДДС still holds the card — the same pair the backend's
 * `setDdsCardMarks` gate asks for (I7 E55). */
const MARKS_GATE_ACTION_IDS = ['set_service_status', 'close'];

interface DdsCardMarksProps {
  sessionId: string;
}

/** The reference's «ЧС» / «ЧП» toggles with the pencil (`screenshot-dds/image6.png`; owner decision
 * 2026-09-29, Q9, I7 E55): read-only until the pencil is pressed; each toggle then commits the
 * whole pair with one `setDdsCardMarks`. The shown value is always the server's (the command's
 * answer, or `DDS_CARD_MARKS_SET` folded by `applyWorkItemEvent` for another ДДС's pencil). */
function DdsCardMarks({ sessionId }: DdsCardMarksProps) {
  const workItem = useWorkItemStore((state) => state.workItem);
  const availableActions = useWorkItemStore((state) => state.availableActions);
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!workItem) return null;
  const marks = workItem.dds_marks ?? { chs: false, chp: false };
  const editable = MARKS_GATE_ACTION_IDS.some((actionId) => hasAvailableAction(availableActions, actionId));

  async function toggle(mark: 'chs' | 'chp'): Promise<void> {
    setPending(true);
    setError(null);
    try {
      const answer = await setDdsCardMarks(sessionId, { ...marks, [mark]: !marks[mark] });
      const current = useWorkItemStore.getState().workItem;
      if (current) useWorkItemStore.getState().setWorkItem({ ...current, dds_marks: answer.dds_marks });
    } catch (caught) {
      setError(caught instanceof ProblemError ? problemMessageRu(caught.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPending(false);
    }
  }

  const buttons: { mark: 'chs' | 'chp'; label: string; onClass: string }[] = [
    { mark: 'chs', label: t('ddsMarkChs'), onClass: '' },
    { mark: 'chp', label: t('ddsMarkChp'), onClass: 'bg-orange-500 text-white hover:bg-orange-500/90' },
  ];
  return (
    <div className="flex flex-col gap-1" data-slot="dds-card-marks">
      <div className="flex items-center gap-1.5" role="group" aria-label={t('ddsMarksLabel')}>
        {buttons.map(({ mark, label, onClass }) => (
          <Button
            key={mark}
            type="button"
            size="sm"
            variant={marks[mark] ? 'default' : 'outline'}
            className={marks[mark] ? onClass : undefined}
            aria-pressed={marks[mark]}
            disabled={!editing || pending}
            onClick={() => void toggle(mark)}
          >
            {label}
          </Button>
        ))}
        {editable ? (
          <Button
            type="button"
            size="sm"
            variant={editing ? 'secondary' : 'ghost'}
            aria-label={editing ? t('ddsMarksDoneButton') : t('ddsMarksEditButton')}
            title={editing ? t('ddsMarksDoneButton') : t('ddsMarksEditButton')}
            aria-pressed={editing}
            onClick={() => setEditing((value) => !value)}
          >
            <Pencil className="size-4" />
          </Button>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

interface WorkItemPanelProps {
  /** The «Получатели» badge row: only the `RESOURCE_PICKER` console, which has no tab bar. */
  showRecipients?: boolean;
  /** I7 E55: the memo console's session — renders the «ЧС» / «ЧП» marks with the pencil. The
   * picker console passes none (the marks belong to the memo workstation). */
  sessionId?: string;
}

export function WorkItemPanel({ showRecipients = false, sessionId }: WorkItemPanelProps) {
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

  // I3 E7a (manager review): incident.types is the dark bar's own title now, never a separate
  // "label: value" line under it — dropped from the incident group's other fields
  // (incident.classifier_code, and a v1 card's own incident.type), which still render as their
  // own separate light rows below the bar(s), as the reference shows. A type with no
  // questionnaire branch of its own (no schema TODO covers it, v2.yaml) still shows its label
  // somewhere — as a plain line, only when no dark bar rendered at all.
  const incidentGroupFields = byKey.get('incident') ?? [];
  const incidentTypesField = incidentGroupFields.find((spec) => spec.field_path === 'incident.types');
  const otherIncidentFields = incidentGroupFields.filter((spec) => spec.field_path !== 'incident.types' && spec.field_path !== CLASSIFIER_CODE_PATH);
  const renderedDarkBarKeys = DARK_BAR_GROUPS.filter((key) => (byKey.get(key)?.length ?? 0) > 0);
  const classifierCodeSpec = fieldSpecs.find((spec) => spec.field_path === CLASSIFIER_CODE_PATH);
  const classifierCode = workItem.card_values[CLASSIFIER_CODE_PATH];

  function darkBarTitle(key: string): string {
    const code = DARK_BAR_GROUP_TO_INCIDENT_TYPE_CODE[key];
    if (incidentTypesField && code) {
      return cardOptionLabelRu(incidentTypesField, code);
    }
    return groupLabel(key);
  }

  return (
    <Card data-tour="dds-card">
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('ddsWorkItemTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {showRecipients ? (
          <div className="flex flex-wrap items-center gap-2" data-slot="dds-recipients-row">
            <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              {t('ddsWorkItemRecipientsLabel')}
            </span>
            {workItem.recipient_services.map((service) => (
              <Badge key={service} variant="outline">
                {serviceTypeLabelRu(service)}
              </Badge>
            ))}
          </div>
        ) : null}

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
            {sessionId ? <DdsCardMarks sessionId={sessionId} /> : null}
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
            {renderedDarkBarKeys.map((key) => {
              const fields = byKey.get(key)!;
              return (
                // I3 E7a (D20, ui-check D-9, manager review): solid `bg-foreground` — the
                // reference's dark bar is a flat fill, not translucent (sampled pixel-exact
                // against `screenshot-dds/image6.png`: `#303335`, this theme's own `--foreground`
                // in `.reference-light`, `src/index.css`). The title IS the selected incident
                // type's own label (`darkBarTitle`, not a static small-caps group heading — the
                // reference's «Происшествие 101» is normal case), and the sentence under it is
                // values only (`ValueSentence`), never "label: value" pairs.
                <div key={key} className="flex flex-col gap-1 rounded-md bg-foreground p-2 text-background" data-slot="dds-questionnaire-bar">
                  <h3 className="text-sm font-semibold">{darkBarTitle(key)}</h3>
                  <ValueSentence fields={fields} values={workItem.card_values} missing={missing} />
                </div>
              );
            })}
            {/* A type with no questionnaire branch of its own (so no dark bar rendered above it
                at all) still shows its own label somewhere, never silently dropped. */}
            {incidentTypesField && renderedDarkBarKeys.length === 0 ? (
              <FieldSentence fields={[incidentTypesField]} values={workItem.card_values} missing={missing} />
            ) : null}
            {/* A v1 card's own `incident.type` (and any other incident field) — separate light
                rows under the bar(s), as the reference shows (manager review). */}
            {otherIncidentFields.map((spec) => {
              const isMissing = missing.has(spec.field_path);
              return (
                <p key={spec.field_path} className="text-sm" data-slot="dds-incident-field-line">
                  <span className="text-muted-foreground">{spec.label_ru}: </span>
                  <span className={isMissing ? 'text-amber-600' : undefined}>
                    {isMissing ? t('ddsMissingFieldNotice') : formatCardValueRu(spec, workItem.card_values[spec.field_path])}
                  </span>
                </p>
              );
            })}
            {/* «[ВИС] Класс.:» — the 112 card's classifier code, read-only, always shown for a
                schema that has the field (the reference shows the row even when empty). */}
            {classifierCodeSpec && isCardFieldVisible(classifierCodeSpec, workItem.card_values) ? (
              <p className="text-sm" data-slot="dds-incident-field-line" data-field-path={CLASSIFIER_CODE_PATH}>
                <span className="text-muted-foreground">{t('ddsVisClassifierLabel')}: </span>
                <span>{isCardValueFilled(classifierCode) ? formatCardValueRu(classifierCodeSpec, classifierCode) : ''}</span>
              </p>
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
