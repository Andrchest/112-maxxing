// Route: /instructor/lessons/:lessonId (I3 E4b, 70 §70.3). The plan, the per-card `card_status`
// (read verbatim from `LessonSessionView.card_status` — never derived here) and the lifecycle
// controls (start/abort/release); once the lesson is terminal, the N card reports plus the
// weighted total (`getLessonReport`, openapi.yaml — "no new evaluator").
//
// I3 E9a (70 §70.3.7): each plan entry shows its scenario's «Сложность», its weight and whose
// workstation it is; the lesson's group is named; `WeightProposalsCard` asks for AI weight
// proposals and accepts the chosen ones (the only way a proposal becomes a weight).
//
// I4 E31 (71 §71.8, D34): a card aborted by an early end is listed unscored, with its time at work
// and its actions (`LessonReport.cards[].unscored`).
//
// I4 E33 (71 §71.10): the scored cards are a table with each card's failed rules, critical errors
// and times against the system's norms, and «Скачать CSV» downloads the same report as a file
// (`lesson-report-table.tsx`).
//
// I5 E39 (Q-E9b-4 variant а): every instructor sees the lesson, but only its creator
// (`LessonDetail.created_by_user_id`) or an ADMIN changes it — for anyone else the start, abort,
// release and weight controls are disabled with «Изменять может только преподаватель, создавший
// занятие». Comments stay open to every instructor.
import { useState } from 'react';
import { useParams, Link } from 'react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AppShell } from '@/shared/ui/app-shell';
import { Badge } from '@/shared/ui/badge';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { canChangeOwned, useAuthStore } from '@/entities/session';
import { formatCallDurationMs } from '@/entities/call';
import {
  getLesson,
  getLessonReport,
  getScenarioVersionSummary,
  listTraineeGroups,
  listUsers,
  problemMessageRu,
  queryKeys,
  releaseLessonReport,
  startLesson,
  type LessonDetail,
  type ProblemCode,
  type SessionState,
  type UnscoredCardView,
  type UserRole,
} from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { arrivalKindLabelRu, cardStatusLabelRu, isRedFlagCardStatus, lessonStateLabelRu } from './lesson-labels';
import { AbortLessonButton } from './abort-lesson-button';
import { WeightProposalsCard } from './weight-proposals-card';
import { DownloadLessonReportCsvButton, LessonReportTable } from './lesson-report-table';

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

const SESSION_STATE_LABEL_KEY: Record<SessionState, keyof typeof ru> = {
  CREATED: 'sessionStateCreated',
  READY: 'sessionStateReady',
  ACTIVE: 'sessionStateActive',
  ROLE_TRANSITION: 'sessionStateRoleTransition',
  COMPLETED: 'sessionStateCompleted',
  ABORTED: 'sessionStateAborted',
};

/** The scenario version's Russian title (`ScenarioVersionTraineeSummary.title`, D3: the
 * trainee-safe projection) — a plan entry or card row names its scenario, not just a bare
 * position (manager follow-up on E4b-shots/04). `'—'` while loading/on error, same fallback
 * `incident-list-table.tsx` already uses for a value not yet available. */
function ScenarioTitle({ scenarioVersionId }: { scenarioVersionId: string }) {
  const query = useQuery({
    queryKey: queryKeys.scenarios.versionSummary(scenarioVersionId),
    queryFn: () => getScenarioVersionSummary(scenarioVersionId),
    enabled: scenarioVersionId !== '',
  });
  return <>{query.data?.title ?? '—'}</>;
}

/** «Сложность N» of the scenario version (the same trainee-safe summary `ScenarioTitle` reads). */
function ScenarioDifficulty({ scenarioVersionId }: { scenarioVersionId: string }) {
  const query = useQuery({
    queryKey: queryKeys.scenarios.versionSummary(scenarioVersionId),
    queryFn: () => getScenarioVersionSummary(scenarioVersionId),
    enabled: scenarioVersionId !== '',
  });
  if (!query.data) return null;
  return (
    <span data-slot="plan-entry-difficulty">
      {t('difficultyLabel')} {query.data.difficulty}
    </span>
  );
}

