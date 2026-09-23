import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ResourceBoard } from './resource-board';
import { useResourceStore } from '@/entities/resource';
import { useWorkItemStore } from '@/entities/work-item';
import { ru } from '@/shared/i18n/ru';
import { makeResource, makeWorkItem, ACTIONS_BY_DDS_STAGE_STATE } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function seed(resources = [makeResource()], availableActions = ACTIONS_BY_DDS_STAGE_STATE.RESOURCE_SELECTION): void {
  useResourceStore.getState().setResources(resources);
  useWorkItemStore.setState({ availableActions, workItem: makeWorkItem({ state: 'RESOURCE_SELECTION' }) });
}

describe('ResourceBoard — action gating strictly from available_actions', () => {
  afterEach(() => {
    useResourceStore.getState().reset();
    useWorkItemStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('renders resources grouped by service with capabilities and status', () => {
    seed();
    render(<ResourceBoard sessionId="sess-1" />);
    expect(screen.getByText(ru.serviceTypeFireRescue)).toBeInTheDocument();
    expect(screen.getByText(/AC-1/)).toBeInTheDocument();
    expect(screen.getByText(ru.resourceStatusAvailable)).toBeInTheDocument();
    expect(screen.getByText(ru.resourceCapabilityFireSuppression)).toBeInTheDocument();
  });

  it('does not render a select button (or the "not selectable" hint) when select_resource is not in available_actions (D13)', () => {
    seed([makeResource()], ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED);
    render(<ResourceBoard sessionId="sess-1" />);
    expect(screen.queryByRole('button', { name: ru.ddsSelectButton })).not.toBeInTheDocument();
    expect(screen.queryByText(ru.ddsNotSelectableHint)).not.toBeInTheDocument();
  });

  it('disables select when selectable is false, regardless of available_actions', () => {
    seed([makeResource({ selectable: false })]);
    render(<ResourceBoard sessionId="sess-1" />);
    expect(screen.getByRole('button', { name: ru.ddsSelectButton })).toBeDisabled();
    expect(screen.getByText(ru.ddsNotSelectableHint)).toBeInTheDocument();
  });

  it('clicking select calls selectDdsResource and applies the returned DdsStageView wholesale', async () => {
    const user = userEvent.setup();
    seed();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/dds/resources/select');
      return jsonResponse({
        role_stage_id: 'stage-dds-1',
        stage_state: 'RESOURCE_SELECTION',
        available_actions: ACTIONS_BY_DDS_STAGE_STATE.RESOURCE_SELECTION,
        work_item: makeWorkItem({ state: 'RESOURCE_SELECTION', selected_resource_ids: ['res-ac1'] }),
        resources: [makeResource({ current_status: 'SELECTED' })],
        unacknowledged_notification_count: 0,
        session_state: 'ACTIVE',
        last_seq_no: 10,
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<ResourceBoard sessionId="sess-1" />);
    await user.click(screen.getByRole('button', { name: ru.ddsSelectButton }));

    await waitFor(() => expect(screen.getByText(ru.resourceStatusSelected)).toBeInTheDocument());
    expect(useWorkItemStore.getState().workItem?.selected_resource_ids).toEqual(['res-ac1']);
  });

  it('renders a deselect button for a SELECTED resource, not a select button', () => {
    seed([makeResource({ current_status: 'SELECTED' })]);
    render(<ResourceBoard sessionId="sess-1" />);
    expect(screen.getByRole('button', { name: ru.ddsDeselectButton })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: ru.ddsSelectButton })).not.toBeInTheDocument();
  });

  // Manager ruling (E10 brief): select_resource/deselect_resource are ALSO available in
  // EN_ROUTE/ARRIVED/WORKING (additional dispatch) — never hard-coded to RESOURCE_SELECTION only.
  it.each(['EN_ROUTE', 'ARRIVED', 'WORKING'] as const)('enables select in %s, driven only by available_actions', (stageState) => {
    seed([makeResource()], ACTIONS_BY_DDS_STAGE_STATE[stageState]);
    render(<ResourceBoard sessionId="sess-1" />);
    expect(screen.getByRole('button', { name: ru.ddsSelectButton })).not.toBeDisabled();
  });
});
