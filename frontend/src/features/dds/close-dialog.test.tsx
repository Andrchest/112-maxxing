import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CloseDialog } from './close-dialog';
import { useWorkItemStore } from '@/entities/work-item';
import { ru } from '@/shared/i18n/ru';
import { ACTIONS_BY_DDS_STAGE_STATE } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

describe('CloseDialog — requires a ClosureReason', () => {
  afterEach(() => {
    useWorkItemStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('renders nothing when close is not in available_actions', () => {
    useWorkItemStore.setState({ availableActions: ACTIONS_BY_DDS_STAGE_STATE.WORKING });
    const { container } = render(<CloseDialog sessionId="sess-1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('disables confirm until a reason is chosen, and calls closeDdsIncident once one is', async () => {
    const user = userEvent.setup();
    useWorkItemStore.setState({ availableActions: ACTIONS_BY_DDS_STAGE_STATE.RESOLVED });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/dds/close');
      expect(JSON.parse(String(init?.body))).toEqual({ closure_reason: 'RESOLVED', comment_ru: null });
      return jsonResponse({
        id: 'sess-1', scenario_version_id: 'v1', scenario_slug: 'apartment-fire', scenario_version: 1,
        session_mode: 'SINGLE_ROLE', state: 'COMPLETED', session_seed: 'seed', time_scale: 1, incident_id: 'inc-1',
        role_chain: ['DDS'], stages: [], active_role_stage_id: null, participants: [], created_by_user_id: 'instr-1',
        created_at: '2026-09-21T00:00:00Z', started_at: '2026-09-21T00:00:00Z', completed_at: '2026-09-21T00:10:00Z',
        abort_reason: null, monotonic_offset_ms: 60000, last_seq_no: 20, transition_pause_seconds: 0,
        transition_continue_available_at_offset_ms: null,
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<CloseDialog sessionId="sess-1" />);
    await user.click(screen.getByRole('button', { name: ru.ddsCloseButton }));

    const confirmButton = await screen.findByRole('button', { name: ru.ddsCloseConfirmButton });
    expect(confirmButton).toBeDisabled();

    await user.selectOptions(screen.getByLabelText(ru.ddsCloseReasonLabel), 'RESOLVED');
    expect(confirmButton).not.toBeDisabled();

    await user.click(confirmButton);

    await waitFor(() => expect(useWorkItemStore.getState().sessionState).toBe('COMPLETED'));
  });
});
