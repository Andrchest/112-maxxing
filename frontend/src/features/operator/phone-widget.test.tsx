import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PhoneWidget } from './phone-widget';
import { ru } from '@/shared/i18n/ru';
import { useCallStateStore } from '@/entities/session';
import { useMediaStateStore } from '@/entities/call';
import { useStageStore } from '@/entities/stage';
import { ACTIONS_BY_STAGE_STATE, makeCallState, makeCard } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

// -- E11-C: the fake LiveKit `Room` the widget's `CallMedia` builds through `livekit-client`'s
// default export (`shared/media/call-media.ts`'s `defaultRoomFactory`). `vi.mock` intercepts the
// module for every importer in this file's graph, so the widget itself needs no test-only prop —
// exactly the "transport-injected... the Room is created by an injected factory" design, just
// injected at the module boundary here instead of through a constructor argument.
const { FakeRoom, roomInstances, nextRoomConfig } = vi.hoisted(() => {
  // Read by each new `FakeRoom`'s constructor — set *before* `render()` so a test can script a
  // denied microphone deterministically, instead of racing the widget's own async join sequence
  // to mutate an already-constructed instance.
  const nextRoomConfig = { denyMic: false };

  class FakeLocalTrack {
    muted = false;
    readonly mediaStreamTrack = {} as MediaStreamTrack;
    async mute(): Promise<void> {
      this.muted = true;
    }
    async unmute(): Promise<void> {
      this.muted = false;
    }
  }
  class FakeLocalParticipant {
    readonly track = new FakeLocalTrack();
    denyMic: boolean;
    micEnabledCalls: boolean[] = [];
    constructor(denyMic: boolean) {
      this.denyMic = denyMic;
    }
    async setMicrophoneEnabled(enabled: boolean): Promise<{ track: FakeLocalTrack } | undefined> {
      this.micEnabledCalls.push(enabled);
      if (this.denyMic) {
        throw new DOMException('Permission denied', 'NotAllowedError');
      }
      return { track: this.track };
    }
  }
  class FakeRoom {
    static instances: FakeRoom[] = [];
    readonly localParticipant: FakeLocalParticipant;
    connectCalls: Array<{ url: string; token: string }> = [];
    connectError: Error | null = null;
    disconnected = false;
    private readonly listeners = new Map<string, Set<(...args: unknown[]) => void>>();

    constructor() {
      this.localParticipant = new FakeLocalParticipant(nextRoomConfig.denyMic);
      FakeRoom.instances.push(this);
    }
    async connect(url: string, token: string): Promise<void> {
      this.connectCalls.push({ url, token });
      if (this.connectError) throw this.connectError;
    }
    async disconnect(): Promise<void> {
      this.disconnected = true;
    }
    on(event: string, handler: (...args: unknown[]) => void): this {
      const set = this.listeners.get(event) ?? new Set();
      set.add(handler);
      this.listeners.set(event, set);
      return this;
    }
    off(event: string, handler: (...args: unknown[]) => void): this {
      this.listeners.get(event)?.delete(handler);
      return this;
    }
    emit(event: string, ...args: unknown[]): void {
      for (const handler of this.listeners.get(event) ?? []) handler(...args);
    }
  }
  return { FakeRoom, roomInstances: FakeRoom.instances, nextRoomConfig };
});

vi.mock('livekit-client', () => ({ Room: FakeRoom }));

// jsdom has neither Web Audio nor `MediaStream` (`shared/media/level-meter.ts` relies on both) —
// stubbed globally, the same way this file already stubs `fetch`/`WebSocket`.
class FakeAnalyser {
  fftSize = 0;
  frequencyBinCount = 4;
  getByteTimeDomainData(array: Uint8Array): void {
    array.fill(128);
  }
}
class FakeAudioContext {
  createAnalyser(): FakeAnalyser {
    return new FakeAnalyser();
  }
  createMediaStreamSource(): { connect(): void; disconnect(): void } {
    return { connect: () => {}, disconnect: () => {} };
  }
  close(): void {}
}
class FakeMediaStream {
  readonly tracks: MediaStreamTrack[];
  constructor(tracks: MediaStreamTrack[]) {
    this.tracks = tracks;
  }
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

