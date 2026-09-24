import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CardIssueButton } from './card-issue-button';
import { useWorkItemStore } from '@/entities/work-item';
import { ru } from '@/shared/i18n/ru';
import { ACTIONS_BY_DDS_STAGE_STATE, makeLeg } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function renderButton(sessionId = 'sess-1') {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <CardIssueButton sessionId={sessionId} />
    </QueryClientProvider>,
  );
}

describe('CardIssueButton — flag_card_issue, dds_card_check: ON only (70 par.70.4.4)', () => {
  afterEach(() => {
    useWorkItemStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('renders nothing when flag_card_issue is not in available_actions', () => {
    useWorkItemStore.setState({ availableActions: ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED });
    const { container } = renderButton();
    expect(container).toBeEmptyDOMElement();
  });

  it('requires a comment client-side, and posts assignment_id/issue_kind/comment_ru once given one', async () => {
    const user = userEvent.setup();
    useWorkItemStore.setState({
      availableActions: [
        ...ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED,
        { action_id: 'flag_card_issue', label_ru: 'Flag card issue', permission: 'FLAG_CARD_ISSUE', trigger: 'flag_card_issue' },
      ],
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/dds/legs')) {
        return jsonResponse([makeLeg({ assignment_id: 'a1', service_name_ru: 'Fire service' })]);
      }
      if (url.endsWith('/dds/card-issues')) {
        expect(JSON.parse(String(init?.body))).toEqual({
          assignment_id: 'a1',
          issue_kind: 'WRONG',
          field_path: null,
          comment_ru: 'Wrong address',
        });
        return jsonResponse({ event_id: 'issue-1', assignment_id: 'a1', field_path: null, issue_kind: 'WRONG', comment_ru: 'Wrong address', at_offset_ms: 1000 }, 201);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderButton();
    await user.click(screen.getByRole('button', { name: ru.ddsCardIssueButton }));
    await user.selectOptions(await screen.findByLabelText(ru.ddsCardIssueServiceLabel), 'a1');

    const submit = screen.getByRole('button', { name: ru.ddsCardIssueSubmitButton });
    await user.click(submit);
    expect(await screen.findByText(ru.ddsCardIssueCommentRequiredNotice)).toBeInTheDocument();

    await user.type(screen.getByLabelText(ru.ddsCardIssueCommentLabel), 'Wrong address');
    await user.click(submit);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/sessions/sess-1/dds/card-issues', expect.anything()));
  });
});
