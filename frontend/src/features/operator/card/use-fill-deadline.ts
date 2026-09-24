// The header strip's red countdown (REQ-3010, HLD 70 §70.3.4/C4): `SESSION_CREATED.timers.
// fill_within_ms`, counted from `CALL_ANSWERED` (`CallStateView.answered_at_offset_ms`). No REST
// field carries `timers` yet (I3 E4a left it in the event payload only, `SESSION_CREATED` §70.7)
// — this reads it the same way `services-panel.tsx` reads `RECIPIENTS_RESOLVED`: through the
// already-typed `listSessionEvents` (never a hand-rolled fetch, `client.ts`'s own contract), one
// query per session, cached. `payload` is untyped JSON (`SessionEventEnvelope.payload`), so the
// `timers` shape is read defensively; a session created before E4a (no `timers` key) falls back
// to the domain default (`180_000`, `card_status.py`).
import { useQuery } from '@tanstack/react-query';
import { listSessionEvents, queryKeys } from '@/shared/api';

const DEFAULT_FILL_WITHIN_MS = 180_000;

interface SessionCreatedTimersPayload {
  timers?: { fill_within_ms?: number } | null;
}

export function useFillWithinMs(sessionId: string): number {
  const query = useQuery({
    queryKey: [...queryKeys.sessions.detail(sessionId), 'session-created-timers'],
    queryFn: () => listSessionEvents(sessionId, { eventType: ['SESSION_CREATED'], limit: 1 }),
    staleTime: Infinity,
  });
  const payload = query.data?.items[0]?.payload as SessionCreatedTimersPayload | undefined;
  const fillWithinMs = payload?.timers?.fill_within_ms;
  return typeof fillWithinMs === 'number' && fillWithinMs > 0 ? fillWithinMs : DEFAULT_FILL_WITHIN_MS;
}

/** ms remaining until the fill deadline (negative once overdue); `null` before the call is
 * answered — the header timer only runs from `CALL_ANSWERED` (§70.3.4). */
export function computeFillRemainingMs(answeredAtOffsetMs: number | null, nowOffsetMs: number, fillWithinMs: number): number | null {
  if (answeredAtOffsetMs === null) return null;
  return answeredAtOffsetMs + fillWithinMs - nowOffsetMs;
}
