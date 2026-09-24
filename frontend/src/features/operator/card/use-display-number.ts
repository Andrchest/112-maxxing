// The header strip's «Происшествие N» number (manager review, I3 E3b): `OperatorCardView` carries
// no human card number (E3a′'s own gap note: "header identity … are system values, not card
// fields") and neither does `SessionDetail`/`SessionSnapshot` — but `IncidentListItem.
// display_number` (I3 E4a) is reachable for the caller's own sessions through the already-typed
// `listMyIncidents` (`shared/api/client.ts`, untouched here), the same list the register/incident
// screens use. This matches by `session_id` rather than `incident_id` because that is what this
// component already has (`CardForm`'s `sessionId` prop) without a second lookup.
//
// No `role_type` filter: `IncidentListItem.my_role_type` (and so the server-side `role_type`
// query filter) is only ever populated for a lesson's participant assignment — a standalone
// (non-lesson) session's own row comes back with `my_role_type: null` and would be filtered out
// by `role_type=OPERATOR_112`, confirmed live (I3 E3b UI run against a plain
// `FULL_CYCLE_SINGLE_TRAINEE` session). The unfiltered list still only ever holds the caller's own
// sessions (`listMyIncidents`'s own contract), so this never reads another trainee's number.
import { useQuery } from '@tanstack/react-query';
import { listMyIncidents, queryKeys } from '@/shared/api';

/** The session's `display_number`, or `null` while it has not resolved yet (never a UUID
 * fallback — the manager review's rule: "if not reachable, show no number"). */
export function useDisplayNumber(sessionId: string): number | null {
  const query = useQuery({
    queryKey: [...queryKeys.sessions.detail(sessionId), 'display-number'],
    queryFn: () => listMyIncidents(),
    staleTime: 30_000,
  });
  const item = query.data?.items.find((entry) => entry.session_id === sessionId);
  return item?.display_number ?? null;
}
