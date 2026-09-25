import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CommentsSection } from './comments-section';
import { ru } from '@/shared/i18n/ru';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function problemResponse(code: string, status: number): Response {
  return new Response(JSON.stringify({ title: code, status, code }), { status, headers: { 'content-type': 'application/problem+json' } });
}

function renderSection(props: { sessionId?: string; canManage?: boolean } = {}) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <CommentsSection sessionId={props.sessionId ?? 'sess-1'} canManage={props.canManage ?? false} />
    </QueryClientProvider>,
  );
}

const COMMENT_1 = {
  comment_id: 'c-1',
  session_id: 'sess-1',
  lesson_id: null,
  author_user_id: 'u-1',
  author_display_name_ru: 'Instructor One',
  text: 'Good work on the card.',
  created_at: '2026-09-21T00:11:00Z',
  replaces_comment_id: null,
  superseded: false,
};

// I4 E32 (HLD 71 §71.9): «Комментарии преподавателя» (instructor feedback on a result).
describe('CommentsSection', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows the empty state when there are no comments', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [] })));
    renderSection();
    expect(await screen.findByText(ru.reportCommentsEmpty)).toBeInTheDocument();
  });

  it('renders a comment, its author and timestamp', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [COMMENT_1] })));
    renderSection();
    expect(await screen.findByText('Good work on the card.')).toBeInTheDocument();
    expect(screen.getByText('Instructor One')).toBeInTheDocument();
  });

  it('marks a superseded comment', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [{ ...COMMENT_1, superseded: true }] })));
    renderSection();
    expect(await screen.findByText(ru.reportCommentsSupersededBadge)).toBeInTheDocument();
  });

  it('403 REPORT_NOT_RELEASED renders the mapped problem message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => problemResponse('REPORT_NOT_RELEASED', 403)));
    renderSection();
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
  });

  it('shows no add form for a trainee (canManage false)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [] })));
    renderSection({ canManage: false });
    await screen.findByText(ru.reportCommentsEmpty);
    expect(screen.queryByRole('button', { name: ru.reportCommentsAddButton })).not.toBeInTheDocument();
  });

  it('an instructor posts a new comment with replaces_comment_id: null', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') {
        expect(String(input)).toBe('/api/v1/reports/sess-1/comments');
        expect(JSON.parse(String(init.body))).toEqual({ text: 'A new comment', replaces_comment_id: null });
        return jsonResponse({ ...COMMENT_1, comment_id: 'c-2', text: 'A new comment' }, 201);
      }
      return jsonResponse({ items: [] });
    });
    vi.stubGlobal('fetch', fetchMock);

    renderSection({ canManage: true });
    await screen.findByText(ru.reportCommentsEmpty);

    await user.type(screen.getByPlaceholderText(ru.reportCommentsAddPlaceholder), 'A new comment');
    await user.click(screen.getByRole('button', { name: ru.reportCommentsAddButton }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/reports/sess-1/comments', expect.objectContaining({ method: 'POST' })));
  });

  it('editing a comment posts with its comment_id as replaces_comment_id', async () => {
    const user = userEvent.setup();
    let postBody: unknown = null;
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') {
        postBody = JSON.parse(String(init.body));
        return jsonResponse({ ...COMMENT_1, comment_id: 'c-2', text: 'Fixed text', replaces_comment_id: 'c-1' }, 201);
      }
      return jsonResponse({ items: [COMMENT_1] });
    });
    vi.stubGlobal('fetch', fetchMock);

    renderSection({ canManage: true });
    await screen.findByText('Good work on the card.');

    await user.click(screen.getByRole('button', { name: ru.reportCommentsEditButton }));
    const textarea = screen.getByPlaceholderText(ru.reportCommentsAddPlaceholder);
    expect(textarea).toHaveValue('Good work on the card.');
    await user.clear(textarea);
    await user.type(textarea, 'Fixed text');
    await user.click(screen.getByRole('button', { name: ru.reportCommentsAddButton }));

    await waitFor(() => expect(postBody).toEqual({ text: 'Fixed text', replaces_comment_id: 'c-1' }));
  });
});
