import { Navigate, Route, Routes } from 'react-router';
import { LoginPage } from '@/features/auth/login-page';
import { OperatorPage } from '@/features/operator/operator-page';
import { DdsPage } from '@/features/dds/dds-page';
import { InstructorPage } from '@/features/instructor/instructor-page';
import { ReportPage } from '@/features/report/report-page';
import { NotFoundPage } from '@/app/not-found-page';

/**
 * Route table (declarative/library mode react-router v7, D12). Deliberately
 * not wrapped in a <BrowserRouter> here so tests can mount it inside a
 * <MemoryRouter> with arbitrary initial entries.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/operator/*" element={<OperatorPage />} />
      <Route path="/dds/*" element={<DdsPage />} />
      <Route path="/instructor/*" element={<InstructorPage />} />
      <Route path="/report/*" element={<ReportPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