/** I4 E31 (71 §71.8, D34; ТЗ ¶342–343): a card of a lesson ended early — no points (Q-E9b-6), but
 * its time at work and its actions (`UnscoredCardView.timeline`, the same projection a card report
 * shows), each with its session offset. Outside the weighted total, as the server computes it. */
function UnscoredReportCard({ position, unscored }: { position: number; unscored: UnscoredCardView | null }) {
  const elapsedMs = unscored?.times.elapsed_ms ?? null;
  const timeline = unscored?.timeline ?? [];
  return (
    <li className="flex flex-col gap-1 rounded-md border border-border p-2 text-sm" data-slot="report-card-unscored">
      <div className="flex items-center justify-between gap-2">
        <span>
          {t('lessonDetailColumnPosition')} {position}
        </span>
        <span className="flex items-center gap-2">
          <Badge variant="outline">{t('lessonReportCardUnscored')}</Badge>
          <span className="text-xs text-muted-foreground" data-slot="report-card-elapsed">
            {elapsedMs === null
              ? t('lessonReportCardNotStarted')
              : `${t('lessonReportCardElapsedLabel')} ${formatCallDurationMs(elapsedMs)}`}
          </span>
        </span>
      </div>
      {timeline.length > 0 ? (
        <details>
          <summary className="cursor-pointer text-xs text-muted-foreground">
            {t('lessonReportCardActionsLabel')} ({timeline.length})
          </summary>
          <ol className="mt-1 flex flex-col gap-0.5 text-xs" data-slot="report-card-actions">
            {timeline.map((entry) => (
              <li key={entry.seq_no}>
                <span className="tabular-nums text-muted-foreground">{formatCallDurationMs(entry.monotonic_offset_ms)}</span>{' '}
                {entry.summary_ru}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </li>
  );
}

function LessonReportSection({ lessonId }: { lessonId: string }) {
  const reportQuery = useQuery({
    queryKey: queryKeys.lessons.report(lessonId),
    queryFn: () => getLessonReport(lessonId),
  });

  if (reportQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">{t('lessonDetailReportLoading')}</p>;
  }
  if (reportQuery.isError) {
    const message =
      reportQuery.error instanceof ProblemError ? problemMessageRu(reportQuery.error.code as ProblemCode) : t('problemUnknown');
    return (
      <p role="alert" className="text-sm text-destructive">
        {message}
      </p>
    );
  }
  if (!reportQuery.data) return null;

  const unscoredCards = reportQuery.data.cards.filter((card) => card.score === null);
  return (
    <div className="flex flex-col gap-2" data-slot="lesson-report">
      <DownloadLessonReportCsvButton lessonId={lessonId} />
      <LessonReportTable cards={reportQuery.data.cards} />
      {unscoredCards.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {unscoredCards.map((card) => (
            <UnscoredReportCard key={card.session_id} position={card.position} unscored={card.unscored} />
          ))}
        </ul>
      ) : null}
      <p className="text-sm font-medium" data-slot="weighted-total">
        {t('lessonDetailWeightedTotalLabel')}: {reportQuery.data.weighted_total} / {reportQuery.data.weighted_max}
      </p>
    </div>
  );
}

export function LessonDetailPage() {
  const { lessonId } = useParams<{ lessonId: string }>();
  const user = useAuthStore((state) => state.user);
  const roleLabel = user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined;
  const queryClient = useQueryClient();
  const [lessonOverride, setLessonOverride] = useState<LessonDetail | null>(null);
  const [startError, setStartError] = useState<unknown>(null);
  const [starting, setStarting] = useState(false);

  const lessonQuery = useQuery({
    queryKey: queryKeys.lessons.detail(lessonId ?? ''),
    queryFn: () => getLesson(lessonId ?? ''),
    enabled: lessonId !== undefined,
  });

  const lesson = lessonOverride ?? lessonQuery.data ?? null;

  const groupsQuery = useQuery({
    queryKey: queryKeys.traineeGroups.list(),
    queryFn: listTraineeGroups,
    enabled: Boolean(lesson?.group_id),
  });
  const groupName = (groupsQuery.data?.items ?? []).find((group) => group.group_id === lesson?.group_id)?.name_ru;
  const traineesQuery = useQuery({
    queryKey: queryKeys.users.list('TRAINEE'),
    queryFn: () => listUsers({ role: 'TRAINEE' }),
  });
  const nameOf = (userId: string) =>
    (traineesQuery.data?.items ?? []).find((account) => account.id === userId)?.display_name_ru ?? userId;

  function applyUpdate(next: LessonDetail) {
    setLessonOverride(next);
    void queryClient.invalidateQueries({ queryKey: queryKeys.lessons.list('ALL') });
  }

  async function handleStart() {
    if (!lessonId) return;
    setStartError(null);
    setStarting(true);
    try {
      applyUpdate(await startLesson(lessonId));
    } catch (error) {
      setStartError(error);
    } finally {
      setStarting(false);
    }
  }

  async function handleRelease() {
    if (!lessonId) return;
    applyUpdate(await releaseLessonReport(lessonId));
  }

  if (!lessonId) return null;

  const canChange = canChangeOwned(user, lesson?.created_by_user_id);

  const scenarioVersionIdByPosition = new Map(
    (lesson?.scenario_plan ?? []).map((entry) => [entry.position, entry.scenario_version_id]),
  );

  return (
    <AppShell
      title={t('lessonsPageTitle')}
      role={roleLabel}
      userLabel={user?.display_name_ru}
      connectionIndicatorHidden
    >
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-lg font-semibold tracking-tight">{lesson?.title_ru ?? t('lessonDetailLoading')}</h1>
        <Link to="/instructor/lessons" className="text-sm text-primary underline-offset-2 hover:underline">
          {t('lessonDetailBackButton')}
        </Link>
      </div>

      {lessonQuery.isLoading && !lesson ? <p className="mt-2 text-sm text-muted-foreground">{t('lessonDetailLoading')}</p> : null}
      {lessonQuery.isError ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {lessonQuery.error instanceof ProblemError ? problemMessageRu(lessonQuery.error.code as ProblemCode) : t('problemUnknown')}
        </p>
      ) : null}

      {lesson ? (
        <div className="mt-4 flex flex-col gap-4">
          <Card className="max-w-2xl">
            <CardHeader className="flex flex-row items-center justify-between gap-2">
              <h2 className="font-heading text-base leading-snug font-medium">{t('lessonDetailPlanTitle')}</h2>
              <span className="text-xs text-muted-foreground">{lessonStateLabelRu(lesson.state)}</span>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {lesson.group_id ? (
                <p className="text-sm" data-slot="lesson-group">
                  {t('lessonDetailGroupLabel')}: {groupName ?? '—'}
                </p>
              ) : null}
              <ul className="flex flex-col gap-1">
                {lesson.scenario_plan.map((entry) => (
                  <li key={entry.position} className="rounded-md border border-border p-2 text-sm">
                    <span className="font-mono">
                      {t('lessonDetailColumnPosition')} {entry.position}
                    </span>{' '}
                    ·{' '}
                    <span data-slot="plan-entry-scenario">
                      <ScenarioTitle scenarioVersionId={entry.scenario_version_id} />
                    </span>
                    {' · '}
                    <span data-slot="plan-entry-arrival">
                      {arrivalKindLabelRu(entry.arrival.kind)}
                      {entry.arrival.kind === 'AT_OFFSET'
                        ? ` (${formatCallDurationMs(entry.arrival.offset_ms ?? 0)})`
                        : null}
                    </span>
                    {' · '}
                    <ScenarioDifficulty scenarioVersionId={entry.scenario_version_id} />
                    {' · '}
                    <span data-slot="plan-entry-weight">
                      {t('lessonDetailWeightLabel')} {entry.weight ?? 1}
                    </span>
                    <span className="block text-xs text-muted-foreground" data-slot="plan-entry-participants">
                      {t('lessonDetailParticipantsLabel')}:{' '}
                      {entry.participants ? entry.participants.map(nameOf).join(', ') : t('lessonDetailEveryone')}
                    </span>
                  </li>
                ))}
              </ul>

              <div className="flex flex-wrap items-center gap-2" data-slot="lesson-actions">
                {lesson.state === 'CREATED' ? (
                  <Button type="button" size="sm" onClick={() => void handleStart()} disabled={starting || !canChange}>
                    {starting ? t('lessonDetailStarting') : t('lessonDetailStartButton')}
                  </Button>
                ) : null}
                {lesson.state === 'CREATED' || lesson.state === 'ACTIVE' ? (
                  <AbortLessonButton lessonId={lessonId} onAborted={applyUpdate} disabled={!canChange} />
                ) : null}
                {(lesson.state === 'COMPLETED' || lesson.state === 'ABORTED') && !lesson.report_released_at ? (
                  <Button type="button" variant="outline" size="sm" onClick={() => void handleRelease()} disabled={!canChange}>
                    {t('lessonDetailReleaseButton')}
                  </Button>
                ) : null}
              </div>
              {!canChange ? (
                <p className="text-xs text-muted-foreground" data-slot="ownership-hint">
                  {t('ownershipHintLesson')}
                </p>
              ) : null}
              {startError ? (
                <p role="alert" className="text-sm text-destructive">
                  {startError instanceof ProblemError ? problemMessageRu(startError.code as ProblemCode) : t('problemUnknown')}
                </p>
              ) : null}
            </CardContent>
          </Card>

          <Card className="max-w-2xl">
            <CardHeader>
              <h2 className="font-heading text-base leading-snug font-medium">{t('lessonDetailCardsTitle')}</h2>
            </CardHeader>
            <CardContent>
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="p-2 font-medium">{t('lessonDetailColumnPosition')}</th>
                    <th className="p-2 font-medium">{t('lessonDetailColumnNumber')}</th>
                    <th className="p-2 font-medium">{t('lessonDetailColumnScenario')}</th>
                    <th className="p-2 font-medium">{t('lessonDetailColumnState')}</th>
                    <th className="p-2 font-medium">{t('lessonDetailColumnStatus')}</th>
                    <th className="p-2" />
                  </tr>
                </thead>
                <tbody>
                  {lesson.sessions.map((session) => (
                    <tr key={session.session_id} className="border-b border-border/60" data-slot="lesson-session-row">
                      <td className="p-2">{session.position}</td>
                      <td className="p-2 font-mono">{session.display_number}</td>
                      <td className="p-2">
                        <ScenarioTitle scenarioVersionId={scenarioVersionIdByPosition.get(session.position) ?? ''} />
                      </td>
                      <td className="p-2">{t(SESSION_STATE_LABEL_KEY[session.state])}</td>
                      <td className="p-2">
                        <Badge variant={isRedFlagCardStatus(session.card_status) ? 'destructive' : 'outline'} data-slot="card-status-badge">
                          {cardStatusLabelRu(session.card_status)}
                        </Badge>
                      </td>
                      <td className="p-2 text-right">
                        <Link
                          className="text-primary underline-offset-2 hover:underline"
                          to={`/instructor/sessions/${session.session_id}`}
                        >
                          {t('lessonDetailOverviewButton')}
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>

          <WeightProposalsCard
            lessonId={lessonId}
            canChange={canChange}
            onWeightsChanged={() => setLessonOverride(null)}
            renderCardLabel={(position, scenarioVersionId) => (
              <span className="flex flex-col">
                <span>
                  {t('lessonDetailColumnPosition')} {position} · <ScenarioTitle scenarioVersionId={scenarioVersionId} />
                </span>
                <span className="text-xs text-muted-foreground">
                  <ScenarioDifficulty scenarioVersionId={scenarioVersionId} />
                </span>
              </span>
            )}
          />

          {lesson.state === 'COMPLETED' || lesson.state === 'ABORTED' ? (
            <Card className="max-w-2xl">
              <CardHeader>
                <h2 className="font-heading text-base leading-snug font-medium">{t('lessonDetailReportTitle')}</h2>
              </CardHeader>
              <CardContent>
                <LessonReportSection lessonId={lessonId} />
              </CardContent>
            </Card>
          ) : (
            <p className="text-sm text-muted-foreground">{t('lessonDetailReportNotReady')}</p>
          )}
        </div>
      ) : null}
    </AppShell>
  );
}
