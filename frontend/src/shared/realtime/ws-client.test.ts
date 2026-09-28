import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WsClient, type SessionEventEnvelope, type WebSocketLike, type WsClientOptions } from './ws-client';

class FakeSocket implements WebSocketLike {
  readonly url: string;
  readyState = 0;
  sent: unknown[] = [];
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number; reason?: string }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data));
  }

  close(code = 1000): void {
    this.readyState = 3;
    this.onclose?.({ code });
  }

  // -- test helpers, never called by WsClient itself -----------------------
  simulateOpen(): void {
    this.readyState = 1;
    this.onopen?.();
  }

  simulateMessage(frame: unknown): void {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }

  simulateAbnormalClose(code: number): void {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

function makeEnvelope(seqNo: number): SessionEventEnvelope {
  return {
    seq_no: seqNo,
    event_type: 'SESSION_STARTED',
    timestamp_utc: '2026-09-21T10:00:00.000Z',
    monotonic_offset_ms: seqNo * 100,
    payload: {},
  };
}

describe('WsClient', () => {
  let sockets: FakeSocket[];
  let createSocket: (url: string) => WebSocketLike;

  beforeEach(() => {
    vi.useFakeTimers();
    sockets = [];
    createSocket = (url: string) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket;
    };
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function makeClient(overrides: Partial<WsClientOptions> = {}) {
    const onEvent = vi.fn();
    const onStatusChange = vi.fn();
    const client = new WsClient({
      sessionId: 'sess-1',
      token: 'jwt-token',
      lastSeqNo: 5,
      createSocket,
      onEvent,
      onStatusChange,
      // Fixed at the jitter formula's midpoint (see ws-client.ts JITTER_RATIO) so
      // `nominal + (random()*2-1)*nominal*0.2` collapses to exactly `nominal` — deterministic by
      // default; individual tests override this to exercise the jitter bounds themselves.
      random: () => 0.5,
      ...overrides,
    });
    return { client, onEvent, onStatusChange };
  }

  it('connects with ?token= and sends resume with the initial last_seq_no on open', () => {
    const { client } = makeClient();
    client.connect();

    expect(sockets).toHaveLength(1);
    expect(sockets[0]!.url).toContain('token=jwt-token');
    expect(sockets[0]!.url).toContain('/sessions/sess-1');
    expect(sockets[0]!.sent).toEqual([]);

    sockets[0]!.simulateOpen();

    expect(sockets[0]!.sent).toEqual([{ type: 'resume', after_seq_no: 5 }]);
  });

  it('applies events idempotently by seq_no', () => {
    const { client, onEvent } = makeClient();
    client.connect();
    sockets[0]!.simulateOpen();
    sockets[0]!.simulateMessage({ type: 'resume_complete', replayed_count: 0, last_seq_no: 5, live: true });

    const envelope = makeEnvelope(6);
    sockets[0]!.simulateMessage({ type: 'event', ...envelope });
    sockets[0]!.simulateMessage({ type: 'event', ...envelope }); // duplicate (replay/live seam)

    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent).toHaveBeenCalledWith(envelope);
  });

  it('re-sends resume on a seq_no gap, and still delivers the event after the gap', () => {
    const { client, onEvent } = makeClient();
    client.connect();
    sockets[0]!.simulateOpen();
    sockets[0]!.simulateMessage({ type: 'resume_complete', replayed_count: 0, last_seq_no: 5, live: true });
    sockets[0]!.sent = [];

    sockets[0]!.simulateMessage({ type: 'event', ...makeEnvelope(7) }); // skipped seq_no 6

    expect(onEvent.mock.calls.map(([event]) => event.seq_no)).toEqual([7]);
    expect(sockets[0]!.sent).toEqual([{ type: 'resume', after_seq_no: 5 }]);
  });

  // I6 FIX1: a role-filtered stream (§40.4) has holes by design — the ДДС trainee received 2, 3,
  // then 25…30. The old client dropped 25…30 and jumped its cursor to 30 on `resume_complete`, so
  // e.g. HANDOFF_RECEIVED never reached the page.
  it('delivers every event of a role-filtered stream with permanent holes', () => {
    const { client, onEvent } = makeClient({ lastSeqNo: 3 });
    client.connect();
    sockets[0]!.simulateOpen();
    sockets[0]!.simulateMessage({ type: 'resume_complete', replayed_count: 0, last_seq_no: 3, live: true });
    sockets[0]!.sent = [];

    // Live: 25 arrives after withheld 4…24, then 26…30 while the re-resume is outstanding.
    for (const seqNo of [25, 26, 27]) sockets[0]!.simulateMessage({ type: 'event', ...makeEnvelope(seqNo) });
    expect(sockets[0]!.sent).toEqual([{ type: 'resume', after_seq_no: 3 }]); // one resume, not three
    // The server restarts from 3 and replays what this role may see: 25…30.
    for (const seqNo of [25, 26, 27, 28, 29, 30]) sockets[0]!.simulateMessage({ type: 'event', ...makeEnvelope(seqNo) });
    sockets[0]!.simulateMessage({ type: 'resume_complete', replayed_count: 6, last_seq_no: 30, live: true });

    expect(onEvent.mock.calls.map(([event]) => event.seq_no)).toEqual([25, 26, 27, 28, 29, 30]);

    // The cursor is now the log's 30: the next contiguous live event needs no resume, and a
    // heartbeat at 30 is not a gap.
    sockets[0]!.simulateMessage({ type: 'event', ...makeEnvelope(31) });
    sockets[0]!.simulateMessage({ type: 'heartbeat', server_time_utc: '2026-09-21T10:00:15.000Z', last_seq_no: 31 });
    expect(onEvent.mock.calls.map(([event]) => event.seq_no)).toEqual([25, 26, 27, 28, 29, 30, 31]);
    expect(sockets[0]!.sent).toEqual([{ type: 'resume', after_seq_no: 3 }]);
  });

  it('fills a genuinely lost event from the replay without re-delivering the one after it', () => {
    const { client, onEvent } = makeClient();
    client.connect();
    sockets[0]!.simulateOpen();
    sockets[0]!.simulateMessage({ type: 'resume_complete', replayed_count: 0, last_seq_no: 5, live: true });
    sockets[0]!.sent = [];

    sockets[0]!.simulateMessage({ type: 'event', ...makeEnvelope(7) }); // 6 lost on the bus
    sockets[0]!.simulateMessage({ type: 'event', ...makeEnvelope(6) }); // replayed from PostgreSQL
    sockets[0]!.simulateMessage({ type: 'event', ...makeEnvelope(7) }); // replayed again — a duplicate
    sockets[0]!.simulateMessage({ type: 'resume_complete', replayed_count: 2, last_seq_no: 7, live: true });
    sockets[0]!.simulateMessage({ type: 'event', ...makeEnvelope(8) });

    expect(onEvent.mock.calls.map(([event]) => event.seq_no)).toEqual([7, 6, 8]);
    expect(sockets[0]!.sent).toEqual([{ type: 'resume', after_seq_no: 5 }]);
  });

  it('after a reconnect resumes from the cursor and delivers what was missed while away', () => {
    const { client, onEvent } = makeClient({ lastSeqNo: 3 });
    client.connect();
    sockets[0]!.simulateOpen();
    sockets[0]!.simulateMessage({ type: 'resume_complete', replayed_count: 0, last_seq_no: 3, live: true });
    sockets[0]!.simulateMessage({ type: 'event', ...makeEnvelope(10) }); // past a hole, resume outstanding
    sockets[0]!.simulateAbnormalClose(1006); // dropped before the resume_complete

    vi.advanceTimersByTime(500);
    expect(sockets).toHaveLength(2);
    sockets[1]!.simulateOpen();
    expect(sockets[1]!.sent).toEqual([{ type: 'resume', after_seq_no: 3 }]);
    for (const seqNo of [10, 12, 15]) sockets[1]!.simulateMessage({ type: 'event', ...makeEnvelope(seqNo) });
    sockets[1]!.simulateMessage({ type: 'resume_complete', replayed_count: 3, last_seq_no: 16, live: true });
    sockets[1]!.simulateMessage({ type: 'event', ...makeEnvelope(17) });

    expect(onEvent.mock.calls.map(([event]) => event.seq_no)).toEqual([10, 12, 15, 17]);
    expect(sockets[1]!.sent).toEqual([{ type: 'resume', after_seq_no: 3 }]);
  });

  it('re-sends resume when a heartbeat is ahead of the applied seq_no', () => {
    const { client, onEvent } = makeClient();
    client.connect();
    sockets[0]!.simulateOpen();
    sockets[0]!.simulateMessage({ type: 'resume_complete', replayed_count: 0, last_seq_no: 5, live: true });
    sockets[0]!.sent = [];

    sockets[0]!.simulateMessage({ type: 'heartbeat', server_time_utc: '2026-09-21T10:00:20Z', last_seq_no: 9 });

    expect(onEvent).not.toHaveBeenCalled();
    expect(sockets[0]!.sent).toEqual([{ type: 'resume', after_seq_no: 5 }]);
  });

  it('does not re-send resume when a heartbeat matches the applied seq_no', () => {
    const { client } = makeClient();
    client.connect();
    sockets[0]!.simulateOpen();
    sockets[0]!.simulateMessage({ type: 'resume_complete', replayed_count: 0, last_seq_no: 5, live: true });
    sockets[0]!.sent = [];

    sockets[0]!.simulateMessage({ type: 'heartbeat', server_time_utc: '2026-09-21T10:00:20Z', last_seq_no: 5 });

    expect(sockets[0]!.sent).toEqual([]);
  });

  it('reconnects on an abnormal close with exponential backoff from 500ms capped at 10s (HLD §40.5)', () => {
    // random() fixed at 0.5 (makeClient's default) zeroes the jitter term, so the schedule is
    // exactly the HLD §40.5 nominal sequence: 500ms, 1s, 2s, 4s, 8s, then capped at 10s.
    const { client, onStatusChange } = makeClient();
    client.connect();
    sockets[0]!.simulateOpen();

    sockets[0]!.simulateAbnormalClose(1006);
    expect(onStatusChange).toHaveBeenCalledWith('reconnecting');
    expect(sockets).toHaveLength(1);

    vi.advanceTimersByTime(499);
    expect(sockets).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(2); // reconnected after 500ms

    sockets[1]!.simulateAbnormalClose(1006);
    vi.advanceTimersByTime(999);
    expect(sockets).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(3); // 1000ms (doubled)

    sockets[2]!.simulateAbnormalClose(1006);
    vi.advanceTimersByTime(2000);
    expect(sockets).toHaveLength(4); // 2000ms (doubled again)

    sockets[3]!.simulateAbnormalClose(1006);
    vi.advanceTimersByTime(4000);
    expect(sockets).toHaveLength(5); // 4000ms

    sockets[4]!.simulateAbnormalClose(1006);
    vi.advanceTimersByTime(8000);
    expect(sockets).toHaveLength(6); // 8000ms

    sockets[5]!.simulateAbnormalClose(1006);
    vi.advanceTimersByTime(10_000);
    expect(sockets).toHaveLength(7); // 16000ms would be next but caps at 10s
  });

  it('applies jitter within ±20% of the nominal delay, clamped to the cap', () => {
    // random() = 0 -> jitter = -1 * nominal * 0.2 -> the low bound of the range.
    const low = makeClient({ random: () => 0 });
    low.client.connect();
    sockets[0]!.simulateOpen();
    sockets[0]!.simulateAbnormalClose(1006);
    vi.advanceTimersByTime(400 - 1); // 500ms * 0.8 = 400ms
    expect(sockets).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(2);

    // random() = 1 -> jitter = +1 * nominal * 0.2 -> the high bound of the range.
    const high = makeClient({ random: () => 1 });
    high.client.connect();
    sockets[2]!.simulateOpen();
    sockets[2]!.simulateAbnormalClose(1006);
    vi.advanceTimersByTime(600 - 1); // 500ms * 1.2 = 600ms
    expect(sockets).toHaveLength(3);
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(4);
  });

  it('never schedules a reconnect delay beyond the 10s cap, even with maximal jitter', () => {
    // Drive the nominal delay up to the 10s cap (500 -> 1000 -> 2000 -> 4000 -> 8000 -> 10000),
    // then close once more with random()=1 (the jitter formula's high bound): nominal*1.2 would
    // be 12s without clamping, but the cap must still hold.
    const { client } = makeClient({ random: () => 1 });
    client.connect();
    sockets[0]!.simulateOpen();
    for (let attempt = 0; attempt < 6; attempt += 1) {
      sockets[attempt]!.simulateAbnormalClose(1006);
      vi.advanceTimersByTime(10_000);
    }
    expect(sockets).toHaveLength(7);

    sockets[6]!.simulateAbnormalClose(1006);
    vi.advanceTimersByTime(10_000 - 1);
    expect(sockets).toHaveLength(7); // still capped at exactly 10s, not 10s * 1.2
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(8);
  });

  it('does not reconnect on close code 4401 (UNAUTHENTICATED)', () => {
    const { client, onStatusChange } = makeClient();
    client.connect();
    sockets[0]!.simulateOpen();

    sockets[0]!.simulateAbnormalClose(4401);

    expect(client.getStatus()).toBe('closed');
    expect(onStatusChange).toHaveBeenCalledWith('closed');
    vi.advanceTimersByTime(60_000);
    expect(sockets).toHaveLength(1);
  });

  it.each([4403, 4404])('does not reconnect on close code %d', (code) => {
    const { client } = makeClient();
    client.connect();
    sockets[0]!.simulateOpen();

    sockets[0]!.simulateAbnormalClose(code);

    expect(client.getStatus()).toBe('closed');
    vi.advanceTimersByTime(60_000);
    expect(sockets).toHaveLength(1);
  });

  it('never sends a frame other than resume', () => {
    const { client } = makeClient();
    client.connect();
    sockets[0]!.simulateOpen();
    sockets[0]!.simulateMessage({ type: 'resume_complete', replayed_count: 0, last_seq_no: 5, live: true });
    sockets[0]!.simulateMessage({ type: 'event', ...makeEnvelope(6) });
    sockets[0]!.simulateMessage({ type: 'heartbeat', server_time_utc: '2026-09-21T10:00:20Z', last_seq_no: 9 });
    sockets[0]!.simulateAbnormalClose(1006);
    vi.advanceTimersByTime(500);
    sockets[1]!.simulateOpen();

    const allFramesEverSent = sockets.flatMap((socket) => socket.sent);
    expect(allFramesEverSent.length).toBeGreaterThan(0);
    for (const frame of allFramesEverSent) {
      expect((frame as { type: string }).type).toBe('resume');
    }
  });

  it('disconnect() closes normally and does not reconnect', () => {
    const { client } = makeClient();
    client.connect();
    sockets[0]!.simulateOpen();

    client.disconnect();

    expect(client.getStatus()).toBe('closed');
    vi.advanceTimersByTime(60_000);
    expect(sockets).toHaveLength(1);
  });
});
