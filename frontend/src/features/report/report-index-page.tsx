// Route: /report (index). A small list/redirect into `/report/:sessionId`, consistent with how
// `features/sessions/sessions-landing-page.tsx` links into a session's console: TRAINEE sees
// their own sessions (`scope: MINE`), INSTRUCTOR/ADMIN sees every session (`scope: ALL`) —
// whether a given report is actually reachable (COMPLETED/ABORTED, released or not) is decided by
// `getSessionReport` itself when the link is followed, not by this list.
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { AppShell } from '@/shared/ui/app-shell';
import { Button } from '@/shared/ui/button';
import { Card, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import { listSessions, problemMessageRu, queryKeys, type ProblemCode, type SessionMode, type SessionState, type UserRole } from '@/shared/api';
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

export function ReportIndexPage() {
  const user = useAuthStore((state) => state.user);
  const userLabel = user?.display_name_ru;
  const roleLabel = user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined;
  const scope = user?.user_role === 'TRAINEE' ? 'MINE' : 'ALL';

  const sessionsQuery = useQuery({
    queryKey: queryKeys.sessions.list(scope),
    queryFn: () => listSessions({ scope }),
  });

  return (
    <AppShell title={t('reportIndexTitle')} role={roleLabel} userLabel={userLabel}>
      <h1 className="text-lg font-semibold tracking-tight">{t('reportIndexTitle')}</h1>
      {sessionsQuery.isLoading ? <p className="mt-2 text-sm text-muted-foreground">{t('reportIndexLoading')}</p> : null}
      {sessionsQuery.isError ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {sessionsQuery.error instanceof ProblemError ? problemMessageRu(sessionsQuery.error.code as ProblemCode) : t('problemUnknown')}
        </p>
      ) : null}
      {sessionsQuery.data && sessionsQuery.data.items.length === 0 ? <p className="mt-2 text-sm text-muted-foreground">{t('reportIndexEmpty')}</p> : null}
      <ul className="mt-3 flex flex-col gap-2">
        {(sessionsQuery.data?.items ?? []).map((session) => (
          <li key={session.id}>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between gap-2">
                <div>
                  <p className="font-medium">
                    {session.scenario_slug} (v{session.scenario_version})
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {t(SESSION_MODE_LABEL_KEY[session.session_mode])} · {t('sessionsStateLabel')}: {t(SESSION_STATE_LABEL_KEY[session.state])}
                  </p>
                </div>
                <Button asChild size="sm">
                  <Link to={`/report/${session.id}`}>{t('reportIndexOpenButton')}</Link>
                </Button>
              </CardHeader>
            </Card>
          </li>
        ))}
      </ul>
    </AppShell>
  );
}
