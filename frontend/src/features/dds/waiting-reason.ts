// I6 UX: why a ДДС participant's snapshot has no work item yet — the pure part of
// `waiting-for-card-notice.tsx` (kept apart so that file exports only its component).
import type { LessonDetail, SessionSnapshot } from '@/shared/api';

/** How often the notice re-reads the lesson (and the console its snapshot) while waiting. */
export const WAITING_POLL_INTERVAL_MS = 3000;

export type WaitingReason =
  | { kind: 'LESSON_NOT_STARTED' }
  | { kind: 'SESSION_NOT_STARTED' }
  | { kind: 'CARD_IN'; seconds: number }
  | { kind: 'CARD_DUE' }
  | { kind: 'AFTER_PREVIOUS_112_STAGE' }
  | { kind: 'AFTER_PREVIOUS_SESSION' }
  | { kind: 'AWAITING_HANDOFF' };

/** Why a ДДС participant's snapshot has no work item yet. `nowMs` is the server's clock. */
export function waitingReason(snapshot: SessionSnapshot, lesson: LessonDetail | undefined, nowMs: number): WaitingReason {
  const { session } = snapshot;
  if (session.state !== 'CREATED' && session.state !== 'READY') {
    // The session runs, but the 112 stage has not handed the card to ДДС yet.
    return { kind: 'AWAITING_HANDOFF' };
  }
  if (!lesson || lesson.lesson_id !== session.lesson_id) return { kind: 'SESSION_NOT_STARTED' };
  if (lesson.state === 'CREATED') return { kind: 'LESSON_NOT_STARTED' };
  const card = lesson.sessions.find((entry) => entry.session_id === session.id);
  if (!card || lesson.state !== 'ACTIVE') return { kind: 'SESSION_NOT_STARTED' };
  if (card.arrival.kind === 'AFTER_PREVIOUS_112_STAGE') return { kind: 'AFTER_PREVIOUS_112_STAGE' };
  if (card.arrival.kind === 'AFTER_PREVIOUS_SESSION') return { kind: 'AFTER_PREVIOUS_SESSION' };
  if (!lesson.started_at) return { kind: 'LESSON_NOT_STARTED' };
  const dueMs = Date.parse(lesson.started_at) + (card.arrival.offset_ms ?? 0);
  const seconds = Math.ceil((dueMs - nowMs) / 1000);
  return seconds > 0 ? { kind: 'CARD_IN', seconds } : { kind: 'CARD_DUE' };
}
