import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AbortSessionButton } from './abort-session-button';
import { ru } from '@/shared/i18n/ru';
import { makeSessionDetail } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function problemResponse(code: string, status: number): Response {
  return new Response(JSON.stringify({ title: code, status, code }), { status, headers: { 'content-type': 'application/problem+json' } });
}

describe('AbortSessionButton — confirm dialog, reason required', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('disables confirm until a reason is entered, and calls abortSession once one is', async () => {
    const user = userEvent.setup();
    const onAborted = vi.fn();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/abort');
      expect(init?.method).toBe('POST');
      expect(JSON.parse(String(init?.body))).toEqual({ reason: 'Trainee unreachable' });
      return jsonResponse(makeSessionDetail({ id: 'sess-1', state: 'ABORTED' }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<AbortSessionButton sessionId="sess-1" onAborted={onAborted} />);
    await user.click(screen.getByRole('button', { name: ru.instructorAbortButton }));

    const confirmButton = await screen.findByRole('button', { name: ru.instructorAbortConfirmButton });
    expect(confirmButton).toBeDisabled();

    await user.type(screen.getByLabelText(ru.instructorAbortReasonLabel), 'Trainee unreachable');
    expect(confirmButton).not.toBeDisabled();

    await user.click(confirmButton);

    await waitFor(() => expect(onAborted).toHaveBeenCalledTimes(1));
    expect(onAborted.mock.calls[0]?.[0]).toMatchObject({ state: 'ABORTED' });
    // the dialog closes on success
    expect(screen.queryByRole('button', { name: ru.instructorAbortConfirmButton })).not.toBeInTheDocument();
  });

  it('shows a whitespace-only reason as not given, without calling abortSession', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    render(<AbortSessionButton sessionId="sess-1" onAborted={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: ru.instructorAbortButton }));
    await user.type(screen.getByLabelText(ru.instructorAbortReasonLabel), '   ');
    // the confirm button stays disabled for a whitespace-only reason (`.trim()`)
    expect(screen.getByRole('button', { name: ru.instructorAbortConfirmButton })).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('renders the Russian problem message on a 409 and keeps the dialog open', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => problemResponse('INVALID_TRANSITION', 409)));

    render(<AbortSessionButton sessionId="sess-1" onAborted={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: ru.instructorAbortButton }));
    await user.type(screen.getByLabelText(ru.instructorAbortReasonLabel), 'reason');
    await user.click(screen.getByRole('button', { name: ru.instructorAbortConfirmButton }));

    expect(await screen.findByText(ru.problemInvalidTransition)).toBeInTheDocument();
  });

  it('cancel closes the dialog without calling abortSession', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    render(<AbortSessionButton sessionId="sess-1" onAborted={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: ru.instructorAbortButton }));
    await user.click(await screen.findByRole('button', { name: ru.instructorAbortCancelButton }));

    expect(screen.queryByRole('button', { name: ru.instructorAbortConfirmButton })).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
