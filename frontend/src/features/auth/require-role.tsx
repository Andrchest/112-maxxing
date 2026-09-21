import { Navigate, Outlet } from 'react-router';
import { useAuthStore, homeRouteForRole } from '@/entities/session';
import type { UserRole } from '@/shared/api';

interface RequireRoleProps {
  roles: readonly UserRole[];
}

/** Redirects a signed-in user whose account role is not in `roles` to their own home route
 * instead of rendering the page (D12 design decision #4: /operator and /dds are TRAINEE,
 * /instructor is INSTRUCTOR|ADMIN). Assumes `RequireAuth` already guaranteed someone is signed
 * in; falls back to /login defensively if it somehow did not. */
export function RequireRole({ roles }: RequireRoleProps) {
  const user = useAuthStore((state) => state.user);

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (!roles.includes(user.user_role)) {
    return <Navigate to={homeRouteForRole(user.user_role)} replace />;
  }

  return <Outlet />;
}
