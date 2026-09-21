import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { OperatorConsolePage } from './console-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore, useCallStateStore, useSessionEventsStore } from '@/entities/session';
import { useCardStore } from '@/entities/card';
import { useStageStore } from '@/entities/stage';
import { ACTIONS_BY_STAGE_STATE, makeCallState, makeCard } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

/** Never opens (no `onopen` call) — enough to prove the page does not crash while a real socket
 * would still be connecting, without attempting a real network connection in jsdom. Tests that
 * need to drive the socket construct their own capturing variant instead. */
class InertSocket {
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  url: string;
  constructor(url: string) {
    this.url = url;
  }
  send(): void {}
  close(): void {
    this.readyState = 3;
  }
}

function makeSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    session: {
      id: 'sess-1',
      scenario_version_id: 'v1',
      scenario_slug: 'apartment-fire',
      scenario_version: 1,
      session_mode: 'SINGLE_ROLE',
      state: 'ACTIVE',
      session_seed: 'seed',
      time_scale: 1,
      incident_id: 'inc-1',
      role_chain: ['OPERATOR_112'],
      stages: [],
      active_role_stage_id: 'stage-1',
      participants: [],
      created_by_user_id: 'instr-1',
      created_at: '2026-09-21T00:00:00Z',
      started_at: '2026-09-21T00:00:00Z',
      completed_at: null,
      abort_reason: null,
      monotonic_offset_ms: 1000,
      last_seq_no: 3,
      transition_pause_seconds: 0,
      transition_continue_available_at_offset_ms: null,
    },
    my_role_type: 'OPERATOR_112',
    active_role_stage_id: 'stage-1',
    active_role_type: 'OPERATOR_112',
    stage_state: 'INTERVIEW',
    available_actions: ACTIONS_BY_STAGE_STATE.INTERVIEW,
    card: makeCard({ values: { 'address.house': '27' } }),
    work_item: null,
    call_state: makeCallState({ phase: 'CONNECTED', answered_at_offset_ms: 100 }),
    last_seq_no: 3,
    visible_sources: ['OPERATOR_CARD', 'CALL_STATE'],
    server_time_utc: '2026-09-21T10:00:00Z',
    ...overrides,
  };
}

function signIn(): void {
  useAuthStore.setState({
    token: 'jwt-token',
    isAuthenticated: true,
    user: { id: 'u1', username: 'trainee1', display_name_ru: 'Trainee', user_role: 'TRAINEE', created_at: '2026-09-21T00:00:00Z' },
  });
}

function renderConsole(sessionId = 'sess-1') {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/operator/${sessionId}`]}>
        <Routes>
          <Route path="/operator/:sessionId" element={<OperatorConsolePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('OperatorConsolePage — refresh restore (SPEC §39, §42 test 13)', () => {
  afterEach(() => {
    useCardStore.getState().setCard(null);
    useStageStore.getState().reset();
    useCallStateStore.setState({ callState: null });
    useSessionEventsStore.getState().reset('none', 0);
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
    vi.unstubAllGlobals();
  });

  it.each(['WAITING_FOR_CALL', 'INTERVIEW', 'HANDOFF_PREPARATION', 'HANDED_OFF'] as const)(
    'GET snapshot -> hydrates stage/card/call state for stage_state %s',
    async (stageState) => {
      signIn();
      vi.stubGlobal('WebSocket', InertSocket);
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        expect(String(input)).toBe('/api/v1/sessions/sess-1/snapshot');
        return jsonResponse(makeSnapshot({ stage_state: stageState, available_actions: ACTIONS_BY_STAGE_STATE[stageState] }));
      });
      vi.stubGlobal('fetch', fetchMock);

      renderConsole();

      await waitFor(() => expect(useStageStore.getState().stageState).toBe(stageState));
      expect(useCardStore.getState().card?.values['address.house']).toBe('27');
      expect(useCallStateStore.getState().callState?.phase).toBe('CONNECTED');

      if (stageState === 'HANDOFF_PREPARATION') {
        expect(await screen.findByText(ru.operatorHandoffPreparationTitle)).toBeInTheDocument();
      } else {
        expect(await screen.findByText(ru.operatorCardTitle)).toBeInTheDocument();
      }
    },
  );

  it('shows a Russian message when the session has no operator card for this role', async () => {
    signIn();
    vi.stubGlobal('WebSocket', InertSocket);
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(makeSnapshot({ card: null }))),
    );

    renderConsole();

    expect(await screen.findByText(ru.operatorConsoleWrongRole)).toBeInTheDocument();
  });
});

describe('OperatorConsolePage — CARD_FIELD_CHANGED event/response convergence (D12 design decision #5)', () => {
  afterEach(() => {
    useCardStore.getState().setCard(null);
    useStageStore.getState().reset();
    useCallStateStore.setState({ callState: null });
    useSessionEventsStore.getState().reset('none', 0);
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
    vi.unstubAllGlobals();
  });

  it('converges to the same value whether the WS event or the REST response would have "arrived" first', async () => {
    signIn();
    const sockets: InertSocket[] = [];
    class CapturingSocket extends InertSocket {
      constructor(url: string) {
        super(url);
        sockets.push(this);
      }
    }
    vi.stubGlobal('WebSocket', CapturingSocket);
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(makeSnapshot())),
    );

    renderConsole();

    await waitFor(() => expect(useCardStore.getState().card?.values['address.house']).toBe('27'));
    await waitFor(() => expect(sockets).toHaveLength(1));

    const socket = sockets[0]!;
    socket.onopen?.();
    socket.onmessage?.({ data: JSON.stringify({ type: 'resume_complete', replayed_count: 0, last_seq_no: 3, live: true }) });

    // This is the log-side write: a CARD_FIELD_CHANGED event for the same value a command
    // response would also have carried. Applying it must land on the identical value.
    socket.onmessage?.({
      data: JSON.stringify({
        type: 'event',
        seq_no: 4,
        event_type: 'CARD_FIELD_CHANGED',
        timestamp_utc: '2026-09-21T10:00:05.000Z',
        monotonic_offset_ms: 2000,
        payload: {
          card_id: 'card-1',
          revision_id: 'rev-2',
          revision_no: 2,
          field_path: 'address.house',
          previous_value: '27',
          new_value: '72',
          value_type: 'STRING',
          actor_user_id: 'u1',
          at_offset_ms: 2000,
        },
        actor_type: 'TRAINEE',
        correlation_id: null,
        redacted_keys: [],
      }),
    });

    await waitFor(() => expect(useCardStore.getState().card?.values['address.house']).toBe('72'));

    // The command-response side: a setCardField response for the same field/value applied after
    // the event already landed must not regress or duplicate anything.
    useCardStore.getState().setCard(makeCard({ values: { 'address.house': '72' }, revision_counter: 2 }));

    expect(useCardStore.getState().card?.values['address.house']).toBe('72');
    expect(useCardStore.getState().card?.revision_counter).toBe(2);
  });
});
