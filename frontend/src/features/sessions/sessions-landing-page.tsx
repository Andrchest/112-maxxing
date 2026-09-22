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
import { listSessions, problemMessageRu, queryKeys, type ProblemCode, type RoleType, type SessionMode } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';

const SESSION_MODE_LABEL_KEY: Record<SessionMode, keyof typeof ru> = {
  SINGLE_ROLE: 'instructorSessionModeSingleRole',
  FULL_CYCLE_SINGLE_TRAINEE: 'instructorSessionModeFullCycle',
  MULTI_TRAINEE: 'instructorSessionModeMultiTrainee',
  ASSESSMENT: 'instructorSessionModeAssessment',
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

export function SessionsLandingPage() {
  const userLabel = useAuthStore((state) => state.user?.display_name_ru);
  const sessionsQuery = useQuery({
    queryKey: queryKeys.sessions.list('MINE'),
    queryFn: () => listSessions({ scope: 'MINE' }),
  });

  return (
    <AppShell title={t('sessionsTitle')} userLabel={userLabel}>
      <h1 className="text-lg font-semibold tracking-tight">{t('sessionsTitle')}</h1>
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
                      {session.scenario_slug} (v{session.scenario_version})
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {t(SESSION_MODE_LABEL_KEY[session.session_mode])} · {t('sessionsStateLabel')}: {session.state}
                    </p>
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
