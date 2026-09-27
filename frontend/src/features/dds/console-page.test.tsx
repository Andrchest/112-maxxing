import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DdsConsolePage } from './console-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore, useSessionEventsStore } from '@/entities/session';
import { useWorkItemStore } from '@/entities/work-item';
import { useResourceStore } from '@/entities/resource';
import { useNotificationStore } from '@/entities/notification';
import { useRadioStore } from '@/entities/radio';
import { ACTIONS_BY_DDS_STAGE_STATE, makeWorkItem, makeResource, makeLeg } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

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

function makeSnapshot(overrides: Record<string, unknown> = {}, sessionOverrides: Record<string, unknown> = {}) {
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
      role_chain: ['DDS'],
      stages: [],
      active_role_stage_id: 'stage-dds-1',
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
      // I3 E5c: `console-page.tsx` reads `session.variants.dds_mode` to pick the memo/picker
      // layout — every existing test here exercises the `RESOURCE_PICKER` resource-board flow.
      variants: { card_source: 'CALLER_VOICE', dds_mode: 'RESOURCE_PICKER', dds_card_check: 'OFF', dds_brigade_call: 'OFF' },
      ...sessionOverrides,
    },
    my_role_type: 'DDS',
    active_role_stage_id: 'stage-dds-1',
    active_role_type: 'DDS',
    stage_state: 'RECEIVED',
    available_actions: ACTIONS_BY_DDS_STAGE_STATE.RECEIVED,
    card: null,
    work_item: makeWorkItem(),
    call_state: { call_id: null, room_name: null, phase: 'NO_CALL', caller_display_ru: null, started_at_offset_ms: null, answered_at_offset_ms: null, ended_at_offset_ms: null, duration_ms: null, caller_speaking: false },
    last_seq_no: 3,
    visible_sources: ['HANDOFF_SNAPSHOT', 'DDS_ASSIGNMENT', 'RESOURCE_BOARD', 'NOTIFICATIONS', 'RADIO_MESSAGES'],
    server_time_utc: '2026-09-21T10:00:00Z',
    ...overrides,
  };
}

function signIn(): void {
  useAuthStore.setState({
    token: 'jwt-token',
    isAuthenticated: true,
    user: { id: 'u1', username: 'trainee2', display_name_ru: 'Trainee', user_role: 'TRAINEE', created_at: '2026-09-21T00:00:00Z' },
  });
}

