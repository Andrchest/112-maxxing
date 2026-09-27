import { describe, expect, it } from 'vitest';
import { waitingReason } from './waiting-reason';
import type { LessonDetail, SessionSnapshot } from '@/shared/api';

// I6 UX: why a ДДС participant has no work item yet, from the snapshot and the trainee's lesson.
function snapshot(state: string, lessonId: string | null = 'lesson-1'): SessionSnapshot {
  return { session: { id: 'sess-1', state, lesson_id: lessonId }, server_time_utc: '2026-09-27T10:00:00Z' } as unknown as SessionSnapshot;
}

function lesson(state: string, arrival: Record<string, unknown>, startedAt: string | null = '2026-09-27T10:00:00Z'): LessonDetail {
  return { lesson_id: 'lesson-1', state, started_at: startedAt, sessions: [{ session_id: 'sess-1', arrival }] } as unknown as LessonDetail;
}

const START = Date.parse('2026-09-27T10:00:00Z');

describe('waitingReason (I6 UX)', () => {
  it('a running session is waiting for the 112 handoff', () => {
    expect(waitingReason(snapshot('ACTIVE'), undefined, START)).toEqual({ kind: 'AWAITING_HANDOFF' });
  });

  it('a READY card of a lesson the instructor has not started', () => {
    expect(waitingReason(snapshot('READY'), lesson('CREATED', { kind: 'AT_OFFSET', offset_ms: 0 }, null), START)).toEqual({
      kind: 'LESSON_NOT_STARTED',
    });
  });

  it('a READY single session (no lesson) is not started either', () => {
    expect(waitingReason(snapshot('READY', null), undefined, START)).toEqual({ kind: 'SESSION_NOT_STARTED' });
  });

  it('counts down to an AT_OFFSET card of a running lesson, then says it is arriving', () => {
    const running = lesson('ACTIVE', { kind: 'AT_OFFSET', offset_ms: 60000 });
    expect(waitingReason(snapshot('READY'), running, START + 15500)).toEqual({ kind: 'CARD_IN', seconds: 45 });
    expect(waitingReason(snapshot('READY'), running, START + 61000)).toEqual({ kind: 'CARD_DUE' });
  });

  it('names the previous-card arrival kinds', () => {
    expect(waitingReason(snapshot('READY'), lesson('ACTIVE', { kind: 'AFTER_PREVIOUS_SESSION' }), START)).toEqual({ kind: 'AFTER_PREVIOUS_SESSION' });
    expect(waitingReason(snapshot('READY'), lesson('ACTIVE', { kind: 'AFTER_PREVIOUS_112_STAGE' }), START)).toEqual({
      kind: 'AFTER_PREVIOUS_112_STAGE',
    });
  });
});
