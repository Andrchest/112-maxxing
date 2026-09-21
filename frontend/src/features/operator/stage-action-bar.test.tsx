import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StageActionBar } from './stage-action-bar';
import { useStageStore } from '@/entities/stage';
import { ru } from '@/shared/i18n/ru';
import { ACTIONS_BY_STAGE_STATE, makeCard, makeCallState } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function seedStage(stageState: keyof typeof ACTIONS_BY_STAGE_STATE): void {
  useStageStore.setState({
    roleStageId: 'stage-1',
    stageState: stageState as never,
    availableActions: ACTIONS_BY_STAGE_STATE[stageState],
    sessionState: 'ACTIVE',
    lastSeqNo: 1,
  });
}

describe('StageActionBar — buttons strictly follow available_actions', () => {
  afterEach(() => {
    useStageStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it.each(['WAITING_FOR_CALL', 'RINGING', 'CONNECTED', 'STAGE_COMPLETED'] as const)(
    'renders no bar buttons in %s (answer/end_call/edit_card/select_services are not bar buttons)',
    (stageState) => {
      seedStage(stageState);
      render(<StageActionBar sessionId="sess-1" />);
      expect(screen.queryByRole('button')).not.toBeInTheDocument();
    },
  );

  it('renders "open_handoff_preparation" in INTERVIEW, nothing else', () => {
    seedStage('INTERVIEW');
    render(<StageActionBar sessionId="sess-1" />);
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(1);
    expect(buttons[0]).toHaveTextContent('Prepare handoff');
  });

  it('renders "back_to_interview" and "create_handoff" in HANDOFF_PREPARATION', () => {
    seedStage('HANDOFF_PREPARATION');
    render(<StageActionBar sessionId="sess-1" />);
    expect(screen.getByRole('button', { name: 'Back to interview' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create handoff' })).toBeInTheDocument();
  });

  it('renders "complete_stage" in HANDED_OFF', () => {
    seedStage('HANDED_OFF');
    render(<StageActionBar sessionId="sess-1" />);
    expect(screen.getByRole('button', { name: 'Complete stage' })).toBeInTheDocument();
  });

  it('clicking back_to_interview calls the command and replaces the stage/card/call state wholesale', async () => {
    const user = userEvent.setup();
    seedStage('HANDOFF_PREPARATION');
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/operator/handoff/cancel');
      return jsonResponse({
        role_stage_id: 'stage-1',
        stage_state: 'INTERVIEW',
        available_actions: ACTIONS_BY_STAGE_STATE.INTERVIEW,
        card: makeCard(),
        call_state: makeCallState({ phase: 'CONNECTED' }),
        session_state: 'ACTIVE',
        last_seq_no: 2,
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<StageActionBar sessionId="sess-1" />);
    await user.click(screen.getByRole('button', { name: 'Back to interview' }));

    await waitFor(() => expect(useStageStore.getState().stageState).toBe('INTERVIEW'));
  });

  it('clicking create_handoff opens a comment dialog, then calls createHandoff and onCommandNeedsRefresh (E10)', async () => {
    const user = userEvent.setup();
    seedStage('HANDOFF_PREPARATION');
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/operator/handoff');
      expect(JSON.parse(String(init?.body))).toEqual({ comment_ru: 'Priority call' });
      return jsonResponse(
        {
          snapshot: {
            snapshot_id: 'snap-1', incident_id: 'inc-1', card_id: 'card-1', card_revision_id: 'rev-1',
            card_values: {}, recipient_services: ['FIRE_RESCUE'], created_by_user_id: 'u1',
            created_at_offset_ms: 1000, content_sha256: 'sha',
          },
          assignment_ids: ['assign-1'],
          stage_state: 'HANDED_OFF',
          session_state: 'ACTIVE',
        },
        201,
      );
    });
    vi.stubGlobal('fetch', fetchMock);
    const onCommandNeedsRefresh = vi.fn();

    render(<StageActionBar sessionId="sess-1" onCommandNeedsRefresh={onCommandNeedsRefresh} />);
    await user.click(screen.getByRole('button', { name: 'Create handoff' }));
    await user.type(await screen.findByLabelText(ru.operatorHandoffCommentLabel), 'Priority call');
    await user.click(screen.getByRole('button', { name: ru.operatorCreateHandoffConfirmButton }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await waitFor(() => expect(onCommandNeedsRefresh).toHaveBeenCalledTimes(1));
  });

  it('clicking complete_stage calls completeOperatorStage and onCommandNeedsRefresh (E10)', async () => {
    const user = userEvent.setup();
    seedStage('HANDED_OFF');
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/operator/stage/complete');
      return jsonResponse({
        id: 'sess-1', scenario_version_id: 'v1', scenario_slug: 'apartment-fire', scenario_version: 1,
        session_mode: 'FULL_CYCLE_SINGLE_TRAINEE', state: 'ROLE_TRANSITION', session_seed: 'seed', time_scale: 1,
        incident_id: 'inc-1', role_chain: ['OPERATOR_112', 'DDS'], stages: [], active_role_stage_id: null,
        participants: [], created_by_user_id: 'instr-1', created_at: '2026-09-21T00:00:00Z',
        started_at: '2026-09-21T00:00:00Z', completed_at: null, abort_reason: null, monotonic_offset_ms: 60000,
        last_seq_no: 12, transition_pause_seconds: 20, transition_continue_available_at_offset_ms: 80000,
      });
    });
    vi.stubGlobal('fetch', fetchMock);
    const onCommandNeedsRefresh = vi.fn();

    render(<StageActionBar sessionId="sess-1" onCommandNeedsRefresh={onCommandNeedsRefresh} />);
    await user.click(screen.getByRole('button', { name: 'Complete stage' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await waitFor(() => expect(onCommandNeedsRefresh).toHaveBeenCalledTimes(1));
  });
});
