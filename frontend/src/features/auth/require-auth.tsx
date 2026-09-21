import { Navigate, Outlet, useLocation } from 'react-router';
import { useAuthStore } from '@/entities/session';

/** Redirects to /login when no one is signed in. Wraps every route group in `app/router.tsx`
 * except /login itself (D12 design decision #4). */
export function RequireAuth() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}
