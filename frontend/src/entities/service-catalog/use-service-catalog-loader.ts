// Loads the service catalog once per signed-in app (HLD 70 §70.6.3, D18). Mounted by
// `ServiceCatalogLoader` at the app root; a failed load leaves the legacy fallback labels in place
// and retries on the next mount — no screen depends on the catalog to function.
import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { listReferenceServices, queryKeys } from '@/shared/api';
import { useServiceCatalogStore } from './service-catalog-store';

export function useServiceCatalogLoader(enabled: boolean): void {
  const { data } = useQuery({
    queryKey: queryKeys.reference.services(),
    queryFn: () => listReferenceServices({ includeHidden: true }),
    enabled,
    staleTime: Infinity,
    retry: false,
  });
  useEffect(() => {
    if (data) {
      useServiceCatalogStore.getState().setEntries(data);
    }
  }, [data]);
}