    render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);

    expect(screen.queryByRole('button', { name: /answer/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/^\d{2}:\d{2}$/)).not.toBeInTheDocument();
  });

  it('RINGING: shows the ringing indicator and the server-labelled answer button only when available_actions offers it', () => {
    useCallStateStore.setState({ callState: makeCallState({ phase: 'RINGING', caller_display_ru: 'Caller X' }) });
    useStageStore.setState({ availableActions: ACTIONS_BY_STAGE_STATE.RINGING });

    render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);

    expect(screen.getByRole('button', { name: 'Answer' })).toBeInTheDocument();
    expect(screen.getByText('Caller X')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /end call/i })).not.toBeInTheDocument();
  });

  it('CONNECTED: shows the call timer and the hang-up button', () => {
    useCallStateStore.setState({ callState: makeCallState({ phase: 'CONNECTED', answered_at_offset_ms: 1000 }) });
    useStageStore.setState({ availableActions: ACTIONS_BY_STAGE_STATE.CONNECTED });

    render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);

    expect(screen.getByRole('button', { name: 'End call' })).toBeInTheDocument();
    expect(screen.getByText(/^\d{2}:\d{2}$/)).toBeInTheDocument();
  });

  it('ENDED: shows the final duration, no action buttons', () => {
    useCallStateStore.setState({ callState: makeCallState({ phase: 'ENDED', duration_ms: 65_000 }) });
    useStageStore.setState({ availableActions: [] });

    render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);

    expect(screen.getByText('01:05')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /answer/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /end call/i })).not.toBeInTheDocument();
  });

  it('caller_speaking renders the speaking indicator', () => {
    useCallStateStore.setState({ callState: makeCallState({ phase: 'CONNECTED', caller_speaking: true }) });
    useStageStore.setState({ availableActions: [] });

    render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);

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

    render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);
    await user.click(screen.getByRole('button', { name: 'Answer' }));

    await waitFor(() => expect(useCallStateStore.getState().callState?.phase).toBe('CONNECTED'));
    expect(useStageStore.getState().stageState).toBe('CONNECTED');
  });
});

// The backend's browser-facing URL (`VoiceTokenResponse.livekit_url`, its `livekit_public_url`
// setting, E11-B) — the normal source of truth per the coordinator's follow-up ruling. Kept
// deliberately different from the `VITE_LIVEKIT_URL` override tests use below, so a test that
// asserts one or the other actually proves which source won.
const RESPONSE_LIVEKIT_URL = 'ws://response-livekit:7880';

