import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiFetch, ProblemError } from './api';

describe('apiFetch', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
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
});
