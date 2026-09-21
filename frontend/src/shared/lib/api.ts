import { API_BASE_PATH } from '@/shared/config';

/**
 * RFC 7807 problem+json body, extended with the application-specific
 * `code` field every backend error carries (SPEC §32/§33 error contract).
 */
export interface ProblemDetails {
  type?: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  code: string;
  [key: string]: unknown;
}

/** Thrown by {@link apiFetch} for any non-2xx response the backend describes
 * as application/problem+json. `code` is the stable machine-readable reason
 * the UI branches on; `title`/`detail` are for display or logging. */
export class ProblemError extends Error {
  readonly status: number;
  readonly code: string;
  readonly title: string;
  readonly detail?: string;
  readonly type?: string;
  readonly instance?: string;
  readonly problem: ProblemDetails;

  constructor(problem: ProblemDetails, status: number) {
    super(problem.detail ?? problem.title);
    this.name = 'ProblemError';
    this.status = status;
    this.code = problem.code;
    this.title = problem.title;
    this.detail = problem.detail;
    this.type = problem.type;
    this.instance = problem.instance;
    this.problem = problem;
  }
}

const PROBLEM_JSON_CONTENT_TYPE = 'application/problem+json';

let authToken: string | null = null;

/**
 * Sets (or clears, with `null`) the bearer token every {@link apiFetch} call attaches. The
 * token's lifecycle (login, sessionStorage persistence, logout) belongs to
 * `entities/session`'s auth store (D12); this module only holds the value it needs to inject,
 * so `shared/lib` never depends on a higher FSD layer.
 */
export function setAuthToken(token: string | null): void {
  authToken = token;
}

/** The bearer token currently attached to every request, or `null` if signed out. */
export function getAuthToken(): string | null {
  return authToken;
}

let unauthorizedHandler: (() => void) | null = null;

/** Registered once by the auth store so any `401` response logs the user out (D8/SPEC §39: a
 * token that stops being valid must never leave the app pretending it is still signed in). */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

/**
 * Thin fetch wrapper: prefixes every call with {@link API_BASE_PATH}, sends
 * and expects JSON, attaches the bearer token when one is set, calls the
 * registered 401 handler, and turns an application/problem+json error
 * response into a typed {@link ProblemError} instead of a generic HTTP
 * failure.
 *
 * The frontend never derives domain state itself — every mutation is a
 * command through this client, and every button is enabled only by the
 * `available_actions` the backend returns (D12).
 */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: `${PROBLEM_JSON_CONTENT_TYPE}, application/json`,
    ...(init.headers as Record<string, string> | undefined),
  };
  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }

  const response = await fetch(`${API_BASE_PATH}${path}`, {
    ...init,
    headers,
  });

  if (response.status === 401) {
    unauthorizedHandler?.();
  }

  if (!response.ok) {
    const contentType = response.headers.get('content-type') ?? '';
    if (contentType.includes(PROBLEM_JSON_CONTENT_TYPE)) {
      const problem = (await response.json()) as ProblemDetails;
      throw new ProblemError(problem, response.status);
    }
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
