import { describe, expect, it } from 'vitest';
import { ru } from '@/shared/i18n/ru';
import type { CardStatus } from '@/shared/api';
import { cardStatusLabelRu, isRedFlagCardStatus } from './lesson-labels';

const ALL_CARD_STATUSES: readonly CardStatus[] = [
  'REGISTERED',
  'WORKED',
  'CHECKED',
  'NOT_NOTIFIED',
  'REFUSED',
  'NOT_COMPLETED',
  'COMPLETED',
];

describe('cardStatusLabelRu — server-derived card status labels (70 §70.4.6)', () => {
  it('renders the memo p.27 Russian label for every CardStatus member', () => {
    expect(cardStatusLabelRu('REGISTERED')).toBe(ru.lessonCardStatusRegistered);
    expect(cardStatusLabelRu('WORKED')).toBe(ru.lessonCardStatusWorked);
    expect(cardStatusLabelRu('CHECKED')).toBe(ru.lessonCardStatusChecked);
    expect(cardStatusLabelRu('NOT_NOTIFIED')).toBe(ru.lessonCardStatusNotNotified);
    expect(cardStatusLabelRu('REFUSED')).toBe(ru.lessonCardStatusRefused);
    expect(cardStatusLabelRu('NOT_COMPLETED')).toBe(ru.lessonCardStatusNotCompleted);
    expect(cardStatusLabelRu('COMPLETED')).toBe(ru.lessonCardStatusCompleted);
  });
});

describe('isRedFlagCardStatus — REQ-5312 (ui-check D-8/D-10)', () => {
  it('flags exactly NOT_NOTIFIED, REFUSED and NOT_COMPLETED', () => {
    const flagged = ALL_CARD_STATUSES.filter((status) => isRedFlagCardStatus(status));
    expect(flagged.sort()).toEqual(['NOT_COMPLETED', 'NOT_NOTIFIED', 'REFUSED'].sort());
  });

  it('does not flag REGISTERED, WORKED, CHECKED or COMPLETED', () => {
    expect(isRedFlagCardStatus('REGISTERED')).toBe(false);
    expect(isRedFlagCardStatus('WORKED')).toBe(false);
    expect(isRedFlagCardStatus('CHECKED')).toBe(false);
    expect(isRedFlagCardStatus('COMPLETED')).toBe(false);
  });
});
