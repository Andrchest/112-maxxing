import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiFetch, ProblemError, setAuthToken, setUnauthorizedHandler } from './api';

describe('apiFetch', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setAuthToken(null);
    setUnauthorizedHandler(null);
  });

  it('turns a problem+json 409 response into a ProblemError carrying code', async () => {
    const problemBody = {
      type: 'about:blank',
      title: 'Conflict',
      status: 409,
      detail: 'Session already started.',
      code: 'SESSION_ALREADY_STARTED',
    };

    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify(problemBody), {
          status: 409,
          headers: { 'content-type': 'application/problem+json' },
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    let caught: unknown;
    try {
      await apiFetch('/sessions/1/start', { method: 'POST' });
    } catch (err) {
      caught = err;
    }

    expect(caught).toBeInstanceOf(ProblemError);
    const problemErr = caught as ProblemError;
    expect(problemErr.code).toBe('SESSION_ALREADY_STARTED');
    expect(problemErr.status).toBe(409);
    expect(problemErr.title).toBe('Conflict');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/sessions/1/start',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('resolves the parsed JSON body on success', async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiFetch('/health')).resolves.toEqual({ ok: true });
  });

  it('injects the bearer token set by setAuthToken', async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    );
    vi.stubGlobal('fetch', fetchMock);
    setAuthToken('the-jwt');

    await apiFetch('/sessions');

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer the-jwt');
  });

  it('sends no Authorization header when no token is set', async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await apiFetch('/sessions');

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('calls the registered unauthorized handler on a 401 response', async () => {
    const problemBody = {
      title: 'Unauthorized',
      status: 401,
      code: 'UNAUTHENTICATED',
    };
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify(problemBody), {
          status: 401,
          headers: { 'content-type': 'application/problem+json' },
        }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);

    await expect(apiFetch('/auth/me')).rejects.toBeInstanceOf(ProblemError);

    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });
});
