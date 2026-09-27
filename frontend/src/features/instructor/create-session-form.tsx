import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { Label } from '@/shared/ui/label';
import { Card, CardContent, CardFooter, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { ProblemError } from '@/shared/lib/api';
import { useServiceCatalogStore } from '@/entities/service-catalog';
import {
  createSession,
  getHealthReady,
  listScenarios,
  listScenarioVersions,
  listUsers,
  problemMessageRu,
  queryKeys,
  startSession,
  type CardSource,
  type DdsBrigadeCall,
  type DdsCardCheck,
  type DdsMode,
  type ProblemCode,
  type RoleType,
  type SessionDetail,
  type SessionMode,
  type SessionVariants,
} from '@/shared/api';
import { sessionStateLabelRu } from './instructor-labels';
import { isVariantSelectable, withoutPickerPhone, type VariantSwitch } from './variant-selection';
import { PassCriteriaFields } from './pass-criteria-fields';
import { DEFAULT_PASS_CRITERIA_DRAFT, passCriteriaField, passCriteriaProblem, type PassCriteriaDraft } from './pass-criteria';

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

// -- I3 E1: variant pickers (70 §70.2) --------------------------------------------------------
// One picker per `SessionVariants` switch, fed by `ScenarioVersionListItem.variants`
// (`ScenarioVariantsView`: the scenario's support after the server's implemented-values filter).
// Every value of the switch is listed so the instructor sees what exists; a value outside the
// view's `supported` list is disabled with a Russian note (either the scenario does not support it
// or the product does not implement it yet — the server answers 409 for both, and this form never
// sends one). The view's `default` is preselected.

const VARIANT_SWITCHES: readonly VariantSwitch[] = [
  'card_source',
  'dds_mode',
  'dds_card_check',
  'dds_brigade_call',
];

const VARIANT_SWITCH_LABEL_KEY: Record<VariantSwitch, keyof typeof ru> = {
  card_source: 'instructorVariantCardSourceLabel',
  dds_mode: 'instructorVariantDdsModeLabel',
  dds_card_check: 'instructorVariantDdsCardCheckLabel',
  dds_brigade_call: 'instructorVariantDdsBrigadeCallLabel',
};

// Exhaustive `generated union -> ru.ts key` tables: a new enum member fails `tsc` until labelled.
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

/**
 * The stages a session will run (70 §70.2.4): under `GENERATED_CARD` the `role_chain` suffix
 * starting at DDS, otherwise the whole chain. The server decides the real chain
 * (`SessionDetail.role_chain`); this only shapes the participant rows the request needs.
 */
function effectiveRoleChain(roleChain: readonly RoleType[], cardSource: CardSource | undefined): RoleType[] {
  if (cardSource !== 'GENERATED_CARD') return [...roleChain];
  const ddsIndex = roleChain.indexOf('DDS');
  return ddsIndex < 0 ? [] : roleChain.slice(ddsIndex);
}

interface ParticipantRow {
  userId: string;
  assignedRoleType: RoleType | null;
  /** I3 E5c (70 §70.4.5, D16): a ДДС participant's bound service; `''` = unbound (the scenario's
   * scripted responder plays that service, or — with nobody bound — one trainee plays every leg).
   * Always `''` for a non-DDS row; `handleCreate` sends `null` for those. */
  assignedServiceId: string;
}

/**
 * `assigned_role_type` per session mode (SPEC §13, D6). `FULL_CYCLE_SINGLE_TRAINEE` is the one
 * mode `ParticipantAssignment` documents `null` for ("one trainee plays every stage"); every
 * other mode assigns one participant per `role_chain` entry.
 *
 * HLD gap (see the E8-A report): neither `docs/hld/00-decisions.md` nor `openapi.yaml` states
 * `ASSESSMENT`'s assignment rule explicitly. This mirrors `SINGLE_ROLE`/`MULTI_TRAINEE` (one row
 * per `role_chain` entry), the reading closest to how `SessionCreateRequest.participants` is
 * shaped for every other mode.
 */
function buildParticipantRows(mode: SessionMode, roleChain: readonly RoleType[]): ParticipantRow[] {
  if (mode === 'FULL_CYCLE_SINGLE_TRAINEE') {
    return [{ userId: '', assignedRoleType: null, assignedServiceId: '' }];
  }
  return roleChain.map((roleType) => ({ userId: '', assignedRoleType: roleType, assignedServiceId: '' }));
}

function ProblemAlert({ error }: { error: unknown }) {
  if (!error) return null;
  const message =
    error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
  return (
    <p role="alert" className="text-sm text-destructive">
      {message}
    </p>
  );
}

/**
 * Minimal "create + start session" flow (E8-A scope): pick scenario -> version -> mode -> assign
 * trainee(s) -> create -> start. Nothing here computes simulation state; `start` is enabled only
 * from `SessionDetail.state` as returned by `createSession` (D12 design decision #3 — the full
 * `available_actions`-driven UI lands with the session snapshot pages in E8-B/E9/E10).
 */
export function CreateSessionForm() {
  const queryClient = useQueryClient();
  const [scenarioId, setScenarioId] = useState('');
  const [versionId, setVersionId] = useState('');
  const [sessionMode, setSessionMode] = useState<SessionMode>('SINGLE_ROLE');
  const [participants, setParticipants] = useState<ParticipantRow[]>([]);
  const [variants, setVariants] = useState<SessionVariants | null>(null);
  const [session, setSession] = useState<SessionDetail | null>(null);
  // I5 E38 (Q-E9b-3): the pass/fail criteria — sent only when they differ from the server's defaults.
  const [passDraft, setPassDraft] = useState<PassCriteriaDraft>(DEFAULT_PASS_CRITERIA_DRAFT);

  const scenariosQuery = useQuery({
    queryKey: queryKeys.scenarios.list(),
    queryFn: listScenarios,
  });

  const versionsQuery = useQuery({
    queryKey: queryKeys.scenarios.versions(scenarioId),
    queryFn: () => listScenarioVersions(scenarioId),
    enabled: scenarioId !== '',
  });

  const selectedVersion = useMemo(
    () => versionsQuery.data?.items.find((version) => version.id === versionId) ?? null,
    [versionsQuery.data, versionId],
  );

  // E8-B: trainee picker, backed by `listUsers` (openapi.yaml/schema.d.ts). Only `TRAINEE`
  // accounts are offered: an INSTRUCTOR/ADMIN is never a valid session participant.
  const traineesQuery = useQuery({
    queryKey: queryKeys.users.list('TRAINEE'),
    queryFn: () => listUsers({ role: 'TRAINEE' }),
  });

  // I3 E5c (70 §70.4.5, D16): the app-wide service catalog (`ServiceCatalogLoader` loads it once
  // at sign-in) — every ДДС participant row's service select is built from it.
  const serviceCatalogEntries = useServiceCatalogStore((state) => state.entries);
  const serviceCatalogOptions = useMemo(
    () => Object.values(serviceCatalogEntries).filter((entry) => entry.display && !entry.deprecated),
    [serviceCatalogEntries],
  );

  // R9 (SPEC §37): the Start button is disabled unless inference readiness is either satisfied
  // (`overall === 'READY'`) or not required at all. `HealthReadyResponse.require_inference_ready`
  // (openapi/schema.d.ts) is the direct signal for "not required" — no HLD gap here, contrary to
  // the brief's contingency reading, which only applies if that field were absent. The backend 503
  // `INFERENCE_NOT_READY` stays the real enforcement; this is only the UI affordance SPEC §37
  // separately demands.
  const healthQuery = useQuery({
    queryKey: queryKeys.health.ready(),
    queryFn: getHealthReady,
    refetchInterval: 5000,
  });
  const readinessSatisfied =
    healthQuery.data !== undefined &&
    (healthQuery.data.require_inference_ready === false || healthQuery.data.overall === 'READY');
  const notReadyComponents = (healthQuery.data?.components ?? [])
    .filter((component) => healthQuery.data!.required_components.includes(component.component))
    .filter((component) => component.status !== 'READY')
    .map((component) => component.component);

  // D1: the sibling `InstructorSessionsList` (instructor-page.tsx) reads the same
  // `queryKeys.sessions.list('ALL')` cache entry — invalidating it here is what makes that list
  // pick up a just-created/-started session without a page reload (D12: still "the server's
  // response", just fanned out to every query reading it, same idiom react-query already gives
  // every other mutation in this app).
  const createMutation = useMutation({
    mutationFn: createSession,
    onSuccess: (detail) => {
      setSession(detail);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions.list('ALL') });
    },
  });

  const startMutation = useMutation({
    mutationFn: (sessionId: string) => startSession(sessionId),
    onSuccess: (detail) => {
      setSession(detail);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions.list('ALL') });
    },
  });

  // Participant rows are reset directly by whichever handler changed the scenario version or
  // the session mode — the shape they imply (D6, SPEC §13) — rather than by an effect that
  // watches for the change after the fact (React: derive during the event, not after render).

  function handleScenarioChange(nextScenarioId: string) {
    setScenarioId(nextScenarioId);
    setVersionId('');
    setSession(null);
    setParticipants([]);
    setVariants(null);
  }

  function handleVersionChange(nextVersionId: string) {
    setVersionId(nextVersionId);
    setSession(null);
    const nextVersion = versionsQuery.data?.items.find((version) => version.id === nextVersionId) ?? null;
    const nextVariants = nextVersion ? withoutPickerPhone(nextVersion.variants.default) : null;
    setVariants(nextVariants);
    setParticipants(
      buildParticipantRows(
        sessionMode,
        effectiveRoleChain(nextVersion?.role_chain ?? [], nextVariants?.card_source),
      ),
    );
  }

  function handleModeChange(nextMode: SessionMode) {
    setSessionMode(nextMode);
    setSession(null);
    setParticipants(
      buildParticipantRows(nextMode, effectiveRoleChain(selectedVersion?.role_chain ?? [], variants?.card_source)),
    );
  }

  function handleVariantChange(variantSwitch: VariantSwitch, value: string) {
    if (!variants) return;
    const nextVariants = withoutPickerPhone({ ...variants, [variantSwitch]: value } as SessionVariants);
    setVariants(nextVariants);
    setSession(null);
    if (variantSwitch === 'card_source') {
      // The card source changes which stages run, so the participant rows follow it.
      setParticipants(
        buildParticipantRows(
          sessionMode,
          effectiveRoleChain(selectedVersion?.role_chain ?? [], nextVariants.card_source),
        ),
      );
    }
  }

  function updateParticipantUserId(index: number, userId: string) {
    setParticipants((rows) => rows.map((row, rowIndex) => (rowIndex === index ? { ...row, userId } : row)));
  }

  function updateParticipantServiceId(index: number, assignedServiceId: string) {
    setParticipants((rows) => rows.map((row, rowIndex) => (rowIndex === index ? { ...row, assignedServiceId } : row)));
  }

  // I3 E5c (70 §70.4.5): `MULTI_TRAINEE` may bind several ДДС participants to distinct services in
  // the one DDS stage — `buildParticipantRows` gives one row per `role_chain` entry, so a second
  // (or further) ДДС trainee is an explicit addition/removal the instructor makes here.
  function addDdsParticipant() {
    setParticipants((rows) => [...rows, { userId: '', assignedRoleType: 'DDS', assignedServiceId: '' }]);
    setSession(null);
  }

  function removeParticipant(index: number) {
    setParticipants((rows) => rows.filter((_, rowIndex) => rowIndex !== index));
    setSession(null);
  }

  function handleCreate() {
    if (!versionId || participants.length === 0 || participants.some((row) => row.userId.trim() === '')) {
      return;
    }
    if (passCriteriaProblem(passDraft) !== null) return;
    createMutation.mutate({
      scenario_version_id: versionId,
      session_mode: sessionMode,
      participants: participants.map((row) => ({
        user_id: row.userId.trim(),
        assigned_role_type: row.assignedRoleType,
        // `undefined` (not `null`) when unbound: `JSON.stringify` drops the key, keeping every
        // non-DDS/unbound request byte-identical to before this epic (a bound DDS row is the only
        // one that ever carries `assigned_service_id`).
        ...(row.assignedRoleType === 'DDS' && row.assignedServiceId.trim() !== ''
          ? { assigned_service_id: row.assignedServiceId.trim() }
          : {}),
      })),
      // The generated type requires this even though the backend defaults it to 1 (openapi's
      // `default: 1` does not make a property optional) — pass the same value explicitly.
      time_scale: 1,
      ...(variants ? { variants } : {}),
      ...passCriteriaField(passDraft),
    });
  }

  function handleStart() {
    if (!session) return;
    startMutation.mutate(session.id);
  }

  const canCreate =
    versionId !== '' &&
    participants.length > 0 &&
    participants.every((row) => row.userId.trim() !== '') &&
    passCriteriaProblem(passDraft) === null &&
    !createMutation.isPending;
  const canStart =
    session !== null && session.state === 'READY' && !startMutation.isPending && readinessSatisfied;

  return (
    <Card className="max-w-xl">
      <CardHeader>
        <h1 className="font-heading text-base leading-snug font-medium">
          {t('instructorCreateSessionTitle')}
        </h1>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="instructor-scenario">{t('instructorScenarioLabel')}</Label>
          <select
            id="instructor-scenario"
            className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            value={scenarioId}
            onChange={(event) => handleScenarioChange(event.target.value)}
            disabled={scenariosQuery.isLoading}
          >
            <option value="">{t('instructorSelectScenarioPlaceholder')}</option>
            {(scenariosQuery.data?.items ?? []).map((scenario) => (
              <option key={scenario.scenario_id} value={scenario.scenario_id}>
                {/* I3 E9a: every scenario picker shows its «Сложность». */}
                {scenario.latest_difficulty
                  ? `${t('difficultyLabel')} ${scenario.latest_difficulty} · ${scenario.title_ru}`
                  : scenario.title_ru}
              </option>
            ))}
          </select>
          {scenariosQuery.isLoading ? (
            <p className="text-xs text-muted-foreground">{t('instructorLoadingScenarios')}</p>
          ) : null}
          {scenariosQuery.data && scenariosQuery.data.items.length === 0 ? (
            <p className="text-xs text-muted-foreground">{t('instructorNoScenarios')}</p>
          ) : null}
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="instructor-version">{t('instructorVersionLabel')}</Label>
          <select
            id="instructor-version"
            className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            value={versionId}
            onChange={(event) => handleVersionChange(event.target.value)}
            disabled={scenarioId === '' || versionsQuery.isLoading}
          >
            <option value="">{t('instructorSelectVersionPlaceholder')}</option>
            {(versionsQuery.data?.items ?? []).map((version) => (
              <option key={version.id} value={version.id}>
                {`${t('difficultyLabel')} ${version.difficulty} · ${version.title} (v${version.version})`}
              </option>
            ))}
          </select>
          {versionsQuery.isLoading ? (
            <p className="text-xs text-muted-foreground">{t('instructorLoadingVersions')}</p>
          ) : null}
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="instructor-mode">{t('instructorModeLabel')}</Label>
          <select
            id="instructor-mode"
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

        {selectedVersion && variants ? (
          <fieldset className="flex flex-col gap-2" data-slot="variant-pickers">
            <legend className="text-sm font-medium">{t('instructorVariantsLabel')}</legend>
            {VARIANT_SWITCHES.map((variantSwitch) => (
              <div key={variantSwitch} className="flex flex-col gap-1.5">
                <Label htmlFor={`instructor-variant-${variantSwitch}`}>
                  {t(VARIANT_SWITCH_LABEL_KEY[variantSwitch])}
                </Label>
                <select
                  id={`instructor-variant-${variantSwitch}`}
                  className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                  value={variants[variantSwitch]}
                  onChange={(event) => handleVariantChange(variantSwitch, event.target.value)}
                >
                  {variantValues(variantSwitch).map((value) => {
                    const supported = isVariantSelectable(selectedVersion.variants, variants, variantSwitch, value);
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
            {VARIANT_SWITCHES.some((variantSwitch) =>
              variantValues(variantSwitch).some((value) => !isVariantSelectable(selectedVersion.variants, variants, variantSwitch, value)),
            ) ? (
              <p className="text-xs text-muted-foreground" data-slot="variant-unavailable-note">
                {t('instructorVariantUnavailableNote')}
              </p>
            ) : null}
          </fieldset>
        ) : null}

        {participants.length > 0 ? (
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">{t('instructorParticipantsLabel')}</span>
            {participants.map((row, index) => (
              <div key={index} className="flex flex-col gap-1.5 rounded-md border border-border p-2">
                <div className="flex items-end gap-2">
                  <div className="flex flex-1 flex-col gap-1.5">
                    <Label htmlFor={`instructor-participant-${index}`}>
                      {row.assignedRoleType
                        ? `${t('instructorParticipantUserIdLabel')} — ${t(ROLE_TYPE_LABEL_KEY[row.assignedRoleType])}`
                        : t('instructorParticipantUserIdLabel')}
                    </Label>
                    <select
                      id={`instructor-participant-${index}`}
                      className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                      value={row.userId}
                      onChange={(event) => updateParticipantUserId(index, event.target.value)}
                      disabled={traineesQuery.isLoading}
                    >
                      <option value="">{t('instructorSelectTraineePlaceholder')}</option>
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
                {row.assignedRoleType === 'DDS' ? (
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={`instructor-participant-${index}-service`}>{t('instructorParticipantServiceLabel')}</Label>
                    <select
                      id={`instructor-participant-${index}-service`}
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
            {traineesQuery.isLoading ? (
              <p className="text-xs text-muted-foreground">{t('instructorLoadingUsers')}</p>
            ) : null}
            {traineesQuery.data && traineesQuery.data.items.length === 0 ? (
              <p className="text-xs text-muted-foreground">{t('instructorNoUsers')}</p>
            ) : null}
            {sessionMode === 'MULTI_TRAINEE' && participants.some((row) => row.assignedRoleType === 'DDS') ? (
              <Button type="button" variant="outline" size="sm" onClick={addDdsParticipant}>
                {t('instructorAddDdsParticipantButton')}
              </Button>
            ) : null}
          </div>
        ) : null}

        <PassCriteriaFields
          idPrefix="instructor"
          draft={passDraft}
          onChange={(draft) => {
            setPassDraft(draft);
            setSession(null);
          }}
        />

        <ProblemAlert error={createMutation.error} />
        <ProblemAlert error={startMutation.error} />

        {session ? (
          <p className="text-xs text-muted-foreground" data-slot="session-state">
            {t('instructorSessionStateLabel')}: {sessionStateLabelRu(session.state)}
          </p>
        ) : null}
        {session && session.state === 'READY' && !readinessSatisfied ? (
          <p role="alert" className="text-sm text-destructive" data-slot="start-not-ready-reason">
            {t('instructorStartNotReadyReason')}
            {notReadyComponents.length > 0 ? `: ${notReadyComponents.join(', ')}` : null}
          </p>
        ) : null}
      </CardContent>
      <CardFooter className="flex gap-2">
        <Button type="button" onClick={handleCreate} disabled={!canCreate}>
          {createMutation.isPending ? t('instructorCreating') : t('instructorCreateButton')}
        </Button>
        <Button type="button" variant="outline" onClick={handleStart} disabled={!canStart}>
          {startMutation.isPending ? t('instructorStarting') : t('instructorStartButton')}
        </Button>
      </CardFooter>
    </Card>
  );
}
