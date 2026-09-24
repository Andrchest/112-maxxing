// I3 E7a (D20, C9): Playwright screenshot comparison of the reference look — the 112 card and the
// ДДС memo workstation — against colour swatches cropped from the organizer's own extracted
// screenshots (`e2e/reference/`). The comparison is per screen region under a stated tolerance
// (`compareSwatch`, `./support.ts`), not whole-page pixel equality. Needs the fake-provider
// backend + Vite dev server already running (`docs/RUNBOOK.md`'s "E2E screenshot comparison"
// section); this suite never starts them.
//
// The 112 card only ever runs a v2 schema once a v2-schema *operator* scenario exists (none does
// yet — every current example scenario is either v1 with an OPERATOR_112 stage, `apartment-fire`,
// or v2 DDS-only, `street-rubbish-fire`, I3 E3a′'s own TODO), so the first test drives a real
// `apartment-fire` operator call (login, answer — a genuine `answer_call` command, so the call
// state and fill-timer deadline are real server data) and then swaps only the snapshot's `card`
// for one built from the live v2 schema (`GET /reference/card-schema/v2`) through `page.route` —
// the same technique the I3 E3b task report already used and verified end-to-end against this
// backend (`/tmp/teamwork-112-maxxing/reports/i3/E3b.md` §3). No repo file is read by the
// intercept; it is pure test scaffolding, and every other field of the snapshot (call state,
// session, timers) stays the server's real response. The second test needs no such fake — the DDS
// memo workstation already has a real v2 example scenario (`street-rubbish-fire`, I3 E5c).
import { expect, test } from '@playwright/test';
import { authToken, compareRegion, compareSwatch, createAndStartSession, login, requireSeedPasswords } from './support';

test.describe.configure({ mode: 'serial' });

