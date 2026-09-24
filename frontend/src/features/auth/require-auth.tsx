import { Navigate, Outlet, useLocation } from 'react-router';
import { useAuthStore } from '@/entities/session';
import { useServiceCatalogLoader } from '@/entities/service-catalog';

/** Redirects to /login when no one is signed in. Wraps every route group in `app/router.tsx`
 * except /login itself (D12 design decision #4). Every signed-in page lives under it, so it is also
 * where the service catalog (I3 E2a, service names) is loaded once. */
export function RequireAuth() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const location = useLocation();
  useServiceCatalogLoader(isAuthenticated);

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}
