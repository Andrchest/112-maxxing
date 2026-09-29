// I7 E56: the two per-user tutorial preferences, kept in localStorage per user id — «the first-login
// card was answered» and «beginner hints are on». Every access is wrapped in try/catch: with no
// storage (private mode, blocked site data) the card simply shows again and the hints start off,
// both harmless. The values are also mirrored in a zustand store so every «?» icon and the card
// re-render the moment the user flips them.
import { create } from 'zustand';

const SEEN_KEY_PREFIX = 'tour.seen.';
const HINTS_KEY_PREFIX = 'tour.hints.';

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* best effort only — see the module comment */
  }
}

interface PreferencesState {
  /** user id → first-login card answered («Начать обучение» or «Не сейчас»). */
  seen: Record<string, boolean>;
  /** user id → beginner hints on. */
  hints: Record<string, boolean>;
  markSeen: (userId: string) => void;
  setHints: (userId: string, enabled: boolean) => void;
}

export const useTourPreferences = create<PreferencesState>((set) => ({
  seen: {},
  hints: {},
  markSeen: (userId) => {
    write(SEEN_KEY_PREFIX + userId, '1');
    set((state) => ({ seen: { ...state.seen, [userId]: true } }));
  },
  setHints: (userId, enabled) => {
    write(HINTS_KEY_PREFIX + userId, enabled ? '1' : '0');
    set((state) => ({ hints: { ...state.hints, [userId]: enabled } }));
  },
}));

/** Whether this user already answered the first-login card (store first, then localStorage). */
export function useTourSeen(userId: string | undefined): boolean {
  const fromStore = useTourPreferences((state) => (userId ? state.seen[userId] : undefined));
  if (!userId) return true;
  return fromStore ?? read(SEEN_KEY_PREFIX + userId) === '1';
}

/** Whether this user turned the beginner hints on (default off). */
export function useHintsEnabled(userId: string | undefined): boolean {
  const fromStore = useTourPreferences((state) => (userId ? state.hints[userId] : undefined));
  if (!userId) return false;
  return fromStore ?? read(HINTS_KEY_PREFIX + userId) === '1';
}
