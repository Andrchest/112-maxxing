import { Navigate, Route, Routes } from 'react-router';
import { LoginPage } from '@/features/auth/login-page';
import { RequireAuth } from '@/features/auth/require-auth';
import { RequireRole } from '@/features/auth/require-role';
import { OperatorPage } from '@/features/operator/operator-page';
import { OperatorConsolePage } from '@/features/operator/console-page';
import { DdsPage } from '@/features/dds/dds-page';
import { DdsConsolePage } from '@/features/dds/console-page';
import { InstructorPage } from '@/features/instructor/instructor-page';
import { ReportPage } from '@/features/report/report-page';
import { SessionsLandingPage } from '@/features/sessions/sessions-landing-page';
import { SessionOpenRedirect } from '@/features/sessions/session-open-redirect';
import { NotFoundPage } from '@/app/not-found-page';
import { useAuthStore, homeRouteForRole } from '@/entities/session';

/** Redirects `/` to /login when signed out, or to the caller's role home route when signed in
 * (D12 design decision #4). */
function RootRedirect() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const user = useAuthStore((state) => state.user);

  if (!isAuthenticated || !user) {
    return <Navigate to="/login" replace />;
  }
  return <Navigate to={homeRouteForRole(user.user_role)} replace />;
}

/**
 * Route table (declarative/library mode react-router v7, D12). Deliberately
 * not wrapped in a <BrowserRouter> here so tests can mount it inside a
 * <MemoryRouter> with arbitrary initial entries.
 *
 * Guards (D12 design decision #4): /operator and /dds are TRAINEE only; /instructor and /report
 * are INSTRUCTOR|ADMIN only. `RequireAuth` sends anyone signed out to /login; `RequireRole` sends
 * a signed-in but wrongly-roled user to their own home route instead. `*` is deliberately
 * outside every guard — an unknown path is shown as 404 regardless of auth state.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<RequireRole roles={['TRAINEE']} />}>
          <Route path="/sessions" element={<SessionsLandingPage />} />
          {/* E10: resolves a FULL_CYCLE_SINGLE_TRAINEE participant's own console by the session's
              active stage, when `SessionListItem.my_role_type` is null (`session_participants.
              assigned_role_type` is deliberately null under `ALL_STAGES_ONE_PARTICIPANT`, D6). */}
          <Route path="/sessions/:sessionId/open" element={<SessionOpenRedirect />} />
          {/* E8-B/E10: the per-session consoles. More specific than /operator/*, /dds/* below, so
              react-router ranks them first regardless of declaration order. */}
          <Route path="/operator/:sessionId" element={<OperatorConsolePage />} />
          <Route path="/operator/*" element={<OperatorPage />} />
          <Route path="/dds/:sessionId" element={<DdsConsolePage />} />
          <Route path="/dds/*" element={<DdsPage />} />
        </Route>
        <Route element={<RequireRole roles={['INSTRUCTOR', 'ADMIN']} />}>
          <Route path="/instructor/*" element={<InstructorPage />} />
          {/* TODO(E16): the report becomes trainee-visible once the instructor releases it
              (SPEC §29, D12 design decision #4). Restricted to INSTRUCTOR|ADMIN until then. */}
          <Route path="/report/*" element={<ReportPage />} />
        </Route>
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
