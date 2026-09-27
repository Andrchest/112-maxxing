// Route: /sessions (D12 design decision #4) — the destination `homeRouteForRole` in
// `entities/session/auth-store.ts` sends a signed-in trainee to. "My sessions" — every session `listSessions({scope:'MINE'})`
// returns for the signed-in trainee, with a link into that session's console. Lists exactly what
// the backend returned: no client-side filtering, sorting or derived status.
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { AppShell } from '@/shared/ui/app-shell';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import {
  getLesson,
  listScenarios,
  listSessions,
  problemMessageRu,
  queryKeys,
  type ProblemCode,
  type RoleType,
  type SessionMode,
  type SessionState,
  type UserRole,
} from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';

const SESSION_MODE_LABEL_KEY: Record<SessionMode, keyof typeof ru> = {
  SINGLE_ROLE: 'instructorSessionModeSingleRole',
  FULL_CYCLE_SINGLE_TRAINEE: 'instructorSessionModeFullCycle',
  MULTI_TRAINEE: 'instructorSessionModeMultiTrainee',
  ASSESSMENT: 'instructorSessionModeAssessment',
};

const SESSION_STATE_LABEL_KEY: Record<SessionState, keyof typeof ru> = {
  CREATED: 'sessionStateCreated',
  READY: 'sessionStateReady',
  ACTIVE: 'sessionStateActive',
  ROLE_TRANSITION: 'sessionStateRoleTransition',
  COMPLETED: 'sessionStateCompleted',
  ABORTED: 'sessionStateAborted',
};

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

/** `SessionListItem.my_role_type` is `session_participants.assigned_role_type` verbatim — under
 * `FULL_CYCLE_SINGLE_TRAINEE` (`ALL_STAGES_ONE_PARTICIPANT`, D6) it is deliberately `null` even
 * for the one trainee playing every stage (SPEC §10.10: `assigned_role_type` is per-stage
 * assignment; a single-trainee-plays-all session assigns no fixed one). Route that case through
 * `/sessions/:id/open`, which resolves the *active* stage's role from the snapshot server-side
 * (E10) — never a client-side guess. A `null` role outside that mode means a true observer. */
function consoleHrefFor(sessionId: string, myRoleType: RoleType | null, sessionMode: SessionMode): string | null {
  if (myRoleType === 'OPERATOR_112') return `/operator/${sessionId}`;
  if (myRoleType === 'DDS') return `/dds/${sessionId}`;
  if (myRoleType === null && sessionMode === 'FULL_CYCLE_SINGLE_TRAINEE') return `/sessions/${sessionId}/open`;
  return null;
}

/** I6 NAV2 (manager decision, final): the lesson's name and this card's own start time, so two
 * runs of the same scenario (e.g. two cards of the same lesson) can be told apart — `getLesson`
 * is the same read `GetLesson` grants a TRAINEE for a lesson they participate in. `started_at` is
 * this session's own (not the lesson's), since a lesson's cards can start at different offsets. */
function LessonRunLabel({ lessonId, startedAt }: { lessonId: string; startedAt: string | null }) {
  const lessonQuery = useQuery({
    queryKey: queryKeys.lessons.detail(lessonId),
    queryFn: () => getLesson(lessonId),
  });
  if (!lessonQuery.data) return null;
  return (
    <p className="text-xs text-muted-foreground" data-slot="session-lesson-run">
      {t('sessionsLessonLabel')}: {lessonQuery.data.title_ru}
      {startedAt ? ` · ${t('sessionsStartedAtLabel')}: ${new Date(startedAt).toLocaleString('ru-RU')}` : null}
    </p>
  );
}

export function SessionsLandingPage() {
  const user = useAuthStore((state) => state.user);
  const userLabel = user?.display_name_ru;
  const roleLabel = user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined;
  const sessionsQuery = useQuery({
    queryKey: queryKeys.sessions.list('MINE'),
    queryFn: () => listSessions({ scope: 'MINE' }),
  });
  // D3: the same "look the Russian title up by scenario slug" read `instructor-sessions-list.tsx`
  // uses, so a trainee's own row reads as a title too, not a raw scenario slug + version.
  const scenariosQuery = useQuery({
    queryKey: queryKeys.scenarios.list(),
    queryFn: listScenarios,
  });
  const scenarioTitleBySlug = new Map((scenariosQuery.data?.items ?? []).map((scenario) => [scenario.slug, scenario.title_ru]));

  return (
    <AppShell title={t('sessionsTitle')} role={roleLabel} userLabel={userLabel}>
      <div className="flex items-start justify-between gap-4">
        <h1 className="text-lg font-semibold tracking-tight">{t('sessionsTitle')}</h1>
        {/* I3 E4b (manager follow-up): a trainee's role is per-session, not per-account (D6), so
            both the 112 «реестр» and the ДДС «Список происшествий» are offered from the one
            trainee home regardless of which role their next lesson assigns them. */}
        <nav className="flex items-center gap-2">
          <Button asChild variant="ghost" size="sm">
            <Link to="/operator/register">{t('navRegisterLink')}</Link>
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link to="/dds/incidents">{t('navIncidentListLink')}</Link>
          </Button>
        </nav>
      </div>
      {sessionsQuery.isLoading ? <p className="mt-2 text-sm text-muted-foreground">{t('sessionsLoading')}</p> : null}
      {sessionsQuery.isError ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {sessionsQuery.error instanceof ProblemError
            ? problemMessageRu(sessionsQuery.error.code as ProblemCode)
            : t('problemUnknown')}
        </p>
      ) : null}
      {sessionsQuery.data && sessionsQuery.data.items.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">{t('sessionsEmpty')}</p>
      ) : null}
      <ul className="mt-3 flex flex-col gap-2">
        {(sessionsQuery.data?.items ?? []).map((session) => {
          const href = consoleHrefFor(session.id, session.my_role_type, session.session_mode);
          return (
            <li key={session.id}>
              <Card>
                <CardHeader className="flex flex-row items-center justify-between gap-2">
                  <div>
                    <p className="font-medium">
                      {scenarioTitleBySlug.get(session.scenario_slug) ?? session.scenario_slug} (v{session.scenario_version})
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {t(SESSION_MODE_LABEL_KEY[session.session_mode])} · {t('sessionsStateLabel')}: {t(SESSION_STATE_LABEL_KEY[session.state])}
                    </p>
                    {session.lesson_id ? (
                      <LessonRunLabel lessonId={session.lesson_id} startedAt={session.started_at ?? null} />
                    ) : null}
                  </div>
                  {href ? (
                    <Button asChild size="sm">
                      <Link to={href}>{t('sessionsOpenButton')}</Link>
                    </Button>
                  ) : null}
                </CardHeader>
                {!href ? (
                  <CardContent>
                    <p className="text-xs text-muted-foreground">{t('sessionsNoConsoleYet')}</p>
                  </CardContent>
                ) : null}
              </Card>
            </li>
          );
        })}
      </ul>
    </AppShell>
  );
}
