// I3 E4b (70 §70.3.1-§70.3.3, D15): the instructor's plan editor for a Lesson (занятие) of N
// cards. Each `PlanEntry` picks a scenario version, an arrival (kind + offset/delay) and, per
// card, the same variant switches E1's `CreateSessionForm` offers — same `ru.ts` keys, same
// "every value listed, unsupported ones disabled" reading of `ScenarioVariantsView`
// (`create-session-form.tsx`'s own comment). `createLesson` validates the whole plan and creates
// every session at once (openapi.yaml); nothing here computes a card status or a session state.
//
// I3 E9a (70 §70.3.7, F-15): a lesson may be created for a trainee group (the participants are
// pre-filled from its members and stay editable; `group_id` is recorded); the matrix of plan
// entries × participants («галочки» per workstation) becomes each entry's `participants` (an
// entry ticked for everyone sends none — the backend's "every lesson participant"); every
// scenario and version option shows its «Сложность» and the scenario list filters by it. The
// per-entry weight is a plain number, default 1 — the difficulty is shown beside it, never
// turned into a weight here (AI proposals are reviewed on the lesson page).
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { Card, CardContent, CardFooter, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { ProblemError } from '@/shared/lib/api';
import { useServiceCatalogStore } from '@/entities/service-catalog';
import {
  createLesson,
  listScenarioPage,
  listScenarioVersions,
  listTraineeGroups,
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
  type ScenarioSummary,
  type ScenarioVersionListItem,
  type SessionMode,
  type SessionVariants,
  type TraineeGroup,
} from '@/shared/api';
import { arrivalKindLabelRu } from '@/features/lesson/lesson-labels';
import { isVariantSelectable, withoutPickerPhone, type VariantSwitch } from './variant-selection';

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
  /** I3 E5c (70 §70.4.5, D16) — same field, same reading, as `create-session-form.tsx`. */
  assignedServiceId: string;
}

function buildParticipantRows(mode: SessionMode, roleChain: readonly RoleType[]): ParticipantRow[] {
  if (mode === 'FULL_CYCLE_SINGLE_TRAINEE') {
    return [{ userId: '', assignedRoleType: null, assignedServiceId: '' }];
  }
  return roleChain.map((roleType) => ({ userId: '', assignedRoleType: roleType, assignedServiceId: '' }));
}

/** «Сложность N» before a picker option's own label (F-15 «Классифицировать задания по уровням
 * сложности») — first, so a long ticket title never hides it; nothing when the server has none. */
function withDifficulty(label: string, difficulty: number | null | undefined): string {
  return difficulty ? `${t('difficultyLabel')} ${difficulty} · ${label}` : label;
}

const DIFFICULTIES: readonly number[] = [1, 2, 3, 4, 5];

/** A group row keeps the role it had when it is still in the chain, else the chain's first. */
function buildGroupRows(
  group: TraineeGroup,
  mode: SessionMode,
  roleChain: readonly RoleType[],
  previous: readonly ParticipantRow[],
): ParticipantRow[] {
  return group.members.map((member) => {
    const before = previous.find((row) => row.userId === member.user_id);
    const keep = before?.assignedRoleType && roleChain.includes(before.assignedRoleType) ? before.assignedRoleType : null;
    return {
      userId: member.user_id,
      assignedRoleType: mode === 'FULL_CYCLE_SINGLE_TRAINEE' ? null : (keep ?? roleChain[0] ?? null),
      assignedServiceId: before?.assignedServiceId ?? '',
    };
  });
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
  /** I3 E9a: the ticked participants' user ids, or `null` for every lesson participant. */
  participantUserIds: string[] | null;
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
    participantUserIds: null,
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
  difficultyFilter: number | null;
  onChange: (patch: Partial<PlanEntryRow>) => void;
  onRemove: () => void;
}

