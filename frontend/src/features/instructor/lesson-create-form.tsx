// I3 E4b (70 §70.3.1-§70.3.3, D15): the instructor's plan editor for a Lesson (занятие) of N
// cards. Each `PlanEntry` picks a scenario version, an arrival (kind + offset/delay) and, per
// card, the same variant switches E1's `CreateSessionForm` offers — same `ru.ts` keys, same
// "every value listed, unsupported ones disabled" reading of `ScenarioVariantsView`
// (`create-session-form.tsx`'s own comment). `createLesson` validates the whole plan and creates
// every session at once (openapi.yaml); nothing here computes a card status or a session state.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { Card, CardContent, CardFooter, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { ProblemError } from '@/shared/lib/api';
import {
  createLesson,
  listScenarios,
  listScenarioVersions,
  listUsers,
  problemMessageRu,
  queryKeys,
  type ArrivalKind,
  type CardSource,
  type DdsBrigadeCall,
  type DdsCardCheck,
  type DdsMode,
  type LessonCreateRequest,
  type LessonDetail,
  type ProblemCode,
  type RoleType,
  type ScenarioVariantsView,
  type ScenarioVersionListItem,
  type SessionMode,
  type SessionVariants,
} from '@/shared/api';
import { arrivalKindLabelRu } from '@/features/lesson/lesson-labels';

const SESSION_MODES: readonly SessionMode[] = [
  'SINGLE_ROLE',
  'FULL_CYCLE_SINGLE_TRAINEE',
  'MULTI_TRAINEE',
  'ASSESSMENT',
];

const SESSION_MODE_LABEL_KEY: Record<SessionMode, keyof typeof ru> = {
  SINGLE_ROLE: 'instructorSessionModeSingleRole',
  FULL_CYCLE_SINGLE_TRAINEE: 'instructorSessionModeFullCycle',
  MULTI_TRAINEE: 'instructorSessionModeMultiTrainee',
  ASSESSMENT: 'instructorSessionModeAssessment',
};

const ROLE_TYPE_LABEL_KEY: Record<RoleType, keyof typeof ru> = {
  OPERATOR_112: 'roleTypeOperator112',
  DDS: 'roleTypeDds',
  EDDS: 'roleTypeEdds',
};

// Same picker set/labels `create-session-form.tsx` uses (70 §70.2) — every value of the switch is
// listed, a value outside the version's `supported` list is disabled with the same Russian note.
type VariantSwitch = keyof SessionVariants;

const VARIANT_SWITCHES: readonly VariantSwitch[] = ['card_source', 'dds_mode', 'dds_card_check', 'dds_brigade_call'];

const VARIANT_SWITCH_LABEL_KEY: Record<VariantSwitch, keyof typeof ru> = {
  card_source: 'instructorVariantCardSourceLabel',
  dds_mode: 'instructorVariantDdsModeLabel',
  dds_card_check: 'instructorVariantDdsCardCheckLabel',
  dds_brigade_call: 'instructorVariantDdsBrigadeCallLabel',
};

const CARD_SOURCE_LABEL_KEY: Record<CardSource, keyof typeof ru> = {
  GENERATED_CARD: 'variantCardSourceGeneratedCard',
  CALLER_VOICE: 'variantCardSourceCallerVoice',
};
const DDS_MODE_LABEL_KEY: Record<DdsMode, keyof typeof ru> = {
  MEMO_STATUSES: 'variantDdsModeMemoStatuses',
  RESOURCE_PICKER: 'variantDdsModeResourcePicker',
};
const DDS_CARD_CHECK_LABEL_KEY: Record<DdsCardCheck, keyof typeof ru> = {
  OFF: 'variantDdsCardCheckOff',
  ON: 'variantDdsCardCheckOn',
};
const DDS_BRIGADE_CALL_LABEL_KEY: Record<DdsBrigadeCall, keyof typeof ru> = {
  OFF: 'variantDdsBrigadeCallOff',
  ON: 'variantDdsBrigadeCallOn',
};

