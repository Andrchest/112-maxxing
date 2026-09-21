// Transport-injected LiveKit call media wrapper (SPEC §15, §32, §34; D9, D12). One `CallMedia`
// instance is one call: `connect` joins the room and publishes the microphone, `setMuted` mutes
// only the local track (never a backend command), `disconnect` leaves cleanly. Caller audio that
// LiveKit subscribes us to is attached to an `<audio>` element and played automatically.
//
// This module never calls the backend REST API and never opens the application WebSocket — raw
// audio and its control travel only through the LiveKit room (SPEC §15; see `call-media.test.ts`
// "never imports the REST client or the realtime WebSocket client"). The token this module
// receives comes from the caller (the phone widget, via `createVoiceToken`); this module never
// requests, logs or otherwise looks at how it was obtained.
//
// The `livekit-client` `Room` is built through an injected factory so tests exercise this against
// a fake instead of a real WebRTC connection (jsdom has neither WebRTC nor Web Audio).
import { Room } from 'livekit-client';
import { startLevelMeter, type AudioContextLike, type LevelMeterHandle } from './level-meter';

export type { AudioContextLike };

export type MediaPhase = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'failed';

export interface LocalTrackLike {
  readonly mediaStreamTrack: MediaStreamTrack;
  mute(): Promise<unknown>;
  unmute(): Promise<unknown>;
}

export interface LocalTrackPublicationLike {
  track?: LocalTrackLike;
}

export interface LocalParticipantLike {
  setMicrophoneEnabled(enabled: boolean): Promise<LocalTrackPublicationLike | undefined>;
}

export interface RemoteTrackLike {
  readonly kind: string;
  attach(): HTMLMediaElement;
  detach(): HTMLMediaElement[];
}

/** The room events this module reacts to, and the arguments each carries — narrow, typed slice
 * of `livekit-client`'s `RoomEvent`/`RoomEventCallbacks` (D9: only what the phone widget needs). */
export interface RoomEventPayloads {
  reconnecting: [];
  reconnected: [];
  disconnected: [];
  trackSubscribed: [track: RemoteTrackLike];
  trackUnsubscribed: [track: RemoteTrackLike];
}
export type RoomEventName = keyof RoomEventPayloads;

export interface RoomLike {
  readonly localParticipant: LocalParticipantLike;
  connect(url: string, token: string): Promise<void>;
  disconnect(): Promise<void>;
  on<E extends RoomEventName>(event: E, handler: (...args: RoomEventPayloads[E]) => void): unknown;
  off<E extends RoomEventName>(event: E, handler: (...args: RoomEventPayloads[E]) => void): unknown;
}

export interface CallMediaCallbacks {
  onPhaseChange?: (phase: MediaPhase) => void;
  /** 0..1 local mic level, via the `AnalyserNode` meter (DESIGN: local mic only). */
  onLevel?: (level: number) => void;
  /** Fired when `setMicrophoneEnabled` rejects (denied/unavailable mic). The room stays joined —
   * the caller can still be heard and REST commands (hang-up) keep working (SPEC §39: media
   * failure never blocks a REST command or touches simulation state). */
  onMicPermissionDenied?: () => void;
}

export interface CallMediaOptions {
  roomFactory?: () => RoomLike;
  audioContextFactory?: () => AudioContextLike;
  mediaStreamFactory?: (track: MediaStreamTrack) => MediaStream;
  levelIntervalMs?: number;
}

function defaultRoomFactory(): RoomLike {
  return new Room() as unknown as RoomLike;
}

const AUDIO_KIND = 'audio';

export class CallMedia {
  private readonly callbacks: CallMediaCallbacks;
  private readonly roomFactory: () => RoomLike;
  private readonly audioContextFactory?: () => AudioContextLike;
  private readonly mediaStreamFactory?: (track: MediaStreamTrack) => MediaStream;
  private readonly levelIntervalMs?: number;

  private room: RoomLike | null = null;
  private localTrack: LocalTrackLike | null = null;
  private levelMeter: LevelMeterHandle | null = null;
  private readonly remoteElements = new Set<HTMLMediaElement>();
  private muted = false;

  private readonly handleReconnecting = (): void => this.setPhase('reconnecting');
  private readonly handleReconnected = (): void => this.setPhase('connected');
  private readonly handleDisconnected = (): void => this.setPhase('failed');

  private readonly handleTrackSubscribed = (track: RemoteTrackLike): void => {
    if (track.kind !== AUDIO_KIND) return;
    const element = track.attach();
    element.autoplay = true;
    document.body.appendChild(element);
    this.remoteElements.add(element);
  };

