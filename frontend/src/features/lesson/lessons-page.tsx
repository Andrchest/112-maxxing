// Route: /instructor/lessons (I3 E4b, 70 §70.3). Create a lesson (занятие) of N cards and list
// every lesson, linking into `/instructor/lessons/:lessonId` for the plan, the sessions and (once
// terminal) the N card reports. I3 E9a: the trainee groups a lesson may be created for are
// managed here too (70 §70.3.7).
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router';
import { AppShell } from '@/shared/ui/app-shell';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { Button } from '@/shared/ui/button';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import { listLessons, problemMessageRu, queryKeys, type LessonDetail, type ProblemCode, type SessionMode, type UserRole } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { LessonCreateForm } from '@/features/instructor/lesson-create-form';
import { TraineeGroupsCard } from '@/features/instructor/trainee-groups-card';
import { lessonStateLabelRu } from './lesson-labels';

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

const SESSION_MODE_LABEL_KEY: Record<SessionMode, keyof typeof ru> = {
  SINGLE_ROLE: 'instructorSessionModeSingleRole',
  FULL_CYCLE_SINGLE_TRAINEE: 'instructorSessionModeFullCycle',
  MULTI_TRAINEE: 'instructorSessionModeMultiTrainee',
  ASSESSMENT: 'instructorSessionModeAssessment',
};

function LessonsList() {
  const lessonsQuery = useQuery({
    queryKey: queryKeys.lessons.list('ALL'),
    queryFn: () => listLessons({ scope: 'ALL' }),
  });

  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('lessonsPageTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {lessonsQuery.isLoading ? <p className="text-sm text-muted-foreground">{t('lessonsListLoading')}</p> : null}
        {lessonsQuery.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {lessonsQuery.error instanceof ProblemError
              ? problemMessageRu(lessonsQuery.error.code as ProblemCode)
              : t('problemUnknown')}
          </p>
        ) : null}
        {lessonsQuery.data && lessonsQuery.data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('lessonsListEmpty')}</p>
        ) : null}
        <ul className="flex flex-col gap-2">
          {(lessonsQuery.data?.items ?? []).map((lesson) => (
            <li key={lesson.lesson_id} className="flex items-center justify-between gap-2 rounded-md border border-border p-2">
              <div>
                <p className="text-sm font-medium">{lesson.title_ru}</p>
                <p className="text-xs text-muted-foreground">
                  {t(SESSION_MODE_LABEL_KEY[lesson.session_mode])} · {lessonStateLabelRu(lesson.state)} · {lesson.card_count}
                </p>
              </div>
              <Button asChild size="sm" variant="outline">
                <Link to={`/instructor/lessons/${lesson.lesson_id}`}>{t('lessonsListOpenButton')}</Link>
              </Button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function LessonsPage() {
  const user = useAuthStore((state) => state.user);
  const roleLabel = user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined;
  const navigate = useNavigate();

  // I6 NAV2 (manager decision, final): the owner following `docs/demo-scenario.md` could not find
  // «Открыть» for a freshly created lesson because the lessons list sat BELOW a long form —
  // moved above it here. Creating a lesson navigates straight to its own detail page (simpler
  // than a scroll-to/highlight on this page, and that page is where «Начать занятие» lives).
  function handleCreated(lesson: LessonDetail): void {
    navigate(`/instructor/lessons/${lesson.lesson_id}`);
  }

  return (
    <AppShell
      title={t('lessonsPageTitle')}
      role={roleLabel}
      userLabel={user?.display_name_ru}
      connectionIndicatorHidden
    >
      <h1 className="text-lg font-semibold tracking-tight">{t('lessonsPageTitle')}</h1>
      <div className="mt-4 flex flex-col gap-4">
        <TraineeGroupsCard />
        <LessonsList />
        <LessonCreateForm onCreated={handleCreated} />
      </div>
    </AppShell>
  );
}
