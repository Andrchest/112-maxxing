// Route: /instructor/board/:lessonId (I4 E32, HLD `71-i4-wave4.md` §71.9, ТЗ ¶224, ¶235,
// Q&A L786–789 «видит действия обучаемых, их результаты… всех обучаемых»). A per-lesson table of
// every card: trainee, state, card status and the score once completed.
//
// Technical choice (71 §71.9 leaves it to E32): built from `getLesson`, polled, rather than the
// optional `getLessonBoard` read model or one WebSocket per active card. `getLesson` already
// returns every card's `state`/`card_status`/`arrival` in one call; trainee names come from one
// `listUsers` call resolved against the lesson's own `participants` (a lesson's participants are
// not tracked per card position in `LessonDetail`, so every card shows the lesson's full trainee
// list rather than a precise per-card subset — a fetch-N-sessions-per-card join was judged not
// worth its cost for a first cut, and is called out in the epic's own report). The score column
// is filled in only once the lesson is terminal, from the existing `getLessonReport` (no new
// evaluator, D11).
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router';
import { AppShell } from '@/shared/ui/app-shell';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import {
  getLesson,
  getLessonReport,
  listUsers,
  problemMessageRu,
  queryKeys,
  type LessonReport,
  type ProblemCode,
  type UserRole,
} from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

const BOARD_POLL_INTERVAL_MS = 3000;
const TERMINAL_STATES = new Set(['COMPLETED', 'ABORTED']);

function scorePercentOf(report: LessonReport | undefined, position: number): number | null {
  const card = report?.cards.find((c) => c.position === position);
  if (!card?.score || card.score.total_max_points <= 0) return null;
  return Math.round((card.score.total_points / card.score.total_max_points) * 100);
}

export function LessonBoardPage() {
  const { lessonId } = useParams<{ lessonId: string }>();
  const user = useAuthStore((state) => state.user);

  const lessonQuery = useQuery({
    queryKey: queryKeys.lessons.detail(lessonId ?? ''),
    queryFn: () => getLesson(lessonId ?? ''),
    enabled: lessonId !== undefined,
    refetchInterval: BOARD_POLL_INTERVAL_MS,
  });

  const usersQuery = useQuery({
    queryKey: queryKeys.users.list(),
    queryFn: () => listUsers(),
  });

  const lesson = lessonQuery.data;
  const isTerminal = lesson !== undefined && TERMINAL_STATES.has(lesson.state);

  const reportQuery = useQuery({
    queryKey: queryKeys.lessons.report(lessonId ?? ''),
    queryFn: () => getLessonReport(lessonId ?? ''),
    enabled: lessonId !== undefined && isTerminal,
    retry: false,
  });

  const nameByUserId = new Map((usersQuery.data?.items ?? []).map((account) => [account.id, account.display_name_ru]));
  const traineeNames = (lesson?.participants ?? [])
    .map((participant) => nameByUserId.get(participant.user_id) ?? participant.user_id)
    .join(', ');

  return (
    <AppShell
      backTo={lessonId ? `/instructor/lessons/${lessonId}` : '/instructor/lessons'}
      title={t('instructorBoardTitle')}
      userLabel={user?.display_name_ru}
      role={user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined}
    >
      <h1 className="text-lg font-semibold tracking-tight">
        {t('instructorBoardTitle')}
        {lesson ? `: ${lesson.title_ru}` : ''}
      </h1>
      <Card className="mt-4">
        <CardHeader />
        <CardContent>
          {lessonQuery.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {lessonQuery.error instanceof ProblemError ? problemMessageRu(lessonQuery.error.code as ProblemCode) : t('problemUnknown')}
            </p>
          ) : (lesson?.sessions.length ?? 0) === 0 ? (
            <p className="text-sm text-muted-foreground">{t('instructorBoardEmpty')}</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="pr-2">{t('instructorBoardColumnPosition')}</th>
                  <th className="pr-2">{t('instructorBoardColumnTrainee')}</th>
                  <th className="pr-2">{t('instructorBoardColumnState')}</th>
                  <th className="pr-2">{t('instructorBoardColumnCardStatus')}</th>
                  <th className="pr-2">{t('instructorBoardColumnScore')}</th>
                </tr>
              </thead>
              <tbody>
                {(lesson?.sessions ?? [])
                  .slice()
                  .sort((a, b) => a.position - b.position)
                  .map((card) => {
                    const percent = scorePercentOf(reportQuery.data, card.position);
                    return (
                      <tr key={card.session_id} className="border-t border-border">
                        <td className="py-1 pr-2">{card.position}</td>
                        <td className="py-1 pr-2">{traineeNames}</td>
                        <td className="py-1 pr-2">{card.state}</td>
                        <td className="py-1 pr-2">{card.card_status}</td>
                        <td className="py-1 pr-2">{percent === null ? t('instructorBoardScorePending') : `${percent}%`}</td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </AppShell>
  );
}