  private readonly handleTrackUnsubscribed = (track: RemoteTrackLike): void => {
    if (track.kind !== AUDIO_KIND) return;
    for (const element of track.detach()) {
      this.remoteElements.delete(element);
      element.remove();
    }
  };

  constructor(callbacks: CallMediaCallbacks = {}, options: CallMediaOptions = {}) {
    this.callbacks = callbacks;
    this.roomFactory = options.roomFactory ?? defaultRoomFactory;
    this.audioContextFactory = options.audioContextFactory;
    this.mediaStreamFactory = options.mediaStreamFactory;
    this.levelIntervalMs = options.levelIntervalMs;
  }

  /** Joins the room at `url` with `token` and publishes the local microphone (D9 DESIGN: call
   * this only after the server reports the call CONNECTED). A no-op while already
   * connecting/connected, so a repeated call for the same join is harmless — the caller (the
   * phone widget) is still responsible for requesting the token at most once per join. */
  async connect(url: string, token: string): Promise<void> {
    if (this.room) return;
    this.setPhase('connecting');
    const room = this.roomFactory();
    this.room = room;
    this.attachRoomListeners(room);

    try {
      await room.connect(url, token);
    } catch {
      this.detachRoomListeners(room);
      this.room = null;
      this.setPhase('failed');
      return;
    }

    this.setPhase('connected');

    try {
      const publication = await room.localParticipant.setMicrophoneEnabled(true);
      const track = publication?.track ?? null;
      this.localTrack = track;
      if (track) {
        if (this.muted) {
          await track.mute();
        }
        // The level meter is a display nicety (SPEC §32 "level meter"), isolated in its own
        // try/catch: a `startLevelMeter` failure (no Web Audio API, say) must never be reported
        // through `onMicPermissionDenied` — the mic is published either way.
        try {
          this.startLevelMeter(track.mediaStreamTrack);
        } catch {
          /* the meter just stays silent; the call is unaffected */
        }
      }
    } catch {
      this.callbacks.onMicPermissionDenied?.();
    }
  }

  /** Local track mute only (D9 DESIGN: "never a backend command"). Safe to call before the mic
   * has published — the pending state is applied once `connect()` finishes. */
  setMuted(muted: boolean): void {
    this.muted = muted;
    const track = this.localTrack;
    if (!track) return;
    void (muted ? track.mute() : track.unmute());
  }

  /** Leaves the room, stops the level meter and detaches any caller audio (D9 DESIGN: on ENDED,
   * unmount or route change). Safe to call when never connected. */
  async disconnect(): Promise<void> {
    this.stopLevelMeter();
    for (const element of this.remoteElements) {
      element.remove();
    }
    this.remoteElements.clear();

    const room = this.room;
    this.room = null;
    this.localTrack = null;
    if (!room) {
      this.setPhase('idle');
      return;
    }

    // Detached before `room.disconnect()` so the resulting `disconnected` event (an intentional
    // leave) never gets reported as a failure through `handleDisconnected`.
    this.detachRoomListeners(room);
    try {
      await room.disconnect();
    } catch {
      // Best-effort leave — the room may already be gone.
    }
    this.setPhase('idle');
  }

  private attachRoomListeners(room: RoomLike): void {
    room.on('reconnecting', this.handleReconnecting);
    room.on('reconnected', this.handleReconnected);
    room.on('disconnected', this.handleDisconnected);
    room.on('trackSubscribed', this.handleTrackSubscribed);
    room.on('trackUnsubscribed', this.handleTrackUnsubscribed);
  }

  private detachRoomListeners(room: RoomLike): void {
    room.off('reconnecting', this.handleReconnecting);
    room.off('reconnected', this.handleReconnected);
    room.off('disconnected', this.handleDisconnected);
    room.off('trackSubscribed', this.handleTrackSubscribed);
    room.off('trackUnsubscribed', this.handleTrackUnsubscribed);
  }

  private startLevelMeter(mediaStreamTrack: MediaStreamTrack): void {
    this.stopLevelMeter();
    this.levelMeter = startLevelMeter(mediaStreamTrack, (level) => this.callbacks.onLevel?.(level), {
      audioContextFactory: this.audioContextFactory,
      mediaStreamFactory: this.mediaStreamFactory,
      intervalMs: this.levelIntervalMs,
    });
  }

  private stopLevelMeter(): void {
    this.levelMeter?.stop();
    this.levelMeter = null;
  }

  private setPhase(phase: MediaPhase): void {
    this.callbacks.onPhaseChange?.(phase);
  }
}
