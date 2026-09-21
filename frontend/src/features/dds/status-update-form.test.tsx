import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StatusUpdateForm } from './status-update-form';
import { useWorkItemStore } from '@/entities/work-item';
import { ru } from '@/shared/i18n/ru';
import { ACTIONS_BY_DDS_STAGE_STATE } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

describe('StatusUpdateForm — send_status_update is available in every non-terminal DDS state', () => {
  afterEach(() => {
    useWorkItemStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('renders nothing when send_status_update is not in available_actions', () => {
    useWorkItemStore.setState({ availableActions: ACTIONS_BY_DDS_STAGE_STATE.RECEIVED });
    const { container } = render(<StatusUpdateForm sessionId="sess-1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each(['ACKNOWLEDGED', 'RESOURCE_SELECTION', 'DISPATCHED', 'EN_ROUTE', 'ARRIVED', 'WORKING', 'RESOLVED'] as const)(
    'renders the form in %s',
    (stageState) => {
      useWorkItemStore.setState({ availableActions: ACTIONS_BY_DDS_STAGE_STATE[stageState] });
      render(<StatusUpdateForm sessionId="sess-1" />);
      expect(screen.getByText(ru.ddsStatusUpdateTitle)).toBeInTheDocument();
    },
  );

  it('submits the chosen kind and text and clears the field on success', async () => {
    const user = userEvent.setup();
    useWorkItemStore.setState({ availableActions: ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/dds/status-updates');
      expect(JSON.parse(String(init?.body))).toEqual({ update_kind: 'SITUATION_UPDATE', text_ru: 'Situation stable' });
      return jsonResponse({ assignment_id: 'assign-1', update_kind: 'SITUATION_UPDATE', text_ru: 'Situation stable', at_offset_ms: 1000, actor_user_id: 'u1' }, 201);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<StatusUpdateForm sessionId="sess-1" />);
    await user.type(screen.getByLabelText(ru.ddsStatusUpdateTextLabel), 'Situation stable');
    await user.click(screen.getByRole('button', { name: ru.ddsStatusUpdateSubmit }));

    await waitFor(() => expect(screen.getByLabelText(ru.ddsStatusUpdateTextLabel)).toHaveValue(''));
  });
});