function stubVoiceTokenFetch(token = 'jwt-voice-token'): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith('/voice-token')) {
      expect(url).toBe('/api/v1/sessions/sess-1/voice-token');
      return jsonResponse({
        token,
        livekit_url: RESPONSE_LIVEKIT_URL,
        room_name: 'room-1',
        participant_identity: 'operator-1',
        expires_at: '2026-09-21T11:00:00Z',
      });
    }
    throw new Error(`unexpected fetch: ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('PhoneWidget — LiveKit call media (SPEC §15, §32, §34; D9, D12)', () => {
  afterEach(() => {
    cleanup();
    useCallStateStore.setState({ callState: null });
    useStageStore.getState().reset();
    useMediaStateStore.getState().reset();
    roomInstances.length = 0;
    nextRoomConfig.denyMic = false;
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it('does not join the LiveKit room while the call is only RINGING', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      throw new Error(`unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    useCallStateStore.setState({ callState: makeCallState({ phase: 'RINGING', call_id: 'call-1' }) });
    useStageStore.setState({ availableActions: ACTIONS_BY_STAGE_STATE.RINGING });

    render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);
    await Promise.resolve();

    expect(roomInstances).toHaveLength(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('joins the room only once the server reports CONNECTED, using the response\'s browser-facing livekit_url', async () => {
    const fetchMock = stubVoiceTokenFetch();
    useCallStateStore.setState({ callState: makeCallState({ phase: 'CONNECTED', call_id: 'call-1', answered_at_offset_ms: 0 }) });
    useStageStore.setState({ availableActions: ACTIONS_BY_STAGE_STATE.CONNECTED });

    render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);

    await waitFor(() => expect(roomInstances).toHaveLength(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(roomInstances[0]!.connectCalls).toEqual([{ url: RESPONSE_LIVEKIT_URL, token: 'jwt-voice-token' }]);
    await waitFor(() => expect(useMediaStateStore.getState().phase).toBe('connected'));
  });

  it('VITE_LIVEKIT_URL, when set and non-empty, overrides the response\'s livekit_url (dev override)', async () => {
    vi.stubEnv('VITE_LIVEKIT_URL', 'ws://dev-override:7880');
    const fetchMock = stubVoiceTokenFetch();
    useCallStateStore.setState({ callState: makeCallState({ phase: 'CONNECTED', call_id: 'call-1' }) });
    useStageStore.setState({ availableActions: ACTIONS_BY_STAGE_STATE.CONNECTED });

    render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);

    await waitFor(() => expect(roomInstances).toHaveLength(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(roomInstances[0]!.connectCalls).toEqual([{ url: 'ws://dev-override:7880', token: 'jwt-voice-token' }]);
  });

  it('an empty-string VITE_LIVEKIT_URL never shadows the response\'s livekit_url', async () => {
    vi.stubEnv('VITE_LIVEKIT_URL', '');
    stubVoiceTokenFetch();
    useCallStateStore.setState({ callState: makeCallState({ phase: 'CONNECTED', call_id: 'call-1' }) });
    useStageStore.setState({ availableActions: ACTIONS_BY_STAGE_STATE.CONNECTED });

    render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);

    await waitFor(() => expect(roomInstances).toHaveLength(1));
    expect(roomInstances[0]!.connectCalls).toEqual([{ url: RESPONSE_LIVEKIT_URL, token: 'jwt-voice-token' }]);
  });

  it('requests the voice token at most once per join, even across re-renders for the same call_id', async () => {
    const fetchMock = stubVoiceTokenFetch();
    useCallStateStore.setState({ callState: makeCallState({ phase: 'CONNECTED', call_id: 'call-1' }) });
    useStageStore.setState({ availableActions: ACTIONS_BY_STAGE_STATE.CONNECTED });

    render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);
    await waitFor(() => expect(roomInstances).toHaveLength(1));

    // The same snapshot/event data re-arriving (e.g. a reactive re-fetch) must not re-request a
    // token or open a second room.
    useCallStateStore.setState({ callState: makeCallState({ phase: 'CONNECTED', call_id: 'call-1', caller_speaking: true }) });
    await waitFor(() => expect(useCallStateStore.getState().callState?.caller_speaking).toBe(true));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(roomInstances).toHaveLength(1);
  });

  it('a browser refresh that restores straight into CONNECTED still joins exactly once', async () => {
    const fetchMock = stubVoiceTokenFetch();
    // Mounting directly with CONNECTED is exactly what the console page's snapshot-restore
    // effect produces on a mid-call refresh (SPEC §39, §42 test 13) — no RINGING/CONNECTED
    // transition, just an initial CONNECTED render.
    useCallStateStore.setState({ callState: makeCallState({ phase: 'CONNECTED', call_id: 'call-1' }) });
    useStageStore.setState({ availableActions: ACTIONS_BY_STAGE_STATE.CONNECTED });

    render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);

    await waitFor(() => expect(roomInstances).toHaveLength(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(roomInstances[0]!.connectCalls).toHaveLength(1);
  });

  it('microphone permission denial shows the Russian message but leaves the call controllable', async () => {
    vi.stubGlobal('AudioContext', FakeAudioContext);
    vi.stubGlobal('MediaStream', FakeMediaStream);
    nextRoomConfig.denyMic = true;
    stubVoiceTokenFetch();
    useCallStateStore.setState({ callState: makeCallState({ phase: 'CONNECTED', call_id: 'call-1' }) });
    useStageStore.setState({ availableActions: ACTIONS_BY_STAGE_STATE.CONNECTED });

    render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);

    await waitFor(() => expect(screen.getByText(ru.operatorMicPermissionDenied)).toBeInTheDocument());

    // The room itself stayed joined (the caller can still be heard) and hang-up is still on the
    // page and enabled — a media failure never blocks a REST command (SPEC §39).
    expect(roomInstances[0]!.disconnected).toBe(false);
    expect(screen.getByRole('button', { name: 'End call' })).toBeEnabled();
  });

  it('mute toggles the local track and the button label — never a backend command', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('AudioContext', FakeAudioContext);
    vi.stubGlobal('MediaStream', FakeMediaStream);
    const fetchMock = stubVoiceTokenFetch();
    useCallStateStore.setState({ callState: makeCallState({ phase: 'CONNECTED', call_id: 'call-1' }) });
    useStageStore.setState({ availableActions: ACTIONS_BY_STAGE_STATE.CONNECTED });

    render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);
    await waitFor(() => expect(roomInstances[0]?.localParticipant.micEnabledCalls).toEqual([true]));

    const muteButton = screen.getByRole('button', { name: ru.operatorMuteButton });
    await user.click(muteButton);

    await waitFor(() => expect(roomInstances[0]!.localParticipant.track.muted).toBe(true));
    expect(screen.getByRole('button', { name: ru.operatorUnmuteButton })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: ru.operatorUnmuteButton }));
    await waitFor(() => expect(roomInstances[0]!.localParticipant.track.muted).toBe(false));

    // Muting never calls the REST API — only the two REST calls this test itself expects
    // (the voice-token mint) ever happen.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('a LiveKit reconnect shows the Russian reconnecting message without touching CallStateView', async () => {
    stubVoiceTokenFetch();
    useCallStateStore.setState({ callState: makeCallState({ phase: 'CONNECTED', call_id: 'call-1' }) });
    useStageStore.setState({ availableActions: ACTIONS_BY_STAGE_STATE.CONNECTED });

    render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);
    await waitFor(() => expect(roomInstances).toHaveLength(1));

    roomInstances[0]!.emit('reconnecting');
    await waitFor(() => expect(screen.getByText(ru.operatorCallReconnecting)).toBeInTheDocument());
    // The application-WebSocket-fed call state is untouched by a LiveKit-only reconnect.
    expect(useCallStateStore.getState().callState?.phase).toBe('CONNECTED');

    roomInstances[0]!.emit('reconnected');
    await waitFor(() => expect(screen.queryByText(ru.operatorCallReconnecting)).not.toBeInTheDocument());
  });

  it('leaves the room when the call reaches ENDED', async () => {
    stubVoiceTokenFetch();
    useCallStateStore.setState({ callState: makeCallState({ phase: 'CONNECTED', call_id: 'call-1' }) });
    useStageStore.setState({ availableActions: ACTIONS_BY_STAGE_STATE.CONNECTED });

    render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);
    await waitFor(() => expect(roomInstances).toHaveLength(1));

    useCallStateStore.setState({ callState: makeCallState({ phase: 'ENDED', call_id: 'call-1', duration_ms: 12_000 }) });

    await waitFor(() => expect(roomInstances[0]!.disconnected).toBe(true));
  });

  it('leaves the room on unmount (covers the route-change-away case too)', async () => {
    stubVoiceTokenFetch();
    useCallStateStore.setState({ callState: makeCallState({ phase: 'CONNECTED', call_id: 'call-1' }) });
    useStageStore.setState({ availableActions: ACTIONS_BY_STAGE_STATE.CONNECTED });

    const { unmount } = render(<PhoneWidget sessionId="sess-1" monotonicOffsetMs={0} />);
    await waitFor(() => expect(roomInstances).toHaveLength(1));

    unmount();

    await waitFor(() => expect(roomInstances[0]!.disconnected).toBe(true));
  });
});
