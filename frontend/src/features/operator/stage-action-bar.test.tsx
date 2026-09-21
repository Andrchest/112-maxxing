import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StageActionBar } from './stage-action-bar';
import { useStageStore } from '@/entities/stage';
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

  it('clicking create_handoff shows the TODO(E10) toast instead of calling a command', async () => {
    const user = userEvent.setup();
    seedStage('HANDOFF_PREPARATION');
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    render(<StageActionBar sessionId="sess-1" />);
    await user.click(screen.getByRole('button', { name: 'Create handoff' }));

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
