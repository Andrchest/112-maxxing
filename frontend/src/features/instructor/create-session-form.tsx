import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { Label } from '@/shared/ui/label';
import { Card, CardContent, CardFooter, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { ProblemError } from '@/shared/lib/api';
import {
  createSession,
  getHealthReady,
  listScenarios,
  listScenarioVersions,
  listUsers,
  problemMessageRu,
  queryKeys,
  startSession,
  type ProblemCode,
  type RoleType,
  type SessionDetail,
  type SessionMode,
} from '@/shared/api';
import { sessionStateLabelRu } from './instructor-labels';

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

interface ParticipantRow {
  userId: string;
  assignedRoleType: RoleType | null;
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
    return [{ userId: '', assignedRoleType: null }];
  }
  return roleChain.map((roleType) => ({ userId: '', assignedRoleType: roleType }));
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
  const [session, setSession] = useState<SessionDetail | null>(null);

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
  }

  function handleVersionChange(nextVersionId: string) {
    setVersionId(nextVersionId);
    setSession(null);
    const nextVersion = versionsQuery.data?.items.find((version) => version.id === nextVersionId) ?? null;
    setParticipants(buildParticipantRows(sessionMode, nextVersion?.role_chain ?? []));
  }

  function handleModeChange(nextMode: SessionMode) {
    setSessionMode(nextMode);
    setSession(null);
    setParticipants(buildParticipantRows(nextMode, selectedVersion?.role_chain ?? []));
  }

  function updateParticipantUserId(index: number, userId: string) {
    setParticipants((rows) => rows.map((row, rowIndex) => (rowIndex === index ? { ...row, userId } : row)));
  }

  function handleCreate() {
    if (!versionId || participants.length === 0 || participants.some((row) => row.userId.trim() === '')) {
      return;
    }
    createMutation.mutate({
      scenario_version_id: versionId,
      session_mode: sessionMode,
      participants: participants.map((row) => ({
        user_id: row.userId.trim(),
        assigned_role_type: row.assignedRoleType,
      })),
      // The generated type requires this even though the backend defaults it to 1 (openapi's
      // `default: 1` does not make a property optional) — pass the same value explicitly.
      time_scale: 1,
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
                {scenario.title_ru}
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
                {version.title} (v{version.version})
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

        {participants.length > 0 ? (
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">{t('instructorParticipantsLabel')}</span>
            {participants.map((row, index) => (
              <div key={index} className="flex items-end gap-2">
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
              </div>
            ))}
            {traineesQuery.isLoading ? (
              <p className="text-xs text-muted-foreground">{t('instructorLoadingUsers')}</p>
            ) : null}
            {traineesQuery.data && traineesQuery.data.items.length === 0 ? (
              <p className="text-xs text-muted-foreground">{t('instructorNoUsers')}</p>
            ) : null}
          </div>
        ) : null}

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
