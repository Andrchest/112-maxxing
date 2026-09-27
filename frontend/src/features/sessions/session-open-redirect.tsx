// Route: /sessions/:sessionId/open (E10). `SessionListItem.my_role_type` is literally
// `session_participants.assigned_role_type`, which is deliberately `null` under
// `ALL_STAGES_ONE_PARTICIPANT` (`docs/hld/00-decisions.md` D6, `FULL_CYCLE_SINGLE_TRAINEE`'s own
// assignment rule) — one trainee plays every stage in the role chain, so no single row names
// "their" role. `getSessionSnapshot`'s own `my_role_type` falls back to the *active stage's* role
// for that participant (`backend/app/application/sessions/get_snapshot.py`'s `_my_role_type`),
// which the session list does not carry. This page fetches the snapshot once and routes to
// whichever console (`/operator/:id` or `/dds/:id`) the session is actually on right now — never
// a client-side guess at which stage is active.
import { useParams, Navigate } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { AppShell } from '@/shared/ui/app-shell';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import { getSessionSnapshot, problemMessageRu, queryKeys, type ProblemCode, type UserRole } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

export function SessionOpenRedirect() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const user = useAuthStore((state) => state.user);
  const userLabel = user?.display_name_ru;
  const roleLabel = user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined;

  const query = useQuery({
    queryKey: queryKeys.sessions.snapshot(sessionId ?? ''),
    queryFn: () => getSessionSnapshot(sessionId ?? ''),
    enabled: sessionId !== undefined,
  });

  if (!sessionId) {
    return null;
  }

  if (query.isLoading) {
    return (
      <AppShell backTo="/sessions" title={t('sessionsTitle')} role={roleLabel} userLabel={userLabel}>
        <p className="text-sm text-muted-foreground">{t('sessionsOpeningConsole')}</p>
      </AppShell>
    );
  }

  if (query.isError) {
    const message = query.error instanceof ProblemError ? problemMessageRu(query.error.code as ProblemCode) : t('problemUnknown');
    return (
      <AppShell backTo="/sessions" title={t('sessionsTitle')} role={roleLabel} userLabel={userLabel}>
        <p role="alert" className="text-sm text-destructive">
          {message}
        </p>
      </AppShell>
    );
  }

  const role = query.data?.my_role_type ?? query.data?.active_role_type ?? null;
  if (role === 'OPERATOR_112') {
    return <Navigate to={`/operator/${sessionId}`} replace />;
  }
  if (role === 'DDS') {
    return <Navigate to={`/dds/${sessionId}`} replace />;
  }

  return (
    <AppShell backTo="/sessions" title={t('sessionsTitle')} role={roleLabel} userLabel={userLabel}>
      <p className="text-sm text-muted-foreground">{t('sessionsNoConsoleYet')}</p>
    </AppShell>
  );
}
