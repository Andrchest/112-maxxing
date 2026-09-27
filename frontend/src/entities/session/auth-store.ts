// Entity: the authenticated account (SPEC §32, §39; D12 design decision #4). Zustand store for
// the one non-realtime piece of session-shaped state the frontend keeps: the signed-in user and
// their token. Token in memory + sessionStorage — never a URL, never logged, and a browser
// refresh keeps the session because sessionStorage survives it.
import { create } from 'zustand';
import { setAuthToken, setUnauthorizedHandler } from '@/shared/lib/api';
import { AUTH_TOKEN_STORAGE_KEY, AUTH_USER_STORAGE_KEY } from '@/shared/config';
import type { UserAccount } from '@/shared/api';

export type { UserAccount };

interface AuthState {
  token: string | null;
  user: UserAccount | null;
  isAuthenticated: boolean;
  login: (token: string, user: UserAccount) => void;
  logout: () => void;
}

function readStorage(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    // sessionStorage can throw (private browsing, disabled storage); the token then only
    // lives for this render, which still satisfies "never a URL, never logged".
    return null;
  }
}

function writeStorage(key: string, value: string): void {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    /* best-effort persistence only — see readStorage */
  }
}

function clearStorage(key: string): void {
  try {
    sessionStorage.removeItem(key);
  } catch {
    /* best-effort persistence only — see readStorage */
  }
}

function readStoredUser(): UserAccount | null {
  const raw = readStorage(AUTH_USER_STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as UserAccount;
  } catch {
    return null;
  }
}

const initialToken = readStorage(AUTH_TOKEN_STORAGE_KEY);
const initialUser = initialToken ? readStoredUser() : null;
if (initialToken && initialUser) {
  setAuthToken(initialToken);
}

export const useAuthStore = create<AuthState>((set) => ({
  token: initialToken && initialUser ? initialToken : null,
  user: initialToken && initialUser ? initialUser : null,
  isAuthenticated: Boolean(initialToken && initialUser),
  login: (token, user) => {
    setAuthToken(token);
    writeStorage(AUTH_TOKEN_STORAGE_KEY, token);
    writeStorage(AUTH_USER_STORAGE_KEY, JSON.stringify(user));
    set({ token, user, isAuthenticated: true });
  },
  logout: () => {
    setAuthToken(null);
    clearStorage(AUTH_TOKEN_STORAGE_KEY);
    clearStorage(AUTH_USER_STORAGE_KEY);
    set({ token: null, user: null, isAuthenticated: false });
  },
}));

// A 401 from any REST call means the token stopped being valid; log out rather than leaving
// stale credentials around (D8, SPEC §39).
setUnauthorizedHandler(() => {
  useAuthStore.getState().logout();
});

/** Where an authenticated user's own role lands them after login (D12 design decision #4). A
 * TRAINEE has no account-level RoleType — that is assigned per session, not per user — so they
 * land on "my sessions" (`features/sessions`, E8-B) and pick a session from there; its console
 * routes (`/operator/:sessionId`, `/dds/:sessionId`) resolve the per-session role.
 *
 * I4 E30 (71 §71.7): ADMIN now lands on `/admin` instead of `/instructor` — its own screens over
 * E28/E29. Whether ADMIN also keeps INSTRUCTOR's own powers is Q-E14-1, undecided by the owner
 * (71 §71.5); `/instructor/*`'s own `RequireRole` guard is unchanged by this epic, so an ADMIN
 * that navigates there directly still gets in.
 *
 * I6 NAV2 (manager decision, final): INSTRUCTOR now lands on `/instructor/lessons`, not
 * `/instructor` — the owner following `docs/demo-scenario.md` could not find «Открыть» for a
 * lesson from `/instructor`'s own sessions list (per-card sessions, no «Начать занятие»); the
 * real lessons list with «Начать занятие» is `/instructor/lessons`. `/instructor` itself is
 * unchanged and still reachable from the role navigation bar. */
export function homeRouteForRole(role: UserAccount['user_role']): string {
  switch (role) {
    case 'TRAINEE':
      return '/sessions';
    case 'INSTRUCTOR':
      return '/instructor/lessons';
    case 'ADMIN':
      return '/admin';
  }
}
