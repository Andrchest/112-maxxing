import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PhoneWidget } from './phone-widget';
import { ru } from '@/shared/i18n/ru';
import { useCallStateStore } from '@/entities/session';
import { useStageStore } from '@/entities/stage';
import { ACTIONS_BY_STAGE_STATE, makeCallState, makeCard } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

describe('PhoneWidget — one state per CallStateView.phase (D12 design decision #3)', () => {
  afterEach(() => {
    useCallStateStore.setState({ callState: null });
    useStageStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('NO_CALL: no answer/hang-up button, no timer', () => {
    useCallStateStore.setState({ callState: makeCallState({ phase: 'NO_CALL' }) });
    useStageStore.setState({ availableActions: [] });

    render(<PhoneWidget sessionId="sess-1" />);

    expect(screen.queryByRole('button', { name: /answer/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/^\d{2}:\d{2}$/)).not.toBeInTheDocument();
  });

  it('RINGING: shows the ringing indicator and the server-labelled answer button only when available_actions offers it', () => {
    useCallStateStore.setState({ callState: makeCallState({ phase: 'RINGING', caller_display_ru: 'Caller X' }) });
    useStageStore.setState({ availableActions: ACTIONS_BY_STAGE_STATE.RINGING });

    render(<PhoneWidget sessionId="sess-1" />);

    expect(screen.getByRole('button', { name: 'Answer' })).toBeInTheDocument();
    expect(screen.getByText('Caller X')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /end call/i })).not.toBeInTheDocument();
  });

  it('CONNECTED: shows the call timer and the hang-up button', () => {
    useCallStateStore.setState({ callState: makeCallState({ phase: 'CONNECTED', answered_at_offset_ms: 1000 }) });
    useStageStore.setState({ availableActions: ACTIONS_BY_STAGE_STATE.CONNECTED });

    render(<PhoneWidget sessionId="sess-1" />);

    expect(screen.getByRole('button', { name: 'End call' })).toBeInTheDocument();
    expect(screen.getByText(/^\d{2}:\d{2}$/)).toBeInTheDocument();
  });

  it('ENDED: shows the final duration, no action buttons', () => {
    useCallStateStore.setState({ callState: makeCallState({ phase: 'ENDED', duration_ms: 65_000 }) });
    useStageStore.setState({ availableActions: [] });

    render(<PhoneWidget sessionId="sess-1" />);

    expect(screen.getByText('01:05')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /answer/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /end call/i })).not.toBeInTheDocument();
  });

  it('caller_speaking renders the speaking indicator', () => {
    useCallStateStore.setState({ callState: makeCallState({ phase: 'CONNECTED', caller_speaking: true }) });
    useStageStore.setState({ availableActions: [] });

    render(<PhoneWidget sessionId="sess-1" />);

    expect(screen.getByText(ru.operatorCallerSpeaking)).toBeInTheDocument();
  });

  it('answering calls answerCall and replaces stage/card/call state from the response', async () => {
    const user = userEvent.setup();
    useCallStateStore.setState({ callState: makeCallState({ phase: 'RINGING' }) });
    useStageStore.setState({ availableActions: ACTIONS_BY_STAGE_STATE.RINGING });

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/operator/call/answer');
      return jsonResponse({
        role_stage_id: 'stage-1',
        stage_state: 'CONNECTED',
        available_actions: ACTIONS_BY_STAGE_STATE.CONNECTED,
        card: makeCard(),
        call_state: makeCallState({ phase: 'CONNECTED', answered_at_offset_ms: 500 }),
        session_state: 'ACTIVE',
        last_seq_no: 5,
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<PhoneWidget sessionId="sess-1" />);
    await user.click(screen.getByRole('button', { name: 'Answer' }));

    await waitFor(() => expect(useCallStateStore.getState().callState?.phase).toBe('CONNECTED'));
    expect(useStageStore.getState().stageState).toBe('CONNECTED');
  });
});