function renderConsole(sessionId = 'sess-1') {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/dds/${sessionId}`]}>
        <Routes>
          <Route path="/dds/:sessionId" element={<DdsConsolePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function stubFetchByPath(handlers: Record<string, () => Response>): ReturnType<typeof vi.fn> {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    for (const [suffix, handler] of Object.entries(handlers)) {
      if (url.endsWith(suffix)) return handler();
    }
    throw new Error(`unexpected fetch: ${url}`);
  });
}

describe('DdsConsolePage — refresh restore (SPEC §39, §42 test 13)', () => {
  afterEach(() => {
    useWorkItemStore.getState().reset();
    useResourceStore.getState().reset();
    useNotificationStore.getState().reset();
    useRadioStore.getState().reset();
    useSessionEventsStore.getState().reset('none', 0);
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
    vi.unstubAllGlobals();
  });

  it.each(['RECEIVED', 'ACKNOWLEDGED', 'RESOURCE_SELECTION', 'DISPATCHED', 'EN_ROUTE', 'ARRIVED', 'WORKING', 'RESOLVED', 'CLOSED'] as const)(
    'GET snapshot -> hydrates the work item and resources for stage_state %s',
    async (stageState) => {
      signIn();
      vi.stubGlobal('WebSocket', InertSocket);
      vi.stubGlobal(
        'fetch',
        stubFetchByPath({
          '/snapshot': () => jsonResponse(makeSnapshot({ stage_state: stageState, available_actions: ACTIONS_BY_DDS_STAGE_STATE[stageState], work_item: makeWorkItem({ state: stageState }) })),
          '/dds/resources': () => jsonResponse({ items: [makeResource()], total: 1 }),
        }),
      );

      renderConsole();

      await waitFor(() => expect(useWorkItemStore.getState().workItem?.state).toBe(stageState));
      await waitFor(() => expect(useResourceStore.getState().resources).toHaveLength(1));
      expect(await screen.findByText(ru.ddsWorkItemTitle)).toBeInTheDocument();
    },
  );

  // I6: the «Выйти» button must be available on every authenticated page — this trainee console
  // renders it exactly once (via AppShell, not a per-page usage) and clicking it clears the session.
  it('shows the logout button exactly once and logs the trainee out on click', async () => {
    signIn();
    vi.stubGlobal('WebSocket', InertSocket);
    vi.stubGlobal(
      'fetch',
      stubFetchByPath({
        '/snapshot': () => jsonResponse(makeSnapshot()),
        '/dds/resources': () => jsonResponse({ items: [makeResource()], total: 1 }),
      }),
    );

    renderConsole();

    expect(await screen.findByText(ru.ddsWorkItemTitle)).toBeInTheDocument();
    const logoutButtons = screen.getAllByRole('button', { name: ru.logoutButton });
    expect(logoutButtons).toHaveLength(1);

    await userEvent.setup().click(logoutButtons[0]!);
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it('shows a Russian message when the session has no DDS work item for this role', async () => {
    signIn();
    vi.stubGlobal('WebSocket', InertSocket);
    vi.stubGlobal(
      'fetch',
      stubFetchByPath({ '/snapshot': () => jsonResponse(makeSnapshot({ work_item: null })) }),
    );

    renderConsole();

    expect(await screen.findByText(ru.ddsConsoleNoWorkItem)).toBeInTheDocument();
  });

  it('re-fetches the snapshot on STAGE_STATE_CHANGED and folds RESOURCE_STATUS_CHANGED live', async () => {
    signIn();
    const sockets: InertSocket[] = [];
    class CapturingSocket extends InertSocket {
      constructor(url: string) {
        super(url);
        sockets.push(this);
      }
    }
    vi.stubGlobal('WebSocket', CapturingSocket);
    let snapshotCalls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/snapshot')) {
          snapshotCalls += 1;
          return jsonResponse(makeSnapshot());
        }
        if (url.endsWith('/dds/resources')) {
          return jsonResponse({ items: [makeResource()], total: 1 });
        }
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderConsole();

    await waitFor(() => expect(useResourceStore.getState().resources).toHaveLength(1));
    await waitFor(() => expect(sockets).toHaveLength(1));
    const socket = sockets[0]!;
    socket.onopen?.();
    socket.onmessage?.({ data: JSON.stringify({ type: 'resume_complete', replayed_count: 0, last_seq_no: 3, live: true }) });

    socket.onmessage?.({
      data: JSON.stringify({
        seq_no: 4,
        type: 'event',
        event_type: 'RESOURCE_STATUS_CHANGED',
        timestamp_utc: '2026-09-21T10:00:05.000Z',
        monotonic_offset_ms: 2000,
        payload: { resource_id: 'res-ac1', callsign: 'AC-1', previous_status: 'AVAILABLE', new_status: 'SELECTED', trigger: 'select', assignment_id: 'assign-1', source_world_event_id: null, at_offset_ms: 2000 },
        actor_type: 'TRAINEE',
        correlation_id: null,
        redacted_keys: [],
      }),
    });
    await waitFor(() => expect(useResourceStore.getState().resources[0]?.current_status).toBe('SELECTED'));

    // E10: NOTIFICATION_CREATED/RADIO_MESSAGE_CREATED must reach entities/notification and
    // entities/radio through this page's WS onEvent handler, not just through the reducers'
    // own unit tests.
    socket.onmessage?.({
      data: JSON.stringify({
        seq_no: 5,
        type: 'event',
        event_type: 'NOTIFICATION_CREATED',
        timestamp_utc: '2026-09-21T10:00:06.000Z',
        monotonic_offset_ms: 2500,
        payload: { notification_id: 'notif-live', audience_role: 'DDS', severity: 'CRITICAL', title_ru: 'Gas cylinder hazard', body_ru: 'A gas cylinder was found.', source_world_event_id: 'gas_cylinder_hazard', at_offset_ms: 2500 },
        actor_type: 'SIMULATION',
        correlation_id: null,
        redacted_keys: [],
      }),
    });
    await waitFor(() => expect(useNotificationStore.getState().items.some((item) => item.notification_id === 'notif-live')).toBe(true));

    socket.onmessage?.({
      data: JSON.stringify({
        seq_no: 6,
        type: 'event',
        event_type: 'RADIO_MESSAGE_CREATED',
        timestamp_utc: '2026-09-21T10:00:07.000Z',
        monotonic_offset_ms: 2600,
        payload: { radio_message_id: 'radio-live', from_callsign: 'AC-1', to_role: 'DDS', text_ru: 'Arrived on scene.', resource_id: 'res-ac1', source_world_event_id: null, at_offset_ms: 2600 },
        actor_type: 'SIMULATION',
        correlation_id: null,
        redacted_keys: [],
      }),
    });
    await waitFor(() => expect(useRadioStore.getState().messages.some((message) => message.radio_message_id === 'radio-live')).toBe(true));

    socket.onmessage?.({
      data: JSON.stringify({
        seq_no: 7,
        type: 'event',
        event_type: 'STAGE_STATE_CHANGED',
        timestamp_utc: '2026-09-21T10:00:06.000Z',
        monotonic_offset_ms: 3000,
        payload: { role_stage_id: 'stage-dds-1', role_type: 'DDS', previous_state: 'RECEIVED', new_state: 'ACKNOWLEDGED', trigger: 'acknowledge', fired_by_actor_type: 'TRAINEE', fired_by_user_id: 'u1', at_offset_ms: 3000 },
        actor_type: 'TRAINEE',
        correlation_id: null,
        redacted_keys: [],
      }),
    });
    await waitFor(() => expect(snapshotCalls).toBeGreaterThan(1));
  });
});

// I3 E5c's own vitest: both `dds_mode` variants render. `RESOURCE_PICKER` is already exercised
// above (the resource board/dispatch flow); this covers `MEMO_STATUSES` — the legs panel replaces
// the resource board, and the old picker UI is not fetched at all.
describe('DdsConsolePage — dds_mode: MEMO_STATUSES renders the memo workstation (70 §70.4, D16)', () => {
  afterEach(() => {
    useWorkItemStore.getState().reset();
    useResourceStore.getState().reset();
    useNotificationStore.getState().reset();
    useRadioStore.getState().reset();
    useSessionEventsStore.getState().reset('none', 0);
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
    vi.unstubAllGlobals();
  });

  it('renders LegsPanel instead of the resource board, and never calls /dds/resources', async () => {
    signIn();
    vi.stubGlobal('WebSocket', InertSocket);
    const resourcesFetch = vi.fn();
    vi.stubGlobal(
      'fetch',
      stubFetchByPath({
        '/snapshot': () =>
          jsonResponse(
            makeSnapshot(
              { available_actions: ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED, work_item: makeWorkItem({ state: 'ACKNOWLEDGED' }) },
              { variants: { card_source: 'GENERATED_CARD', dds_mode: 'MEMO_STATUSES', dds_card_check: 'OFF', dds_brigade_call: 'OFF' } },
            ),
          ),
        '/dds/legs': () => jsonResponse([makeLeg({ service_name_ru: 'Fire service' })]),
        '/dds/resources': () => {
          resourcesFetch();
          return jsonResponse({ items: [], total: 0 });
        },
        '/incidents': () => jsonResponse({ items: [], total: 0 }),
      }),
    );

    renderConsole();

    expect(await screen.findByRole('tab')).toBeInTheDocument();
    expect(await screen.findByText('Fire service')).toBeInTheDocument();
    expect(screen.queryByText(ru.ddsResourceBoardTitle)).not.toBeInTheDocument();
    expect(resourcesFetch).not.toHaveBeenCalled();
  });

  // I4 E21 (owner decision 2026-09-25): was work-item-panel's "renders the recipient services"
  // badge-row test — the memo card has no «Получатели» row, the tab bar shows each recipient.
  it('shows the recipient services as tabs of the tab bar, with no recipients badge row', async () => {
    signIn();
    vi.stubGlobal('WebSocket', InertSocket);
    vi.stubGlobal(
      'fetch',
      stubFetchByPath({
        '/snapshot': () =>
          jsonResponse(
            makeSnapshot(
              {
                available_actions: ACTIONS_BY_DDS_STAGE_STATE.ACKNOWLEDGED,
                work_item: makeWorkItem({ state: 'ACKNOWLEDGED', recipient_services: ['FIRE_RESCUE', 'AMBULANCE'] }),
              },
              { variants: { card_source: 'GENERATED_CARD', dds_mode: 'MEMO_STATUSES', dds_card_check: 'OFF', dds_brigade_call: 'OFF' } },
            ),
          ),
        '/dds/legs': () =>
          jsonResponse([
            makeLeg({ assignment_id: 'leg-fire', service_type: 'FIRE_RESCUE', service_name_ru: ru.serviceTypeFireRescue }),
            makeLeg({ assignment_id: 'leg-ambulance', service_type: 'AMBULANCE', service_name_ru: ru.serviceTypeAmbulance }),
          ]),
        '/incidents': () => jsonResponse({ items: [], total: 0 }),
      }),
    );

    renderConsole();

    const tabs = await screen.findAllByRole('tab');
    expect(tabs).toHaveLength(2);
    expect(tabs[0]).toHaveTextContent(ru.serviceTypeFireRescue);
    expect(tabs[1]).toHaveTextContent(ru.serviceTypeAmbulance);
    expect(document.querySelector('[data-slot="dds-recipients-row"]')).toBeNull();
  });
});