const VARIANT_VALUE_LABEL_KEYS: { [K in VariantSwitch]: Record<SessionVariants[K], keyof typeof ru> } = {
  card_source: CARD_SOURCE_LABEL_KEY,
  dds_mode: DDS_MODE_LABEL_KEY,
  dds_card_check: DDS_CARD_CHECK_LABEL_KEY,
  dds_brigade_call: DDS_BRIGADE_CALL_LABEL_KEY,
};

function variantValues(variantSwitch: VariantSwitch): string[] {
  return Object.keys(VARIANT_VALUE_LABEL_KEYS[variantSwitch]);
}

function variantValueLabel(variantSwitch: VariantSwitch, value: string): string {
  const key = (VARIANT_VALUE_LABEL_KEYS[variantSwitch] as Record<string, keyof typeof ru>)[value];
  return key ? t(key) : value;
}

function isSupported(view: ScenarioVariantsView, variantSwitch: VariantSwitch, value: string): boolean {
  return (view.supported[variantSwitch] as readonly string[]).includes(value);
}

/** Same reading `create-session-form.tsx` uses: under `GENERATED_CARD` only the `role_chain`
 * suffix starting at DDS runs. */
function effectiveRoleChain(roleChain: readonly RoleType[], cardSource: CardSource | undefined): RoleType[] {
  if (cardSource !== 'GENERATED_CARD') return [...roleChain];
  const ddsIndex = roleChain.indexOf('DDS');
  return ddsIndex < 0 ? [] : roleChain.slice(ddsIndex);
}

interface ParticipantRow {
  userId: string;
  assignedRoleType: RoleType | null;
}

function buildParticipantRows(mode: SessionMode, roleChain: readonly RoleType[]): ParticipantRow[] {
  if (mode === 'FULL_CYCLE_SINGLE_TRAINEE') {
    return [{ userId: '', assignedRoleType: null }];
  }
  return roleChain.map((roleType) => ({ userId: '', assignedRoleType: roleType }));
}

interface PlanEntryRow {
  key: number;
  scenarioId: string;
  versionId: string;
  version: ScenarioVersionListItem | null;
  arrivalKind: ArrivalKind;
  offsetMs: number;
  delayMs: number;
  variants: SessionVariants | null;
  weight: number;
}

function makeEntry(key: number, defaultOffsetMs: number): PlanEntryRow {
  return {
    key,
    scenarioId: '',
    versionId: '',
    version: null,
    arrivalKind: 'AT_OFFSET',
    offsetMs: defaultOffsetMs,
    delayMs: 0,
    variants: null,
    weight: 1,
  };
}

