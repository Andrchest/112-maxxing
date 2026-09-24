// I3 E4b (70 §70.3.6, §70.4.6; D15): Russian labels for the Lesson/`card_status`/`Arrival`
// enums, same "exhaustive `generated union -> ru.ts key` table" pattern `features/dds/dds-labels.ts`
// and `client.ts`'s `PROBLEM_MESSAGE_KEYS` use (D12 design decision #5). `CardStatus` is a
// SERVER-materialised projection (`incidents.card_status`, 70 §70.4.6) — this file only maps the
// seven enum members to their memo p.27 label, it never computes a status from timers or offsets.
import { ru } from '@/shared/i18n/ru';
import { t } from '@/shared/i18n';
import type { ArrivalKind, CardStatus, LessonState } from '@/shared/api';

export const CARD_STATUS_LABEL_KEY: Record<CardStatus, keyof typeof ru> = {
  REGISTERED: 'lessonCardStatusRegistered',
  WORKED: 'lessonCardStatusWorked',
  CHECKED: 'lessonCardStatusChecked',
  NOT_NOTIFIED: 'lessonCardStatusNotNotified',
  REFUSED: 'lessonCardStatusRefused',
  NOT_COMPLETED: 'lessonCardStatusNotCompleted',
  COMPLETED: 'lessonCardStatusCompleted',
};

export function cardStatusLabelRu(value: CardStatus): string {
  return t(CARD_STATUS_LABEL_KEY[value]);
}

/** The three statuses the reference marks red (REQ-5312, ui-check D-8/D-10). A pure predicate
 * over the server's own `card_status` — no timer or offset comparison happens here. */
const RED_FLAG_CARD_STATUSES: ReadonlySet<CardStatus> = new Set(['NOT_NOTIFIED', 'REFUSED', 'NOT_COMPLETED']);

export function isRedFlagCardStatus(value: CardStatus): boolean {
  return RED_FLAG_CARD_STATUSES.has(value);
}

export const LESSON_STATE_LABEL_KEY: Record<LessonState, keyof typeof ru> = {
  CREATED: 'lessonStateCreated',
  ACTIVE: 'lessonStateActive',
  COMPLETED: 'lessonStateCompleted',
  ABORTED: 'lessonStateAborted',
};

export function lessonStateLabelRu(value: LessonState): string {
  return t(LESSON_STATE_LABEL_KEY[value]);
}

export const ARRIVAL_KIND_LABEL_KEY: Record<ArrivalKind, keyof typeof ru> = {
  AT_OFFSET: 'lessonArrivalKindAtOffset',
  AFTER_PREVIOUS_112_STAGE: 'lessonArrivalKindAfterPrevious112Stage',
  AFTER_PREVIOUS_SESSION: 'lessonArrivalKindAfterPreviousSession',
};

export function arrivalKindLabelRu(value: ArrivalKind): string {
  return t(ARRIVAL_KIND_LABEL_KEY[value]);
}
