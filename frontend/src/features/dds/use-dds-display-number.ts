// The header strip's «Происшествие N» number for the ДДС console (I3 E5c manager review, mirrors
// `features/operator/card/use-display-number.ts` exactly — duplicated rather than cross-feature
// imported, same treatment `features/report/dds-decision-labels.ts`'s own header comment
// documents ("duplication-over-cross-feature-import")). `DdsWorkItem` carries no human card
// number either (only `assignment_id`/`incident_id`/`snapshot_id` UUIDs) — `IncidentListItem.
// display_number` (I3 E4a) reached through `listMyIncidents`, matched by `session_id`, is the same
// source the operator's own header strip uses.
import { useQuery } from '@tanstack/react-query';
import { listMyIncidents, queryKeys } from '@/shared/api';

/** The session's `display_number`, or `null` while it has not resolved yet (never a UUID
 * fallback). */
export function useDdsDisplayNumber(sessionId: string): number | null {
  const query = useQuery({
    queryKey: [...queryKeys.sessions.detail(sessionId), 'display-number'],
    queryFn: () => listMyIncidents(),
    staleTime: 30_000,
  });
  const item = query.data?.items.find((entry) => entry.session_id === sessionId);
  return item?.display_number ?? null;
}
