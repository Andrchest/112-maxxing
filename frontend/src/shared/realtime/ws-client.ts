// Client half of the realtime protocol (`docs/hld/40-realtime-protocol.md`, D8, D12 design
// decision #2). Transport-injected: `createSocket` defaults to the browser `WebSocket`, so tests
// drive this with a fake socket and fake timers instead of a real connection.
//
// Contract implemented literally from HLD §40:
//   - connect with `?token=` (§40.1); the client sends exactly one frame type, `resume`
//     (§40.2) — this module never sends anything else;
//   - resume with the last contiguous `seq_no` (the REST snapshot's `last_seq_no` on first
//     connect, §40.5 step 2-3);
//   - apply `event` frames idempotently by `seq_no` (§40.3 at-least-once delivery: a duplicate
//     at the replay/live seam is a no-op, not a second apply);
//   - a `seq_no` gap, or a `heartbeat` whose `last_seq_no` is ahead of what we've applied,
//     re-sends `resume` instead of accepting a hole in the stream;
//   - exponential reconnect backoff on an abnormal close;
//   - no reconnect on `4401`/`4403`/`4404` (HLD §40.1: these will not resolve by retrying).
import { WS_BASE_PATH } from '@/shared/config';
import type { components } from '@/shared/api';

export type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];

export type ConnectionStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed';

/** The subset of the `WebSocket` interface this client needs — small enough for a test to fake
 * without a real socket or a jsdom WebSocket polyfill. */
export interface WebSocketLike {
  readyState: number;
  onopen: (() => void) | null;
  onclose: ((event: { code: number; reason?: string }) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onmessage: ((event: { data: string }) => void) | null;
  send(data: string): void;
  close(code?: number, reason?: string): void;
}

interface EventFrame extends SessionEventEnvelope {
  type: 'event';
}
interface ResumeCompleteFrame {
  type: 'resume_complete';
  replayed_count: number;
  last_seq_no: number;
  live: boolean;
}
interface HeartbeatFrame {
  type: 'heartbeat';
  server_time_utc: string;
  last_seq_no: number;
}
interface ErrorFrame {
  type: 'error';
  code: string;
  detail?: string;
}
type ServerFrame = EventFrame | ResumeCompleteFrame | HeartbeatFrame | ErrorFrame;

// HLD §40.5: "0.5 s, 1 s, 2 s, 4 s, capped at 10 s, with jitter" — doubling on every abnormal
// close, nominal delay capped at 10 s.
const DEFAULT_MIN_BACKOFF_MS = 500;
const DEFAULT_MAX_BACKOFF_MS = 10000;

// HLD §40.5 names "jitter" without an exact formula. ±20% of the nominal (pre-jitter) delay for
// this attempt, uniformly distributed, then re-clamped to the cap — close enough to the nominal
// schedule to be predictable, random enough to avoid every client retrying in lockstep.
const JITTER_RATIO = 0.2;

// Close codes the server uses for an authorization/session problem that will not resolve by
// retrying (HLD §40.1).
const NO_RECONNECT_CLOSE_CODES = new Set([4401, 4403, 4404]);

export interface WsClientOptions {
  sessionId: string;
  token: string;
  /** The store's last contiguous `seq_no` — the REST snapshot's `last_seq_no` on first connect
   * (HLD §40.5). */
  lastSeqNo: number;
  wsBasePath?: string;
  createSocket?: (url: string) => WebSocketLike;
  onEvent: (event: SessionEventEnvelope) => void;
  onResumeComplete?: (info: { replayedCount: number; lastSeqNo: number; live: boolean }) => void;
  onError?: (frame: ErrorFrame) => void;
  onStatusChange?: (status: ConnectionStatus) => void;
  minBackoffMs?: number;
  maxBackoffMs?: number;
  /** Jitter source for reconnect backoff (HLD §40.5). Defaults to `Math.random`; injectable so
   * tests can assert an exact schedule instead of a random one. */
  random?: () => number;
}

function defaultCreateSocket(url: string): WebSocketLike {
  return new WebSocket(url) as unknown as WebSocketLike;
}

function buildWsUrl(options: Pick<WsClientOptions, 'sessionId' | 'token' | 'wsBasePath'>): string {
  const basePath = options.wsBasePath ?? WS_BASE_PATH;
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const path = `${basePath}/sessions/${encodeURIComponent(options.sessionId)}`;
  return `${scheme}://${window.location.host}${path}?token=${encodeURIComponent(options.token)}`;
}

/** WebSocket client for one `session:{id}:events` connection. Owns its own reconnect/resume
 * bookkeeping; forwards every newly-applied event to `onEvent`, which a caller wires to
 * `entities/session`'s `useSessionEventsStore.applyEvent` in real usage. */
export class WsClient {
  private readonly options: WsClientOptions;
  private readonly random: () => number;
  private socket: WebSocketLike | null = null;
  private status: ConnectionStatus = 'idle';
  private lastSeqNo: number;
  private backoffMs: number;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closedByCaller = false;

