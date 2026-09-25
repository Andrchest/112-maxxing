// I4 E27 (docs/hld/71-i4-wave4.md §71.4, D32): the TLS edge, checked from a real browser.
//
// Browsers grant the microphone only in a secure context; a classroom PC opening
// http://<server-LAN-IP> is not one. These tests open the UI through the Caddy edge at
// https://<LAN-IP> (UI_BASE — deliberately a non-loopback address: `localhost` is a secure context
// even over plain http, so it would prove nothing) and assert:
//   1. window.isSecureContext, a real getUserMedia, and Vite's HMR socket over wss:// through the edge;
//   2. (control, when UI_INSECURE_BASE is set) the same UI over plain http on a non-loopback address
//      is NOT a secure context — so assertion 1 is the edge's doing;
//   3. the ДДС phone widget joins LiveKit over wss://<edge>/rtc and its WebRTC transport connects,
//      with the realtime channel on wss:// too.
//
// Needs the stack already running behind the edge (docs/RUNBOOK.md, «HTTPS в классе» → "Browser
// check"); skipped unless UI_BASE is https. Chromium trusts the local CA the way a classroom PC
// does after the teacher installed it: SIM_EDGE_CA_CERT names infra/certs/ca.crt and the browser is
// told to trust exactly that CA's public key (`--ignore-certificate-errors-spki-list`, which
// matches a key anywhere in the served chain — make-certs.sh serves leaf + CA). Any other
// certificate still fails the navigation. Fake audio devices stand in for a headset.
import { expect, test, type Page } from '@playwright/test';
import { createHash, X509Certificate } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { login, requireSeedPasswords } from './support';

const UI_BASE = process.env.UI_BASE ?? '';
const INSECURE_BASE = process.env.UI_INSECURE_BASE ?? '';
const CA_CERT = process.env.SIM_EDGE_CA_CERT ?? '';
const SEED_INSTRUCTOR_PASSWORD = process.env.SIM_SEED_INSTRUCTOR_PASSWORD ?? '';

/** base64(sha256(SubjectPublicKeyInfo)) — the form Chromium's SPKI allow-list takes. */
function spkiHash(pemPath: string): string {
  const der = new X509Certificate(readFileSync(pemPath)).publicKey.export({ type: 'spki', format: 'der' });
  return createHash('sha256').update(der).digest('base64');
}

function isLoopback(hostname: string): boolean {
  return hostname === 'localhost' || hostname.startsWith('127.') || hostname === '[::1]';
}

test.skip(!UI_BASE.startsWith('https://'), 'UI_BASE must be the edge, https://<LAN-IP>[:port] (RUNBOOK «HTTPS в классе»)');

test.use({
  launchOptions: {
    args: [
      ...(CA_CERT ? [`--ignore-certificate-errors-spki-list=${spkiHash(CA_CERT)}`] : []),
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
    ],
  },
});

test.describe.configure({ mode: 'serial' });

test('https://<LAN-IP> through the edge is a secure context: microphone allowed, HMR over wss://', async ({ page }) => {
  expect(CA_CERT, 'SIM_EDGE_CA_CERT must name infra/certs/ca.crt').not.toBe('');
  const edge = new URL(UI_BASE);
  expect(isLoopback(edge.hostname), 'UI_BASE must not be a loopback address').toBe(false);

  let hmrUrl = '';
  const hmrFrames: string[] = [];
  page.on('websocket', (socket) => {
    if (new URL(socket.url()).pathname !== '/') return; // Vite's HMR socket lives at the root
    hmrUrl = socket.url();
    socket.on('framereceived', (frame) => hmrFrames.push(String(frame.payload)));
  });

  const response = await page.goto('/login');
  expect(response?.ok()).toBe(true);
  expect(new URL(page.url()).origin).toBe(edge.origin);
  expect(await page.evaluate(() => window.isSecureContext)).toBe(true);

  // The prompt a teacher would see; the fake-UI flag answers it, so a track comes back.
  const audioTracks = await page.evaluate(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const count = stream.getAudioTracks().length;
    stream.getTracks().forEach((track) => track.stop());
    return count;
  });
  expect(audioTracks).toBe(1);

  // HMR through the proxy (§71.4 acceptance): Vite's client dials wss://<page host:port>/.
  await expect.poll(() => hmrFrames.some((frame) => frame.includes('"type":"connected"'))).toBe(true);
  expect(hmrUrl.startsWith(`wss://${edge.host}/`)).toBe(true);
});

test('control: the same UI over plain http on a non-loopback address is NOT a secure context', async ({ page }) => {
  test.skip(!INSECURE_BASE, 'set UI_INSECURE_BASE=http://<non-loopback address of the Vite server> to run the control');
  expect(isLoopback(new URL(INSECURE_BASE).hostname)).toBe(false);
  await page.goto(`${INSECURE_BASE}/login`);
  expect(await page.evaluate(() => window.isSecureContext)).toBe(false);
  // No secure context, no getUserMedia at all — the classroom failure E27 exists to fix.
  expect(await page.evaluate(() => typeof navigator.mediaDevices)).toBe('undefined');
});

