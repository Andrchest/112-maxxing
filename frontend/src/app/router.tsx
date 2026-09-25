import { Navigate, Route, Routes } from 'react-router';
import { LoginPage } from '@/features/auth/login-page';
import { RequireAuth } from '@/features/auth/require-auth';
import { RequireRole } from '@/features/auth/require-role';
import { OperatorPage } from '@/features/operator/operator-page';
import { OperatorConsolePage } from '@/features/operator/console-page';
import { DdsPage } from '@/features/dds/dds-page';
import { DdsConsolePage } from '@/features/dds/console-page';
import { InstructorPage } from '@/features/instructor/instructor-page';
import { InstructorLiveOverviewPage } from '@/features/instructor/live-overview-page';
import { ReportPage } from '@/features/report/report-page';
import { ReportIndexPage } from '@/features/report/report-index-page';
import { SessionsLandingPage } from '@/features/sessions/sessions-landing-page';
import { SessionOpenRedirect } from '@/features/sessions/session-open-redirect';
import { RegisterPage } from '@/features/operator/register-page';
import { DdsIncidentListPage } from '@/features/dds/incident-list-page';
import { LessonsPage } from '@/features/lesson/lessons-page';
import { LessonDetailPage } from '@/features/lesson/lesson-detail-page';
import { ScenariosPage } from '@/features/instructor/scenarios-page';
import { LessonBoardPage } from '@/features/instructor/lesson-board-page';
import { MaterialsPage } from '@/features/instructor/materials-page';
import { MaterialsReferencePage } from '@/features/materials/materials-reference-page';
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
 * Guards (D12 design decision #4): /operator and /dds are TRAINEE only; /instructor is
 * INSTRUCTOR|ADMIN only; /report admits all three account roles (the per-session release gate is
 * enforced by the backend, E16). `RequireAuth` sends anyone signed out to /login; `RequireRole`
 * sends a signed-in but wrongly-roled user to their own home route instead. `*` is deliberately
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
          {/* I3 E4b (70 §70.3.6, ui-check D-2): the 112 «реестр» — a static segment, so
              react-router ranks it ahead of the dynamic /operator/:sessionId above regardless of
              declaration order. */}
          <Route path="/operator/register" element={<RegisterPage />} />
          <Route path="/operator/*" element={<OperatorPage />} />
          <Route path="/dds/:sessionId" element={<DdsConsolePage />} />
          {/* I3 E4b (70 §70.3.6, ui-check D-8): the ДДС «Список происшествий». */}
          <Route path="/dds/incidents" element={<DdsIncidentListPage />} />
          <Route path="/dds/*" element={<DdsPage />} />
          {/* I4 E34 (71 §71.11, ТЗ ¶256): «Справочная база» — read-only for a trainee. */}
          <Route path="/materials" element={<MaterialsReferencePage />} />
        </Route>
        <Route element={<RequireRole roles={['INSTRUCTOR', 'ADMIN']} />}>
          {/* E17-C: more specific than /instructor/*, so react-router ranks it first regardless
              of declaration order (same pattern /operator/:sessionId, /dds/:sessionId use). */}
          <Route path="/instructor/sessions/:sessionId" element={<InstructorLiveOverviewPage />} />
          {/* I3 E4b (70 §70.3.1-§70.3.3): the lesson (занятие) plan editor, list and detail — the
              instructor creates a lesson of N cards, starts/aborts/releases it and sees the N
              card reports. More specific than /instructor/*, ranked first the same way. */}
          <Route path="/instructor/lessons/:lessonId" element={<LessonDetailPage />} />
          <Route path="/instructor/lessons" element={<LessonsPage />} />
          {/* I4 E32 (71 §71.9): the «Сценарии» upload/archive page and the all-trainees board,
              same "more specific, ranked first" pattern as the routes above. */}
          <Route path="/instructor/scenarios" element={<ScenariosPage />} />
          <Route path="/instructor/board/:lessonId" element={<LessonBoardPage />} />
          {/* I4 E34 (71 §71.11, ТЗ ¶227, ¶387, ¶370): upload, list and archive materials. */}
          <Route path="/instructor/materials" element={<MaterialsPage />} />
          <Route path="/instructor/*" element={<InstructorPage />} />
        </Route>
        {/* E16: the report is trainee-visible too (SPEC §29, D12 design decision #4) — the
            release gate itself is enforced by the backend (403 REPORT_NOT_RELEASED, rendered
            in-page by ReportPage), not by this route guard, since a trainee is otherwise allowed
            to open /report/:sessionId for a session they participated in. */}
        <Route element={<RequireRole roles={['TRAINEE', 'INSTRUCTOR', 'ADMIN']} />}>
          <Route path="/report/:sessionId" element={<ReportPage />} />
          <Route path="/report" element={<ReportIndexPage />} />
        </Route>
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