  constructor(options: WsClientOptions) {
    this.options = options;
    this.random = options.random ?? Math.random;
    this.lastSeqNo = options.lastSeqNo;
    this.backoffMs = options.minBackoffMs ?? DEFAULT_MIN_BACKOFF_MS;
  }

  connect(): void {
    this.closedByCaller = false;
    this.openSocket();
  }

  /** Closes the socket normally (`1000`) and cancels any pending reconnect. Never reconnects
   * after this — the caller asked for the connection to end. */
  disconnect(): void {
    this.closedByCaller = true;
    this.clearReconnectTimer();
    this.socket?.close(1000);
    this.socket = null;
    this.setStatus('closed');
  }

  getStatus(): ConnectionStatus {
    return this.status;
  }

  private openSocket(): void {
    this.setStatus(this.status === 'idle' ? 'connecting' : 'reconnecting');
    const url = buildWsUrl(this.options);
    const createSocket = this.options.createSocket ?? defaultCreateSocket;
    const socket = createSocket(url);
    this.socket = socket;
    socket.onopen = () => {
      this.backoffMs = this.options.minBackoffMs ?? DEFAULT_MIN_BACKOFF_MS;
      this.sendResume();
    };
    socket.onmessage = (event) => this.handleMessage(event.data);
    socket.onclose = (event) => this.handleClose(event.code);
    socket.onerror = () => {
      /* the close handler carries the reconnect decision; nothing to do here */
    };
  }

  private sendResume(): void {
    // The only frame this client ever sends (D8, HLD §40.2).
    this.socket?.send(JSON.stringify({ type: 'resume', after_seq_no: this.lastSeqNo }));
  }

  private handleMessage(raw: string): void {
    let frame: ServerFrame;
    try {
      frame = JSON.parse(raw) as ServerFrame;
    } catch {
      return;
    }
    switch (frame.type) {
      case 'event':
        this.handleEvent(frame);
        return;
      case 'resume_complete':
        this.setStatus('open');
        this.lastSeqNo = frame.last_seq_no;
        this.options.onResumeComplete?.({
          replayedCount: frame.replayed_count,
          lastSeqNo: frame.last_seq_no,
          live: frame.live,
        });
        return;
      case 'heartbeat':
        // A cheap gap detector (HLD §40.2): a heartbeat ahead of what we've applied means we
        // missed something and re-resume rather than waiting for the next event to reveal it.
        if (frame.last_seq_no > this.lastSeqNo) {
          this.sendResume();
        }
        return;
      case 'error':
        this.options.onError?.(frame);
        return;
    }
  }

  private handleEvent(frame: EventFrame): void {
    if (frame.seq_no <= this.lastSeqNo) {
      // Already-applied event — the replay/live seam duplicate HLD §40.3 warns about. Idempotent
      // no-op, not a second apply.
      return;
    }
    if (frame.seq_no !== this.lastSeqNo + 1) {
      // A gap: re-resume from our last contiguous seq_no instead of accepting a hole (HLD §40.3).
      this.sendResume();
      return;
    }
    this.lastSeqNo = frame.seq_no;
    this.options.onEvent({
      seq_no: frame.seq_no,
      event_type: frame.event_type,
      timestamp_utc: frame.timestamp_utc,
      monotonic_offset_ms: frame.monotonic_offset_ms,
      payload: frame.payload,
      actor_type: frame.actor_type,
      correlation_id: frame.correlation_id,
      redacted_keys: frame.redacted_keys,
    });
  }

  private handleClose(code: number): void {
    this.socket = null;
    if (this.closedByCaller || NO_RECONNECT_CLOSE_CODES.has(code)) {
      this.setStatus('closed');
      return;
    }
    this.setStatus('reconnecting');
    this.scheduleReconnect();
  }

  private scheduleReconnect(): void {
    const maxBackoffMs = this.options.maxBackoffMs ?? DEFAULT_MAX_BACKOFF_MS;
    const nominal = this.backoffMs;
    const jitterRange = nominal * JITTER_RATIO;
    const jitter = (this.random() * 2 - 1) * jitterRange;
    const delay = Math.min(maxBackoffMs, Math.max(0, nominal + jitter));
    this.backoffMs = Math.min(nominal * 2, maxBackoffMs);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openSocket();
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private setStatus(status: ConnectionStatus): void {
    this.status = status;
    this.options.onStatusChange?.(status);
  }
}