function ProblemAlert({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
  return (
    <p role="alert" className="text-sm text-destructive">
      {message}
    </p>
  );
}

interface PlanEntryFieldsProps {
  row: PlanEntryRow;
  index: number;
  isFirst: boolean;
  canRemove: boolean;
  onChange: (patch: Partial<PlanEntryRow>) => void;
  onRemove: () => void;
}

function PlanEntryFields({ row, index, isFirst, canRemove, onChange, onRemove }: PlanEntryFieldsProps) {
  const scenariosQuery = useQuery({ queryKey: queryKeys.scenarios.list(), queryFn: listScenarios });
  const versionsQuery = useQuery({
    queryKey: queryKeys.scenarios.versions(row.scenarioId),
    queryFn: () => listScenarioVersions(row.scenarioId),
    enabled: row.scenarioId !== '',
  });

  function handleScenarioChange(nextScenarioId: string) {
    onChange({ scenarioId: nextScenarioId, versionId: '', version: null, variants: null });
  }

  function handleVersionChange(nextVersionId: string) {
    const nextVersion = versionsQuery.data?.items.find((version) => version.id === nextVersionId) ?? null;
    onChange({ versionId: nextVersionId, version: nextVersion, variants: nextVersion?.variants.default ?? null });
  }

  function handleVariantChange(variantSwitch: VariantSwitch, value: string) {
    if (!row.variants) return;
    onChange({ variants: { ...row.variants, [variantSwitch]: value } as SessionVariants });
  }

  return (
    <fieldset className="flex flex-col gap-2 rounded-md border border-border p-2" data-slot="plan-entry">
      <legend className="px-1 text-sm font-medium">
        {t('lessonFormEntryLabel')} {index + 1}
      </legend>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`lesson-entry-${row.key}-scenario`}>{t('lessonFormEntryScenarioLabel')}</Label>
        <select
          id={`lesson-entry-${row.key}-scenario`}
          className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
          value={row.scenarioId}
          onChange={(event) => handleScenarioChange(event.target.value)}
          disabled={scenariosQuery.isLoading}
        >
          <option value="">{t('lessonFormSelectScenarioPlaceholder')}</option>
          {(scenariosQuery.data?.items ?? []).map((scenario) => (
            <option key={scenario.scenario_id} value={scenario.scenario_id}>
              {scenario.title_ru}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`lesson-entry-${row.key}-version`}>{t('lessonFormEntryVersionLabel')}</Label>
        <select
          id={`lesson-entry-${row.key}-version`}
          className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
          value={row.versionId}
          onChange={(event) => handleVersionChange(event.target.value)}
          disabled={row.scenarioId === '' || versionsQuery.isLoading}
        >
          <option value="">{t('lessonFormSelectVersionPlaceholder')}</option>
          {(versionsQuery.data?.items ?? []).map((version) => (
            <option key={version.id} value={version.id}>
              {version.title} (v{version.version})
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`lesson-entry-${row.key}-arrival`}>{t('lessonFormEntryArrivalKindLabel')}</Label>
        {isFirst ? (
          <p className="text-xs text-muted-foreground" data-slot="arrival-first-note">
            {t('lessonFormEntryArrivalFirstNote')}
          </p>
        ) : (
          <select
            id={`lesson-entry-${row.key}-arrival`}
            className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            value={row.arrivalKind}
            onChange={(event) => onChange({ arrivalKind: event.target.value as ArrivalKind })}
          >
            {(['AT_OFFSET', 'AFTER_PREVIOUS_112_STAGE', 'AFTER_PREVIOUS_SESSION'] as const).map((kind) => (
              <option key={kind} value={kind}>
                {arrivalKindLabelRu(kind)}
              </option>
            ))}
          </select>
        )}
        {row.arrivalKind === 'AT_OFFSET' ? (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`lesson-entry-${row.key}-offset`}>{t('lessonFormEntryOffsetLabel')}</Label>
            <Input
              id={`lesson-entry-${row.key}-offset`}
              type="number"
              min={0}
              value={row.offsetMs}
              onChange={(event) => onChange({ offsetMs: Number(event.target.value) })}
            />
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`lesson-entry-${row.key}-delay`}>{t('lessonFormEntryDelayLabel')}</Label>
            <Input
              id={`lesson-entry-${row.key}-delay`}
              type="number"
              min={0}
              value={row.delayMs}
              onChange={(event) => onChange({ delayMs: Number(event.target.value) })}
            />
          </div>
        )}
      </div>

      {row.version && row.variants ? (
        <fieldset className="flex flex-col gap-2" data-slot="variant-pickers">
          <legend className="text-xs font-medium text-muted-foreground">{t('lessonFormVariantsLabel')}</legend>
          {VARIANT_SWITCHES.map((variantSwitch) => (
            <div key={variantSwitch} className="flex flex-col gap-1.5">
              <Label htmlFor={`lesson-entry-${row.key}-variant-${variantSwitch}`}>
                {t(VARIANT_SWITCH_LABEL_KEY[variantSwitch])}
              </Label>
              <select
                id={`lesson-entry-${row.key}-variant-${variantSwitch}`}
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                value={row.variants![variantSwitch]}
                onChange={(event) => handleVariantChange(variantSwitch, event.target.value)}
              >
                {variantValues(variantSwitch).map((value) => {
                  const supported = isSupported(row.version!.variants, variantSwitch, value);
                  return (
                    <option key={value} value={value} disabled={!supported}>
                      {supported
                        ? variantValueLabel(variantSwitch, value)
                        : `${variantValueLabel(variantSwitch, value)} — ${t('instructorVariantUnavailableSuffix')}`}
                    </option>
                  );
                })}
              </select>
            </div>
          ))}
        </fieldset>
      ) : null}

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`lesson-entry-${row.key}-weight`}>{t('lessonFormEntryWeightLabel')}</Label>
        <Input
          id={`lesson-entry-${row.key}-weight`}
          type="number"
          min={0}
          step="0.1"
          value={row.weight}
          onChange={(event) => onChange({ weight: Number(event.target.value) })}
        />
      </div>

      {canRemove ? (
        <Button type="button" variant="outline" size="sm" onClick={onRemove}>
          {t('lessonFormEntryRemoveButton')}
        </Button>
      ) : null}
    </fieldset>
  );
}

interface LessonCreateFormProps {
  onCreated?: (lesson: LessonDetail) => void;
}

export function LessonCreateForm({ onCreated }: LessonCreateFormProps) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState('');
  const [sessionMode, setSessionMode] = useState<SessionMode>('SINGLE_ROLE');
  const [nextKey, setNextKey] = useState(1);
  const [entries, setEntries] = useState<PlanEntryRow[]>([makeEntry(0, 0)]);
  const [participants, setParticipants] = useState<ParticipantRow[]>([]);

  const traineesQuery = useQuery({
    queryKey: queryKeys.users.list('TRAINEE'),
    queryFn: () => listUsers({ role: 'TRAINEE' }),
  });

  const createMutation = useMutation({
    mutationFn: createLesson,
    onSuccess: (lesson) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.lessons.list('ALL') });
      onCreated?.(lesson);
    },
  });

  function roleChainFor(nextEntries: PlanEntryRow[]): RoleType[] {
    const seen = new Set<RoleType>();
    const chain: RoleType[] = [];
    for (const row of nextEntries) {
      if (!row.version) continue;
      for (const role of effectiveRoleChain(row.version.role_chain, row.variants?.card_source)) {
        if (!seen.has(role)) {
          seen.add(role);
          chain.push(role);
        }
      }
    }
    return chain;
  }

  function refreshParticipants(nextEntries: PlanEntryRow[], mode: SessionMode) {
    setParticipants(buildParticipantRows(mode, roleChainFor(nextEntries)));
  }

  function updateEntry(index: number, patch: Partial<PlanEntryRow>) {
    setEntries((rows) => {
      const next = rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row));
      refreshParticipants(next, sessionMode);
      return next;
    });
  }

  function addEntry() {
    setEntries((rows) => {
      const maxOffset = rows.reduce((max, row) => (row.arrivalKind === 'AT_OFFSET' ? Math.max(max, row.offsetMs) : max), 0);
      const next = [...rows, makeEntry(nextKey, maxOffset + 60000)];
      refreshParticipants(next, sessionMode);
      return next;
    });
    setNextKey((key) => key + 1);
  }

  function removeEntry(index: number) {
    setEntries((rows) => {
      const next = rows.filter((_, rowIndex) => rowIndex !== index);
      refreshParticipants(next, sessionMode);
      return next;
    });
  }

  function handleModeChange(nextMode: SessionMode) {
    setSessionMode(nextMode);
    refreshParticipants(entries, nextMode);
  }

  function updateParticipantUserId(index: number, userId: string) {
    setParticipants((rows) => rows.map((row, rowIndex) => (rowIndex === index ? { ...row, userId } : row)));
  }

  const entriesValid =
    entries.length > 0 &&
    entries.every((row) => row.versionId !== '') &&
    entries[0]?.arrivalKind === 'AT_OFFSET';
  const canCreate =
    title.trim() !== '' &&
    entriesValid &&
    participants.length > 0 &&
    participants.every((row) => row.userId.trim() !== '') &&
    !createMutation.isPending;

  function handleCreate() {
    if (!canCreate) return;
    const body: LessonCreateRequest = {
      title_ru: title.trim(),
      session_mode: sessionMode,
      participants: participants.map((row) => ({
        user_id: row.userId.trim(),
        assigned_role_type: row.assignedRoleType,
      })),
      // The generated type requires this even though the backend defaults it to 1 (same
      // `create-session-form.tsx` note: openapi's `default: 1` does not make a property optional).
      time_scale: 1,
      scenario_plan: entries.map((row, index) => ({
        position: index + 1,
        scenario_version_id: row.versionId,
        arrival: {
          kind: row.arrivalKind,
          ...(row.arrivalKind === 'AT_OFFSET' ? { offset_ms: row.offsetMs } : {}),
          delay_ms: row.delayMs,
        },
        ...(row.variants ? { variants: row.variants } : {}),
        weight: row.weight,
      })),
    };
    createMutation.mutate(body);
  }

  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('lessonFormTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="lesson-title">{t('lessonFormTitleFieldLabel')}</Label>
          <Input
            id="lesson-title"
            value={title}
            placeholder={t('lessonFormTitlePlaceholder')}
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="lesson-mode">{t('lessonFormModeLabel')}</Label>
          <select
            id="lesson-mode"
            className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            value={sessionMode}
            onChange={(event) => handleModeChange(event.target.value as SessionMode)}
          >
            {SESSION_MODES.map((mode) => (
              <option key={mode} value={mode}>
                {t(SESSION_MODE_LABEL_KEY[mode])}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium">{t('lessonFormPlanLabel')}</span>
          {entries.map((row, index) => (
            <PlanEntryFields
              key={row.key}
              row={row}
              index={index}
              isFirst={index === 0}
              canRemove={entries.length > 1}
              onChange={(patch) => updateEntry(index, patch)}
              onRemove={() => removeEntry(index)}
            />
          ))}
          <Button type="button" variant="outline" size="sm" onClick={addEntry}>
            {t('lessonFormEntryAddButton')}
          </Button>
        </div>

        {participants.length > 0 ? (
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">{t('lessonFormParticipantsLabel')}</span>
            {participants.map((row, index) => (
              <div key={index} className="flex items-end gap-2">
                <div className="flex flex-1 flex-col gap-1.5">
                  <Label htmlFor={`lesson-participant-${index}`}>
                    {row.assignedRoleType
                      ? `${t('instructorParticipantUserIdLabel')} — ${t(ROLE_TYPE_LABEL_KEY[row.assignedRoleType])}`
                      : t('instructorParticipantUserIdLabel')}
                  </Label>
                  <select
                    id={`lesson-participant-${index}`}
                    className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                    value={row.userId}
                    onChange={(event) => updateParticipantUserId(index, event.target.value)}
                    disabled={traineesQuery.isLoading}
                  >
                    <option value="">{t('lessonFormSelectTraineePlaceholder')}</option>
                    {(traineesQuery.data?.items ?? []).map((user) => (
                      <option key={user.id} value={user.id}>
                        {user.display_name_ru}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            ))}
          </div>
        ) : null}

        <ProblemAlert error={createMutation.error} />
      </CardContent>
      <CardFooter>
        <Button type="button" onClick={handleCreate} disabled={!canCreate}>
          {createMutation.isPending ? t('lessonFormCreating') : t('lessonFormCreateButton')}
        </Button>
      </CardFooter>
    </Card>
  );
}
