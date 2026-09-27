// Sessions list on /instructor (E17-C task DO item 2): links every session into its live overview
// (`/instructor/sessions/:sessionId`, R4) and, for a terminal session, additionally into its report
// (`/report/:sessionId`) — mirrors `features/report/report-index-page.tsx`'s own list/redirect
// pattern, reusing the existing `listSessions` client fn (`scope: 'ALL'`: every session, not just
// ones this instructor created).
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { listScenarios, listSessions, problemMessageRu, queryKeys, type ProblemCode, type SessionMode } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { sessionStateLabelRu } from './instructor-labels';

const SESSION_MODE_LABEL_KEY: Record<SessionMode, keyof typeof ru> = {
  SINGLE_ROLE: 'instructorSessionModeSingleRole',
  FULL_CYCLE_SINGLE_TRAINEE: 'instructorSessionModeFullCycle',
  MULTI_TRAINEE: 'instructorSessionModeMultiTrainee',
  ASSESSMENT: 'instructorSessionModeAssessment',
};

export function InstructorSessionsList() {
  const sessionsQuery = useQuery({
    queryKey: queryKeys.sessions.list('ALL'),
    queryFn: () => listSessions({ scope: 'ALL' }),
  });
  // D3: the list shows the scenario's Russian title, not its (English/slug) identifier —
  // `SessionListItem` carries only `scenario_slug`, so this looks the title up from the scenario
  // catalog by slug, falling back to the slug itself for a scenario this fetch has not (yet)
  // returned (defensive, never a blank label).
  const scenariosQuery = useQuery({
    queryKey: queryKeys.scenarios.list(),
    queryFn: listScenarios,
  });
  const scenarioTitleBySlug = new Map((scenariosQuery.data?.items ?? []).map((scenario) => [scenario.slug, scenario.title_ru]));

  return (
    <Card className="max-w-xl">
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('instructorSessionsListTitle')}</h2>
        {/* I6 NAV2 (manager decision, final): points at `/instructor/lessons`, where «Начать
            занятие» actually lives — the owner could not find it starting from this list. */}
        <p className="text-xs text-muted-foreground">
          {t('instructorSessionsListHintPrefix')}{' '}
          «
          <Link to="/instructor/lessons" className="text-primary underline-offset-2 hover:underline">
            {t('instructorSessionsListHintLink')}
          </Link>
          ».
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {sessionsQuery.isLoading ? <p className="text-sm text-muted-foreground">{t('instructorSessionsListLoading')}</p> : null}
        {sessionsQuery.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {sessionsQuery.error instanceof ProblemError ? problemMessageRu(sessionsQuery.error.code as ProblemCode) : t('problemUnknown')}
          </p>
        ) : null}
        {sessionsQuery.data && sessionsQuery.data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('instructorSessionsListEmpty')}</p>
        ) : null}
        <ul className="flex flex-col gap-2">
          {(sessionsQuery.data?.items ?? []).map((session) => {
            const isTerminal = session.state === 'COMPLETED' || session.state === 'ABORTED';
            return (
              <li key={session.id} className="flex items-center justify-between gap-2 rounded-md border border-border p-2">
                <div>
                  <p className="text-sm font-medium">
                    {scenarioTitleBySlug.get(session.scenario_slug) ?? session.scenario_slug} (v{session.scenario_version})
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {t(SESSION_MODE_LABEL_KEY[session.session_mode])} · {t('sessionsStateLabel')}: {sessionStateLabelRu(session.state)}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button asChild size="sm" variant="outline">
                    <Link to={`/instructor/sessions/${session.id}`}>{t('instructorSessionsListOverviewButton')}</Link>
                  </Button>
                  {isTerminal ? (
                    <Button asChild size="sm">
                      <Link to={`/report/${session.id}`}>{t('reportIndexOpenButton')}</Link>
                    </Button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
