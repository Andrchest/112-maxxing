import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StageActionBar } from './stage-action-bar';
import { useWorkItemStore } from '@/entities/work-item';
import { ACTIONS_BY_DDS_STAGE_STATE, makeWorkItem } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

describe('StageActionBar — buttons strictly follow available_actions', () => {
  afterEach(() => {
    useWorkItemStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('renders "acknowledge" in RECEIVED', () => {
    useWorkItemStore.setState({ availableActions: ACTIONS_BY_DDS_STAGE_STATE.RECEIVED });
    render(<StageActionBar sessionId="sess-1" />);
    expect(screen.getByRole('button', { name: 'Acknowledge' })).toBeInTheDocument();
  });

  it('clicking acknowledge calls acknowledgeDdsAssignment and applies the returned DdsStageView wholesale', async () => {
    const user = userEvent.setup();
    useWorkItemStore.setState({ availableActions: ACTIONS_BY_DDS_STAGE_STATE.RECEIVED });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/dds/acknowledge');
      expect(init?.method).toBe('POST');
      expect(init?.body).toBeUndefined();
      return jsonResponse({
        role_stage_id: 'stage-dds-1',
        stage_state: 'ACKNOWLEDGED',
        available_actions: ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED,
        work_item: makeWorkItem({ state: 'ACKNOWLEDGED', acknowledged_at_offset_ms: 2000 }),
        resources: [],
        unacknowledged_notification_count: 0,
        session_state: 'ACTIVE',
        last_seq_no: 5,
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<StageActionBar sessionId="sess-1" />);
    await user.click(screen.getByRole('button', { name: 'Acknowledge' }));

    await waitFor(() => expect(useWorkItemStore.getState().workItem?.state).toBe('ACKNOWLEDGED'));
  });

  it('renders "open_resource_selection" in ACKNOWLEDGED and clicking calls the endpoint with no body', async () => {
    const user = userEvent.setup();
    useWorkItemStore.setState({ availableActions: ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/dds/resources/selection/open');
      expect(init?.method).toBe('POST');
      expect(init?.body).toBeUndefined();
      return jsonResponse({
        role_stage_id: 'stage-dds-1',
        stage_state: 'RESOURCE_SELECTION',
        available_actions: ACTIONS_BY_DDS_STAGE_STATE.RESOURCE_SELECTION,
        work_item: makeWorkItem({ state: 'RESOURCE_SELECTION' }),
        resources: [],
        unacknowledged_notification_count: 0,
        session_state: 'ACTIVE',
        last_seq_no: 6,
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<StageActionBar sessionId="sess-1" />);
    await user.click(screen.getByRole('button', { name: 'Open resource selection' }));

    await waitFor(() => expect(useWorkItemStore.getState().workItem?.state).toBe('RESOURCE_SELECTION'));
  });

  it('renders "open_resource_selection" (worded "Add more forces") again in DISPATCHED — driven only by available_actions, not a hard-coded stage list', () => {
    useWorkItemStore.setState({ availableActions: ACTIONS_BY_DDS_STAGE_STATE.DISPATCHED });
    render(<StageActionBar sessionId="sess-1" />);
    expect(screen.getByRole('button', { name: 'Add more forces' })).toBeInTheDocument();
  });

  it('does not render open_resource_selection in EN_ROUTE/ARRIVED/WORKING (dispatch_additional lives in the resource board instead)', () => {
    useWorkItemStore.setState({ availableActions: ACTIONS_BY_DDS_STAGE_STATE.EN_ROUTE });
    render(<StageActionBar sessionId="sess-1" />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('renders "back_to_acknowledged" in RESOURCE_SELECTION and clicking calls the endpoint with no body', async () => {
    const user = userEvent.setup();
    useWorkItemStore.setState({ availableActions: ACTIONS_BY_DDS_STAGE_STATE.RESOURCE_SELECTION });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/dds/resources/selection/cancel');
      expect(init?.method).toBe('POST');
      expect(init?.body).toBeUndefined();
      return jsonResponse({
        role_stage_id: 'stage-dds-1',
        stage_state: 'ACKNOWLEDGED',
        available_actions: ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED,
        work_item: makeWorkItem({ state: 'ACKNOWLEDGED' }),
        resources: [],
        unacknowledged_notification_count: 0,
        session_state: 'ACTIVE',
        last_seq_no: 7,
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<StageActionBar sessionId="sess-1" />);
    await user.click(screen.getByRole('button', { name: 'Back' }));

    await waitFor(() => expect(useWorkItemStore.getState().workItem?.state).toBe('ACKNOWLEDGED'));
  });
});
