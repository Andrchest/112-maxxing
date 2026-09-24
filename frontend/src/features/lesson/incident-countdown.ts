// I3 E4b (70 §70.3.6): countdowns are computed from `IncidentListItem`'s server offsets only
// (`session_offset_ms` plus the wall-clock elapsed since the row was fetched) — this file never
// reads or infers a `card_status`. Pure and unit-tested on its own; the component that renders a
// countdown owns the ticking `setInterval`, this module owns the arithmetic and formatting.

/** `null` when the row carries no such deadline yet (openapi: "`null` = not applicable yet"). A
 * negative result means the deadline has passed — the caller decides how to render that (this
 * module makes no status/colour decision). */
export function remainingDeadlineMs(
  deadlineOffsetMs: number | null,
  sessionOffsetMs: number,
  elapsedSinceFetchMs: number,
): number | null {
  if (deadlineOffsetMs === null) return null;
  return deadlineOffsetMs - (sessionOffsetMs + elapsedSinceFetchMs);
}

/** `mm:ss`, or `h:mm:ss` once an hour is reached. Negative input clamps to zero — the caller
 * renders "overdue" separately instead of a negative clock. */
export function formatDurationMs(ms: number): string {
  const clamped = Math.max(0, Math.round(ms / 1000)) * 1000;
  const totalSeconds = Math.floor(clamped / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`;
}
