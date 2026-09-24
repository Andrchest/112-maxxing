// Route: /instructor/lessons/:lessonId (I3 E4b, 70 §70.3). The plan, the per-card `card_status`
// (read verbatim from `LessonSessionView.card_status` — never derived here) and the lifecycle
// controls (start/abort/release); once the lesson is terminal, the N card reports plus the
// weighted total (`getLessonReport`, openapi.yaml — "no new evaluator").
import { useState } from 'react';
import { useParams, Link } from 'react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AppShell } from '@/shared/ui/app-shell';
import { Badge } from '@/shared/ui/badge';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import { formatCallDurationMs } from '@/entities/call';
import {
  getLesson,
  getLessonReport,
  getScenarioVersionSummary,
  problemMessageRu,
  queryKeys,
  releaseLessonReport,
  startLesson,
  type LessonDetail,
  type ProblemCode,
  type SessionState,
  type UserRole,
} from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { arrivalKindLabelRu, cardStatusLabelRu, isRedFlagCardStatus, lessonStateLabelRu } from './lesson-labels';
import { AbortLessonButton } from './abort-lesson-button';

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

  return (
    <div className="flex flex-col gap-2" data-slot="lesson-report">
      <ul className="flex flex-col gap-1">
        {reportQuery.data.cards.map((card) => (
          <li key={card.session_id} className="flex items-center justify-between gap-2 rounded-md border border-border p-2 text-sm">
            <span>
              {t('lessonDetailColumnPosition')} {card.position}
            </span>
            <span>
              {card.score.total_points} / {card.score.total_max_points}
            </span>
          </li>
        ))}
      </ul>
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
                  </li>
                ))}
              </ul>

              <div className="flex flex-wrap items-center gap-2" data-slot="lesson-actions">
                {lesson.state === 'CREATED' ? (
                  <Button type="button" size="sm" onClick={() => void handleStart()} disabled={starting}>
                    {starting ? t('lessonDetailStarting') : t('lessonDetailStartButton')}
                  </Button>
                ) : null}
                {lesson.state === 'CREATED' || lesson.state === 'ACTIVE' ? (
                  <AbortLessonButton lessonId={lessonId} onAborted={applyUpdate} />
                ) : null}
                {(lesson.state === 'COMPLETED' || lesson.state === 'ABORTED') && !lesson.report_released_at ? (
                  <Button type="button" variant="outline" size="sm" onClick={() => void handleRelease()}>
                    {t('lessonDetailReleaseButton')}
                  </Button>
                ) : null}
              </div>
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