/** Creates and starts a `street-rubbish-fire` session with the seeded trainee as ДДС (SINGLE_ROLE,
 * the claimant call ON), as the instructor, through the edge — `fetch` inside the page, so the
 * request rides the same trusted TLS connection the UI does. Returns the session id. */
async function createDdsSession(page: Page): Promise<string> {
  await page.goto('/login');
  return page.evaluate(async (password) => {
    async function call<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers.Authorization = `Bearer ${token}`;
      const response = await fetch(path, { ...init, headers });
      if (!response.ok) throw new Error(`${init.method ?? 'GET'} ${path} -> ${response.status} ${await response.text()}`);
      return (await response.json()) as T;
    }
    type Listing<Item> = { items: Item[] };
    const auth = await call<{ access_token: string }>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username: 'instructor', password }),
    });
    const token = auth.access_token;
    const scenarios = await call<Listing<{ slug: string; scenario_id: string }>>('/api/v1/scenarios', {}, token);
    const scenario = scenarios.items.find((item) => item.slug === 'street-rubbish-fire');
    if (!scenario) throw new Error('street-rubbish-fire is not imported');
    const versions = await call<Listing<{ id: string }>>(`/api/v1/scenarios/${scenario.scenario_id}/versions`, {}, token);
    const users = await call<Listing<{ id: string; username: string }>>('/api/v1/users?role=TRAINEE', {}, token);
    const trainee = users.items.find((user) => user.username === 'trainee');
    if (!trainee) throw new Error('the seeded trainee account is missing');
    const session = await call<{ id: string }>(
      '/api/v1/sessions',
      {
        method: 'POST',
        body: JSON.stringify({
          scenario_version_id: versions.items[0].id,
          session_mode: 'SINGLE_ROLE',
          participants: [{ user_id: trainee.id, assigned_role_type: 'DDS' }],
          variants: { dds_brigade_call: 'ON' },
        }),
      },
      token,
    );
    await call<unknown>(`/api/v1/sessions/${session.id}/start`, { method: 'POST' }, token);
    return session.id;
  }, SEED_INSTRUCTOR_PASSWORD);
}

test('ДДС phone widget joins LiveKit over wss:// through the edge', async ({ browser }) => {
  requireSeedPasswords();
  const edge = new URL(UI_BASE);

  const instructorContext = await browser.newContext({ locale: 'ru-RU' });
  const sessionId = await createDdsSession(await instructorContext.newPage());
  await instructorContext.close();

  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, locale: 'ru-RU' });
  const page = await context.newPage();
  // Records every RTCPeerConnection's state, so the test sees the WebRTC transport itself connect
  // (DTLS-SRTP to the SFU), not only the signalling socket.
  await page.addInitScript(() => {
    const states: string[] = [];
    (window as unknown as { __pcStates: string[] }).__pcStates = states;
    const Native = window.RTCPeerConnection;
    window.RTCPeerConnection = class extends Native {
      constructor(...args: ConstructorParameters<typeof RTCPeerConnection>) {
        super(...args);
        this.addEventListener('connectionstatechange', () => states.push(this.connectionState));
      }
    } as typeof RTCPeerConnection;
  });
  const sockets: { url: string; frames: number; closed: boolean }[] = [];
  page.on('websocket', (socket) => {
    const entry = { url: socket.url(), frames: 0, closed: false };
    sockets.push(entry);
    socket.on('framereceived', () => (entry.frames += 1));
    socket.on('close', () => (entry.closed = true));
  });

  await login(page, 'trainee');
  await page.goto(`/dds/${sessionId}`);
  await page.getByRole('button', { name: 'Позвонить заявителю' }).click();
  // The fake claimant answers a few seconds later (I3 E6b), and only then does the widget join.
  await expect(page.getByText('Разговор', { exact: true })).toBeVisible({ timeout: 20_000 });

  const rtcPrefix = `wss://${edge.host}/rtc`;
  await expect
    .poll(() => sockets.some((socket) => socket.url.startsWith(rtcPrefix) && socket.frames > 0), { timeout: 15_000 })
    .toBe(true);
  await expect
    .poll(() => page.evaluate(() => (window as unknown as { __pcStates: string[] }).__pcStates.includes('connected')), {
      timeout: 15_000,
    })
    .toBe(true);
  await expect(page.getByText('Голосовая связь недоступна — звонок продолжается без звука.')).toHaveCount(0);

  // The realtime channel took the same edge, as wss://.
  const realtime = sockets.find((socket) => socket.url.startsWith(`wss://${edge.host}/api/v1/ws/sessions/${sessionId}`));
  expect(realtime?.frames ?? 0).toBeGreaterThan(0);
  // Nothing on this page dialled a plain ws:// or http:// address.
  expect(sockets.filter((socket) => !socket.url.startsWith('wss://'))).toEqual([]);

  await page.getByRole('button', { name: 'Положить трубку' }).click();
  await expect(page.getByText('Звонок завершён', { exact: true })).toBeVisible({ timeout: 10_000 });
  await context.close();
});
