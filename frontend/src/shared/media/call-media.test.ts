import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  CallMedia,
  type AudioContextLike,
  type LocalParticipantLike,
  type LocalTrackLike,
  type LocalTrackPublicationLike,
  type RemoteTrackLike,
  type RoomEventName,
  type RoomEventPayloads,
  type RoomLike,
} from './call-media';

class FakeLocalTrack implements LocalTrackLike {
  muted = false;
  readonly mediaStreamTrack = {} as MediaStreamTrack;
  async mute(): Promise<unknown> {
    this.muted = true;
    return this;
  }
  async unmute(): Promise<unknown> {
    this.muted = false;
    return this;
  }
}

class FakeLocalParticipant implements LocalParticipantLike {
  readonly track = new FakeLocalTrack();
  micEnabledCalls: boolean[] = [];
  shouldDenyMic = false;

  async setMicrophoneEnabled(enabled: boolean): Promise<LocalTrackPublicationLike | undefined> {
    this.micEnabledCalls.push(enabled);
    if (this.shouldDenyMic) {
      throw new DOMException('Permission denied', 'NotAllowedError');
    }
    return { track: this.track };
  }
}

class FakeRemoteTrack implements RemoteTrackLike {
  readonly kind: string;
  attachedElements: HTMLMediaElement[] = [];

  constructor(kind: string) {
    this.kind = kind;
  }

  attach(): HTMLMediaElement {
    const element = document.createElement('audio');
    this.attachedElements.push(element);
    return element;
  }

  detach(): HTMLMediaElement[] {
    const detached = this.attachedElements;
    this.attachedElements = [];
    return detached;
  }
}

class FakeRoom implements RoomLike {
  readonly localParticipant: FakeLocalParticipant;
  readonly connectCalls: Array<{ url: string; token: string }> = [];
  connectError: Error | null = null;
  disconnected = false;
  private readonly listeners = new Map<RoomEventName, Set<(...args: never[]) => void>>();

  constructor(localParticipant: FakeLocalParticipant = new FakeLocalParticipant()) {
    this.localParticipant = localParticipant;
  }

  async connect(url: string, token: string): Promise<void> {
    this.connectCalls.push({ url, token });
    if (this.connectError) throw this.connectError;
  }

  async disconnect(): Promise<void> {
    this.disconnected = true;
  }

  on<E extends RoomEventName>(event: E, handler: (...args: RoomEventPayloads[E]) => void): this {
    const set = this.listeners.get(event) ?? new Set();
    set.add(handler as unknown as (...args: never[]) => void);
    this.listeners.set(event, set);
    return this;
  }

  off<E extends RoomEventName>(event: E, handler: (...args: RoomEventPayloads[E]) => void): this {
    this.listeners.get(event)?.delete(handler as unknown as (...args: never[]) => void);
    return this;
  }

  emit<E extends RoomEventName>(event: E, ...args: RoomEventPayloads[E]): void {
    for (const handler of this.listeners.get(event) ?? []) {
      (handler as unknown as (...args: RoomEventPayloads[E]) => void)(...args);
    }
  }
}

class FakeAnalyser {
  fftSize = 0;
  frequencyBinCount = 4;
  nextBytes = new Uint8Array([128, 128, 128, 128]);
  getByteTimeDomainData(array: Uint8Array): void {
    array.set(this.nextBytes);
  }
}

class FakeAudioContext implements AudioContextLike {
  analysers: FakeAnalyser[] = [];
  closed = false;
  createAnalyser(): FakeAnalyser {
    const analyser = new FakeAnalyser();
    this.analysers.push(analyser);
    return analyser;
  }
  createMediaStreamSource(): { connect(): void; disconnect(): void } {
    return { connect: () => {}, disconnect: () => {} };
  }
  close(): void {
    this.closed = true;
  }
}