test('112 card — reference colours (orange services bar, blue selected tag, fill timer)', async ({ browser }) => {
  requireSeedPasswords();

  const instructorContext = await browser.newContext({ viewport: { width: 1920, height: 1080 }, locale: 'ru-RU' });
  const instructorPage = await instructorContext.newPage();
  await login(instructorPage, 'instructor');
  const sessionId = await createAndStartSession(instructorPage, { scenarioIndex: 1, mode: 'FULL_CYCLE_SINGLE_TRAINEE' });
  await instructorContext.close();

  const traineeContext = await browser.newContext({ viewport: { width: 1920, height: 1080 }, locale: 'ru-RU' });
  const page = await traineeContext.newPage();
  await login(page, 'trainee');
  await page.goto(`/operator/${sessionId}`);
  await page.waitForTimeout(1500);
  // A real `answer_call` command (not faked) — the fill-timer's deadline and the call state stay
  // genuine server data through the `card` swap below.
  await page.getByRole('button', { name: 'Ответить' }).click();
  await page.waitForTimeout(1500);

  const token = await authToken(page);
  const schemaResponse = await page.request.get('/api/v1/reference/card-schema/v2', {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(schemaResponse.ok()).toBe(true);
  const schema = (await schemaResponse.json()) as { field_specs: unknown[] };

  await page.route('**/api/v1/sessions/*/snapshot', async (route) => {
    const response = await route.fetch();
    const json = await response.json();
    if (json.card) {
      json.card.field_specs = schema.field_specs;
      json.card.card_schema = 'v2';
      // incident.types '1' -> the q_fire questionnaire group; q.fire.where 'на улице' selects one
      // TOGGLE_SET tag (blue when selected, D20) — option codes copied verbatim from
      // reference/card-schema/v2.yaml (read only for this literal; no repo file touched by the
      // route handler itself).
      json.card.values = { 'incident.types': ['1'], 'q.fire.where': ['на улице'] };
    }
    await route.fulfill({ response, json });
  });
  await page.reload();
  await page.waitForTimeout(1500);
  await expect(page.locator('[data-slot="services-bar"]')).toBeVisible();
  await expect(page.locator('[data-slot="card-fill-timer"]')).toBeVisible();

  await compareSwatch(page, '[data-slot="services-bar"]', {
    referenceName: 'card-services-bar-orange.png',
    shotName: 'card-01-services-bar',
    size: { width: 20, height: 20 },
  });

  await compareSwatch(page, '[data-slot="card-fill-timer"]', {
    referenceName: 'card-fill-timer.png',
    shotName: 'card-02-fill-timer',
    size: { width: 10, height: 16 },
  });

  await compareSwatch(page, '[data-slot="card-group-q_fire"] button[aria-pressed="true"]', {
    referenceName: 'card-selected-tag-blue.png',
    shotName: 'card-03-selected-tag',
    // Small — a toggle button's own text can run close to its `px-2.5` padding edge at this
    // font size, so a wider swatch risks catching anti-aliased glyph pixels.
    size: { width: 8, height: 6 },
  });

  await compareSwatch(page, '[data-slot="card-group-q_fire"] [data-slot="card-header"]', {
    referenceName: 'card-questionnaire-title-bar.png',
    shotName: 'card-04-questionnaire-title-bar',
    size: { width: 20, height: 9 },
  });

  // I3 E7a (manager review, item 5): whole-element layout regions, catching a structural
  // regression the colour swatches above cannot (they only sample a few pixels each). The
  // session's own `display_number` and the timer's ticking digits are masked — everything else
  // (phone fields, flag buttons, the bar's own shape/padding/colour) must match the checked-in
  // baseline (`e2e/reference/*-region.png`, generated with `--update-snapshots`).
  await compareRegion(page, '[data-slot="card-header-strip"]', {
    name: 'card-header-strip-region.png',
    mask: ['[data-slot="card-number"]', '[data-slot="card-fill-timer"]'],
  });
  await compareRegion(page, '[data-slot="services-bar"]', {
    name: 'card-services-bar-region.png',
  });

  // Overdue state (D20: the timer turns red, `#FF0000`) — a second, deterministic reload with the
  // fill deadline forced to have already elapsed (`timers.fill_within_ms` overridden to 1 ms in
  // the SESSION_CREATED event's own payload the header timer reads, `use-fill-deadline.ts`),
  // rather than waiting out the real ~180 s default.
  await page.route('**/api/v1/sessions/*/events*', async (route) => {
    const response = await route.fetch();
    const json = await response.json();
    if (route.request().url().includes('event_type=SESSION_CREATED')) {
      // `apartment-fire` has no explicit `timers` block, so the real `SESSION_CREATED` query
      // here already comes back empty (the frontend falls back to the domain default,
      // `use-fill-deadline.ts`) — inject a synthetic item instead of mutating one that isn't
      // there, forcing the fill deadline to have already elapsed (D20's red overdue state).
      json.items = [
        {
          seq_no: 1,
          event_type: 'SESSION_CREATED',
          timestamp_utc: new Date().toISOString(),
          monotonic_offset_ms: 0,
          payload: { timers: { fill_within_ms: 1 } },
        },
      ];
    }
    await route.fulfill({ response, json });
  });
  await page.reload();
  await page.waitForTimeout(1500);
  await expect(page.locator('[data-slot="card-fill-timer"][data-overdue="true"]')).toBeVisible();
  // The base fill is red always (D20, manager review) — the overdue state's own visual delta is
  // a static ring, not a second background colour, so it shows up here as a DOM class, not as a
  // different swatch colour (the fill itself is identical to the non-overdue swatch above).
  await expect(page.locator('[data-slot="card-fill-timer"]')).toHaveClass(/ring-2/);

  await compareSwatch(page, '[data-slot="card-fill-timer"]', {
    referenceName: 'card-fill-timer-overdue.png',
    shotName: 'card-05-fill-timer-overdue',
    size: { width: 10, height: 16 },
  });
});

test('ДДС memo workstation — reference colours (services tab bar, dark title bar)', async ({ browser }) => {
  requireSeedPasswords();

  const instructorContext = await browser.newContext({ viewport: { width: 1920, height: 1080 }, locale: 'ru-RU' });
  const instructorPage = await instructorContext.newPage();
  await login(instructorPage, 'instructor');
  // street-rubbish-fire: schema v2, role_chain [DDS], GENERATED_CARD — the trainee lands on the
  // DDS memo console directly, no operator stage (I3 E5c's own real UI run used this scenario).
  const sessionId = await createAndStartSession(instructorPage, { scenarioIndex: 2, mode: 'SINGLE_ROLE' });
  await instructorContext.close();

  const traineeContext = await browser.newContext({ viewport: { width: 1920, height: 1080 }, locale: 'ru-RU' });
  const page = await traineeContext.newPage();
  await login(page, 'trainee');
  await page.goto(`/dds/${sessionId}`);
  await page.waitForTimeout(2000);

  await expect(page.locator('[data-slot="dds-services-tab-bar"]')).toBeVisible();

  await compareSwatch(page, '[data-slot="dds-services-tab-bar"]', {
    referenceName: 'dds-services-tab-bar.png',
    shotName: 'dds-01-services-tab-bar',
    size: { width: 20, height: 13 },
  });

  await compareSwatch(page, '[data-slot="dds-questionnaire-bar"]', {
    referenceName: 'card-questionnaire-title-bar.png',
    shotName: 'dds-02-questionnaire-title-bar',
    size: { width: 20, height: 9 },
  });

  // I3 E7a (manager review, item 5): whole-element layout regions (see the 112 card test above
  // for why) — the DDS header strip and the services tab bar, masking the session's own
  // `display_number`.
  await compareRegion(page, '[data-slot="dds-header-strip"]', {
    name: 'dds-header-strip-region.png',
    mask: ['[data-slot="dds-card-number"]'],
  });
  await compareRegion(page, '[data-slot="dds-services-tab-bar"]', {
    name: 'dds-services-tab-bar-region.png',
  });
});
