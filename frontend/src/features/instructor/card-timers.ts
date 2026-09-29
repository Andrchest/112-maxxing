// I4 E31 (71 §71.8, D34; ТЗ ¶240): the per-card timer override as the instructor types it, in
// seconds — shared by the lesson form (`PlanEntry.timers`, one draft per plan entry) and, since I7
// E49 (Q-E31-2), the single-session form (`SessionCreateRequest.timers`, one draft for the whole
// session). An empty field keeps the scenario's value; the backend resolves scenario ← override
// and refuses a result that breaks R39 (`resolve_card_timers`).
import type { CardTimersRequest } from '@/shared/api';

/** The three per-card timers of `CardTimersRequest`, in the order the fields are shown. */
export type TimerKey = keyof CardTimersRequest;

export const TIMER_KEYS: readonly TimerKey[] = ['accept_within_ms', 'fill_within_ms', 'not_completed_after_ms'];

export type TimerSeconds = Record<TimerKey, string>;

export const NO_TIMER_OVERRIDE: TimerSeconds = {
  accept_within_ms: '',
  fill_within_ms: '',
  not_completed_after_ms: '',
};

/** A typed value is a positive number of seconds; an empty one keeps the scenario's timer. */
export function timerSecondsValid(value: string): boolean {
  if (value.trim() === '') return true;
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds > 0;
}

/** `{ timers }` in session ms, or `{}` when every field is empty (the request sends no `timers`,
 * byte-identical to before this override existed). */
export function timersField(timerSeconds: TimerSeconds): { timers?: CardTimersRequest } {
  const timers: CardTimersRequest = {};
  for (const key of TIMER_KEYS) {
    const value = timerSeconds[key].trim();
    if (value !== '') timers[key] = Math.round(Number(value) * 1000);
  }
  return Object.keys(timers).length > 0 ? { timers } : {};
}