describe('CallMedia', () => {
  let room: FakeRoom;
  let audioContext: FakeAudioContext;
  let media: CallMedia;
  let phases: string[];
  let levels: number[];
  let micDeniedCount: number;

  function makeMedia(localParticipant?: FakeLocalParticipant): void {
    room = new FakeRoom(localParticipant);
    audioContext = new FakeAudioContext();
    phases = [];
    levels = [];
    micDeniedCount = 0;
    media = new CallMedia(
      {
        onPhaseChange: (phase) => phases.push(phase),
        onLevel: (level) => levels.push(level),
        onMicPermissionDenied: () => {
          micDeniedCount += 1;
        },
      },
      {
        roomFactory: () => room,
        audioContextFactory: () => audioContext,
        mediaStreamFactory: () => ({}) as MediaStream,
        levelIntervalMs: 50,
      },
    );
  }

  beforeEach(() => {
    vi.useFakeTimers();
    makeMedia();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('connects, publishes the mic and reports connecting -> connected', async () => {
    await media.connect('ws://livekit', 'tok');

    expect(room.connectCalls).toEqual([{ url: 'ws://livekit', token: 'tok' }]);
    expect(room.localParticipant.micEnabledCalls).toEqual([true]);
    expect(phases).toEqual(['connecting', 'connected']);
  });

  it('connect() is a no-op while already connecting/connected — one join per call', async () => {
    const first = media.connect('ws://livekit', 'tok');
    const second = media.connect('ws://livekit', 'tok');
    await Promise.all([first, second]);

    expect(room.connectCalls).toHaveLength(1);
  });

  it('a room connect() failure reports failed and never publishes the mic', async () => {
    room.connectError = new Error('unreachable');

    await media.connect('ws://livekit', 'tok');

    expect(phases).toEqual(['connecting', 'failed']);
    expect(room.localParticipant.micEnabledCalls).toEqual([]);
  });

  it('reports the local mic level from the AnalyserNode while connected', async () => {
    await media.connect('ws://livekit', 'tok');
    vi.advanceTimersByTime(50);

    expect(levels.length).toBeGreaterThan(0);
    expect(levels[0]).toBe(0); // byte 128 normalises to 0 -> RMS 0

    audioContext.analysers[0]!.nextBytes = new Uint8Array([255, 0, 255, 0]);
    vi.advanceTimersByTime(50);
    expect(levels.at(-1)).toBeGreaterThan(0);
  });

  it('a level-meter setup failure is never reported as a microphone permission denial', async () => {
    media = new CallMedia(
      {
        onPhaseChange: (phase) => phases.push(phase),
        onMicPermissionDenied: () => {
          micDeniedCount += 1;
        },
      },
      {
        roomFactory: () => room,
        audioContextFactory: () => {
          throw new Error('no Web Audio API');
        },
      },
    );

    await media.connect('ws://livekit', 'tok');

    expect(micDeniedCount).toBe(0);
    expect(room.localParticipant.micEnabledCalls).toEqual([true]);
    expect(phases).toEqual(['connecting', 'connected']);
  });

  it('microphone permission denial reports onMicPermissionDenied but keeps the room joined', async () => {
    const localParticipant = new FakeLocalParticipant();
    localParticipant.shouldDenyMic = true;
    makeMedia(localParticipant);

    await media.connect('ws://livekit', 'tok');

    expect(micDeniedCount).toBe(1);
    expect(phases).toEqual(['connecting', 'connected']);
    expect(room.disconnected).toBe(false);
  });

  it('mute() calls track.mute(), unmute calls track.unmute() — local track only', async () => {
    await media.connect('ws://livekit', 'tok');
    const track = room.localParticipant.track;

    media.setMuted(true);
    await Promise.resolve();
    expect(track.muted).toBe(true);

    media.setMuted(false);
    await Promise.resolve();
    expect(track.muted).toBe(false);
  });

  it('reconnecting/reconnected room events flip the phase without a new join', async () => {
    await media.connect('ws://livekit', 'tok');

    room.emit('reconnecting');
    expect(phases.at(-1)).toBe('reconnecting');

    room.emit('reconnected');
    expect(phases.at(-1)).toBe('connected');
    expect(room.connectCalls).toHaveLength(1);
  });

  it('an unexpected disconnected event (not our own leave) reports failed', async () => {
    await media.connect('ws://livekit', 'tok');

    room.emit('disconnected');

    expect(phases.at(-1)).toBe('failed');
  });

  it('attaches and plays subscribed caller audio, detaches it on unsubscribe', async () => {
    await media.connect('ws://livekit', 'tok');
    const remoteTrack = new FakeRemoteTrack('audio');

    room.emit('trackSubscribed', remoteTrack);
    expect(remoteTrack.attachedElements).toHaveLength(1);
    const element = remoteTrack.attachedElements[0]!;
    expect(document.body.contains(element)).toBe(true);
    expect(element.autoplay).toBe(true);

    room.emit('trackUnsubscribed', remoteTrack);
    expect(document.body.contains(element)).toBe(false);
  });

  it('ignores a non-audio subscribed track', async () => {
    await media.connect('ws://livekit', 'tok');
    const remoteTrack = new FakeRemoteTrack('video');

    room.emit('trackSubscribed', remoteTrack);

    expect(remoteTrack.attachedElements).toHaveLength(0);
  });

  it('disconnect() leaves the room, stops the level meter and detaches remote audio', async () => {
    await media.connect('ws://livekit', 'tok');
    const remoteTrack = new FakeRemoteTrack('audio');
    room.emit('trackSubscribed', remoteTrack);
    const element = remoteTrack.attachedElements[0]!;

    await media.disconnect();

    expect(room.disconnected).toBe(true);
    expect(audioContext.closed).toBe(true);
    expect(phases.at(-1)).toBe('idle');
    expect(document.body.contains(element)).toBe(false);

    // An event from the now-detached room must not resurrect a phase after we left on purpose.
    room.emit('disconnected');
    expect(phases.at(-1)).toBe('idle');
  });

  it('disconnect() is a harmless no-op when never connected', async () => {
    await media.disconnect();
    expect(phases).toEqual(['idle']);
  });
});

describe('CallMedia module boundary (SPEC §15: raw audio never leaves the LiveKit room)', () => {
  it('never imports the REST client or the realtime WebSocket client', () => {
    const source = readFileSync(join(__dirname, 'call-media.ts'), 'utf-8');
    // Only import statements and actual calls matter here — the module's own comments are
    // allowed to talk *about* the REST/WS boundary it stays out of.
    const importLines = source.split('\n').filter((line) => /^\s*import\b/.test(line));
    for (const line of importLines) {
      expect(line).not.toMatch(/shared\/lib\/api/);
      expect(line).not.toMatch(/shared\/realtime/);
    }
    expect(source).not.toMatch(/\bfetch\(/);
    expect(source).not.toMatch(/new WebSocket\(/);
  });
});
