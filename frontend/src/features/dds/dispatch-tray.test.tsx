import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DispatchTray } from './dispatch-tray';
import { useResourceStore } from '@/entities/resource';
import { useWorkItemStore } from '@/entities/work-item';
import { ru } from '@/shared/i18n/ru';
import { makeResource, makeWorkItem, ACTIONS_BY_DDS_STAGE_STATE } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

describe('DispatchTray', () => {
  afterEach(() => {
    useResourceStore.getState().reset();
    useWorkItemStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('shows the empty state when nothing is selected', () => {
    useResourceStore.getState().setResources([makeResource()]);
    useWorkItemStore.setState({ workItem: makeWorkItem({ selected_resource_ids: [] }), availableActions: ACTIONS_BY_DDS_STAGE_STATE.RESOURCE_SELECTION });
    render(<DispatchTray sessionId="sess-1" />);
    expect(screen.getByText(ru.ddsSelectionTrayEmpty)).toBeInTheDocument();
  });

  it('lists selected resources and disables dispatch until dispatch is in available_actions', () => {
    useResourceStore.getState().setResources([makeResource({ current_status: 'SELECTED' })]);
    useWorkItemStore.setState({ workItem: makeWorkItem({ selected_resource_ids: ['res-ac1'] }), availableActions: ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED });
    render(<DispatchTray sessionId="sess-1" />);
    expect(screen.getByText('AC-1')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: ru.ddsDispatchButton })).not.toBeInTheDocument();
  });

  it('clicking dispatch calls dispatchDdsResources with the note and applies the returned stage', async () => {
    const user = userEvent.setup();
    useResourceStore.getState().setResources([makeResource({ current_status: 'SELECTED' })]);
    useWorkItemStore.setState({ workItem: makeWorkItem({ selected_resource_ids: ['res-ac1'] }), availableActions: ACTIONS_BY_DDS_STAGE_STATE.RESOURCE_SELECTION });

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/dds/resources/dispatch');
      expect(JSON.parse(String(init?.body))).toEqual({ note_ru: 'First dispatch' });
      return jsonResponse({
        stage: {
          role_stage_id: 'stage-dds-1',
          stage_state: 'DISPATCHED',
          available_actions: ACTIONS_BY_DDS_STAGE_STATE.DISPATCHED,
          work_item: makeWorkItem({ state: 'DISPATCHED', selected_resource_ids: [], dispatched_resource_ids: ['res-ac1'] }),
          resources: [makeResource({ current_status: 'DISPATCHED' })],
          unacknowledged_notification_count: 0,
          session_state: 'ACTIVE',
          last_seq_no: 11,
        },
        dispatched_resource_ids: ['res-ac1'],
        eta_seconds_by_resource: { 'res-ac1': 360 },
        is_additional: false,
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<DispatchTray sessionId="sess-1" />);
    await user.type(screen.getByPlaceholderText(ru.ddsDispatchNoteLabel), 'First dispatch');
    await user.click(screen.getByRole('button', { name: ru.ddsDispatchButton }));

    await waitFor(() => expect(useWorkItemStore.getState().workItem?.dispatched_resource_ids).toEqual(['res-ac1']));
    expect(useWorkItemStore.getState().workItem?.selected_resource_ids).toEqual([]);
  });

  it('renders the live status of already-dispatched units', () => {
    useResourceStore.getState().setResources([makeResource({ current_status: 'EN_ROUTE' })]);
    useWorkItemStore.setState({ workItem: makeWorkItem({ dispatched_resource_ids: ['res-ac1'] }), availableActions: ACTIONS_BY_DDS_STAGE_STATE.EN_ROUTE });
    render(<DispatchTray sessionId="sess-1" />);
    expect(screen.getByText(ru.resourceStatusEnRoute)).toBeInTheDocument();
  });
});