function PlanEntryFields({ row, index, isFirst, canRemove, difficultyFilter, onChange, onRemove }: PlanEntryFieldsProps) {
  const scenariosQuery = useQuery({
    queryKey: queryKeys.scenarioPicker.list(),
    queryFn: () => listScenarioPage({ limit: 200 }),
  });
  const scenarioOptions: ScenarioSummary[] = (scenariosQuery.data?.items ?? []).filter(
    (scenario) =>
      difficultyFilter === null || scenario.latest_difficulty === difficultyFilter || scenario.scenario_id === row.scenarioId,
  );
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
    onChange({
      versionId: nextVersionId,
      version: nextVersion,
      variants: nextVersion ? withoutPickerPhone(nextVersion.variants.default) : null,
    });
  }

  function handleVariantChange(variantSwitch: VariantSwitch, value: string) {
    if (!row.variants) return;
    // I4 E21 (D28, R41): switching the entry to the picker turns its phone off.
    onChange({ variants: withoutPickerPhone({ ...row.variants, [variantSwitch]: value } as SessionVariants) });
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
          {scenarioOptions.map((scenario) => (
            <option key={scenario.scenario_id} value={scenario.scenario_id}>
              {withDifficulty(scenario.title_ru, scenario.latest_difficulty)}
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
              {withDifficulty(`${version.title} (v${version.version})`, version.difficulty)}
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
                  const supported = isVariantSelectable(row.version!.variants, row.variants!, variantSwitch, value);
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
        <p className="text-xs text-muted-foreground">{t('lessonFormEntryWeightHint')}</p>
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
  const [groupId, setGroupId] = useState('');
  const [difficultyFilter, setDifficultyFilter] = useState<number | null>(null);

  const groupsQuery = useQuery({ queryKey: queryKeys.traineeGroups.list(), queryFn: listTraineeGroups });
  const selectedGroup = (groupsQuery.data?.items ?? []).find((group) => group.group_id === groupId) ?? null;

  const traineesQuery = useQuery({
    queryKey: queryKeys.users.list('TRAINEE'),
    queryFn: () => listUsers({ role: 'TRAINEE' }),
  });

  // I3 E5c (70 §70.4.5, D16): same app-wide catalog `create-session-form.tsx` reads.
  const serviceCatalogEntries = useServiceCatalogStore((state) => state.entries);
  const serviceCatalogOptions = useMemo(
    () => Object.values(serviceCatalogEntries).filter((entry) => entry.display && !entry.deprecated),
    [serviceCatalogEntries],
  );

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

  function refreshParticipants(nextEntries: PlanEntryRow[], mode: SessionMode, group: TraineeGroup | null = selectedGroup) {
    const chain = roleChainFor(nextEntries);
    if (group) {
      setParticipants((rows) => buildGroupRows(group, mode, chain, rows));
      return;
    }
    setParticipants(buildParticipantRows(mode, chain));
  }

  function handleGroupChange(nextGroupId: string) {
    setGroupId(nextGroupId);
    const group = (groupsQuery.data?.items ?? []).find((item) => item.group_id === nextGroupId) ?? null;
    setEntries((rows) => rows.map((row) => ({ ...row, participantUserIds: null })));
    if (group) {
      setParticipants(buildGroupRows(group, sessionMode, roleChainFor(entries), []));
    } else {
      setParticipants(buildParticipantRows(sessionMode, roleChainFor(entries)));
    }
  }

  function updateParticipantRole(index: number, role: RoleType | null) {
    setParticipants((rows) => rows.map((row, rowIndex) => (rowIndex === index ? { ...row, assignedRoleType: role } : row)));
  }

  // -- the per-workstation matrix («галочки», F-15) ----------------------------------------------
  const chosenUserIds = participants.map((row) => row.userId.trim()).filter((userId) => userId !== '');
  const displayNameOf = (userId: string) =>
    (traineesQuery.data?.items ?? []).find((user) => user.id === userId)?.display_name_ru ?? userId;

  function effectiveTicks(row: PlanEntryRow): string[] {
    return row.participantUserIds === null
      ? chosenUserIds
      : row.participantUserIds.filter((userId) => chosenUserIds.includes(userId));
  }

  function toggleTick(index: number, userId: string) {
    setEntries((rows) =>
      rows.map((row, rowIndex) => {
        if (rowIndex !== index) return row;
        const ticks = effectiveTicks(row);
        const next = ticks.includes(userId) ? ticks.filter((id) => id !== userId) : [...ticks, userId];
        const everyone = chosenUserIds.every((id) => next.includes(id));
        return { ...row, participantUserIds: everyone ? null : next };
      }),
    );
  }

  function distributeCards() {
    if (chosenUserIds.length === 0) return;
    setEntries((rows) =>
      rows.map((row, index) => ({ ...row, participantUserIds: [chosenUserIds[index % chosenUserIds.length]!] })),
    );
  }

  function tickEveryone() {
    setEntries((rows) => rows.map((row) => ({ ...row, participantUserIds: null })));
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

  function updateParticipantServiceId(index: number, assignedServiceId: string) {
    setParticipants((rows) => rows.map((row, rowIndex) => (rowIndex === index ? { ...row, assignedServiceId } : row)));
  }

  function addDdsParticipant() {
    setParticipants((rows) => [...rows, { userId: '', assignedRoleType: 'DDS', assignedServiceId: '' }]);
  }

  function removeParticipant(index: number) {
    setParticipants((rows) => rows.filter((_, rowIndex) => rowIndex !== index));
  }

  const everyEntryHasAParticipant = entries.every((row) => effectiveTicks(row).length > 0);
  const entriesValid =
    entries.length > 0 &&
    entries.every((row) => row.versionId !== '') &&
    entries[0]?.arrivalKind === 'AT_OFFSET' &&
    everyEntryHasAParticipant;
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
        // `undefined` (not `null`) when unbound — same "drop the key" reading `create-session-
        // form.tsx` uses, so an unbound/non-DDS row's JSON is unchanged from before this epic.
        ...(row.assignedRoleType === 'DDS' && row.assignedServiceId.trim() !== ''
          ? { assigned_service_id: row.assignedServiceId.trim() }
          : {}),
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
        // I3 E9a: an entry ticked for everyone sends no subset (every lesson participant).
        ...(row.participantUserIds === null ? {} : { participants: effectiveTicks(row) }),
      })),
      ...(groupId !== '' ? { group_id: groupId } : {}),
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

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="lesson-group">{t('lessonFormGroupLabel')}</Label>
          <select
            id="lesson-group"
            className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            value={groupId}
            onChange={(event) => handleGroupChange(event.target.value)}
            disabled={groupsQuery.isLoading}
          >
            <option value="">{t('lessonFormGroupNone')}</option>
            {(groupsQuery.data?.items ?? []).map((group) => (
              <option key={group.group_id} value={group.group_id}>
                {group.name_ru}
              </option>
            ))}
          </select>
          {selectedGroup ? <p className="text-xs text-muted-foreground">{t('lessonFormGroupHint')}</p> : null}
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="lesson-difficulty-filter">{t('lessonFormDifficultyFilterLabel')}</Label>
          <select
            id="lesson-difficulty-filter"
            className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            value={difficultyFilter ?? ''}
            onChange={(event) => setDifficultyFilter(event.target.value === '' ? null : Number(event.target.value))}
          >
            <option value="">{t('lessonFormDifficultyAll')}</option>
            {DIFFICULTIES.map((difficulty) => (
              <option key={difficulty} value={difficulty}>
                {`${t('difficultyLabel')} ${difficulty}`}
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
              difficultyFilter={difficultyFilter}
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
              <div key={index} className="flex flex-col gap-1.5 rounded-md border border-border p-2">
                <div className="flex items-end gap-2">
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
                  {row.assignedRoleType === 'DDS' && participants.filter((p) => p.assignedRoleType === 'DDS').length > 1 ? (
                    <Button type="button" variant="outline" size="sm" onClick={() => removeParticipant(index)}>
                      {t('instructorRemoveDdsParticipantButton')}
                    </Button>
                  ) : null}
                </div>
                {selectedGroup && sessionMode !== 'FULL_CYCLE_SINGLE_TRAINEE' && roleChainFor(entries).length > 0 ? (
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={`lesson-participant-${index}-role`}>{t('lessonFormParticipantRoleLabel')}</Label>
                    <select
                      id={`lesson-participant-${index}-role`}
                      className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                      value={row.assignedRoleType ?? ''}
                      onChange={(event) => updateParticipantRole(index, (event.target.value || null) as RoleType | null)}
                    >
                      {roleChainFor(entries).map((role) => (
                        <option key={role} value={role}>
                          {t(ROLE_TYPE_LABEL_KEY[role])}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : null}
                {row.assignedRoleType === 'DDS' ? (
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={`lesson-participant-${index}-service`}>{t('instructorParticipantServiceLabel')}</Label>
                    <select
                      id={`lesson-participant-${index}-service`}
                      className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                      value={row.assignedServiceId}
                      onChange={(event) => updateParticipantServiceId(index, event.target.value)}
                    >
                      <option value="">{t('instructorParticipantServiceUnboundOption')}</option>
                      {serviceCatalogOptions.map((entry) => (
                        <option key={entry.id} value={entry.id}>
                          {entry.name_ru}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : null}
              </div>
            ))}
            {sessionMode === 'MULTI_TRAINEE' && participants.some((row) => row.assignedRoleType === 'DDS') ? (
              <Button type="button" variant="outline" size="sm" onClick={addDdsParticipant}>
                {t('instructorAddDdsParticipantButton')}
              </Button>
            ) : null}
          </div>
        ) : null}

        {chosenUserIds.length > 1 ? (
          <fieldset className="flex flex-col gap-2 rounded-md border border-border p-2" data-slot="workstation-matrix">
            <legend className="px-1 text-sm font-medium">{t('lessonFormMatrixTitle')}</legend>
            <p className="text-xs text-muted-foreground">{t('lessonFormMatrixHint')}</p>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="p-1.5 font-medium">{t('lessonFormMatrixCardColumn')}</th>
                    {chosenUserIds.map((userId) => (
                      <th key={userId} className="p-1.5 text-center font-medium">
                        {displayNameOf(userId)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {entries.map((row, index) => (
                    <tr key={row.key} className="border-b border-border/60">
                      <td className="p-1.5">
                        {t('lessonFormEntryLabel')} {index + 1}
                        {row.version ? <span className="text-muted-foreground"> · {row.version.title}</span> : null}
                      </td>
                      {chosenUserIds.map((userId) => (
                        <td key={userId} className="p-1.5 text-center">
                          <input
                            type="checkbox"
                            className="size-4 accent-primary"
                            aria-label={`${t('lessonFormEntryLabel')} ${index + 1} — ${displayNameOf(userId)}`}
                            checked={effectiveTicks(row).includes(userId)}
                            onChange={() => toggleTick(index, userId)}
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" size="sm" onClick={distributeCards}>
                {t('lessonFormMatrixDistributeButton')}
              </Button>
              <Button type="button" variant="outline" size="sm" onClick={tickEveryone}>
                {t('lessonFormMatrixAllButton')}
              </Button>
            </div>
            {!everyEntryHasAParticipant ? (
              <p role="alert" className="text-xs text-destructive">
                {t('lessonFormMatrixEmptyEntry')}
              </p>
            ) : null}
          </fieldset>
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
