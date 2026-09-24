// I3 E7a: shared helpers for the reference-look screenshot comparison (`_common.md`'s fake-
// provider UI run recipe). Login and session-creation selectors mirror the manual UI-check
// scripts that already proved this flow against a real backend
// (`/tmp/teamwork-112-maxxing/reports/i3/ui-check/scripts/lib.js` and the E3c UI-check scripts),
// not reinvented here.
import { expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

export const SHOTS_DIR = '/tmp/teamwork-112-maxxing/reports/i3/E7a-shots';

const SEED_PASSWORD: Record<'trainee' | 'instructor', string | undefined> = {
  trainee: process.env.SIM_SEED_TRAINEE_PASSWORD,
  instructor: process.env.SIM_SEED_INSTRUCTOR_PASSWORD,
};

export function requireSeedPasswords(): void {
  if (!SEED_PASSWORD.trainee || !SEED_PASSWORD.instructor) {
    throw new Error(
      'SIM_SEED_TRAINEE_PASSWORD / SIM_SEED_INSTRUCTOR_PASSWORD are not set — start the fake-provider ' +
        'backend per docs/RUNBOOK.md’s "E2E screenshot comparison" section before running npm run e2e.',
    );
  }
}

export async function login(page: Page, role: 'trainee' | 'instructor'): Promise<void> {
  await page.goto('/login');
  await page.fill('#login-username', role);
  await page.fill('#login-password', SEED_PASSWORD[role]!);
  await page.click('button[type=submit]');
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 15_000 });
}

/** The Zustand auth store’s bearer token (`entities/session/auth-store.ts`,
 * `shared/config`’s `AUTH_TOKEN_STORAGE_KEY`), for the rare authenticated `page.request` call this
 * suite makes directly (fetching the v2 card schema to build a v2 card fixture — see
 * `reference-look.spec.ts`). */
export async function authToken(page: Page): Promise<string> {
  const token = await page.evaluate(() => sessionStorage.getItem('auth.token'));
  if (!token) throw new Error('no auth token in sessionStorage after login');
  return token;
}

/** Creates and starts a lesson-less session through the instructor UI (the same form and
 * selectors `/tmp/teamwork-112-maxxing/reports/i3/E3c-shots/scripts/{a1,b1}-*.js` already used
 * successfully against a real backend), returns the created session id. */
export async function createAndStartSession(
  page: Page,
  opts: { scenarioIndex: number; mode: string },
): Promise<string> {
  await page.goto('/instructor');
  await page.selectOption('#instructor-scenario', { index: opts.scenarioIndex });
  await page.selectOption('#instructor-version', { index: 1 });
  await page.selectOption('#instructor-mode', opts.mode);
  await page.selectOption('#instructor-participant-0', { index: 1 });
  await page.getByRole('button', { name: 'Создать занятие' }).click();
  await page.waitForTimeout(1500);
  const links = await page.$$eval('a', (as) => as.map((a) => a.getAttribute('href') ?? ''));
  const sessionLink = links.find((href) => /[0-9a-f-]{36}/.test(href));
  if (!sessionLink) throw new Error('no session link found after createSession');
  const sessionId = sessionLink.match(/[0-9a-f-]{36}/)![0];
  await page.getByRole('button', { name: 'Начать занятие' }).click();
  await page.waitForTimeout(1000);
  return sessionId;
}

/**
 * Clips a small region near the far edge of `locator`'s own box — deliberately away from any text
 * or icon the element renders, landing on the element's own solid background fill (every element
 * this suite samples is a single flat `background-color`, never a gradient or image, D20) — and
 * asserts it against the checked-in reference crop under `tolerance` (a pixelmatch-style
 * `maxDiffPixelRatio`, I3 E7a brief). Also saves the *full* element screenshot into
 * `SHOTS_DIR` for the report's side-by-side table.
 */
export async function compareSwatch(
  page: Page,
  locatorSelector: string,
  opts: {
    referenceName: string;
    shotName: string;
    /** Size of the checked-in reference crop (`e2e/reference/<referenceName>`) — the clipped
     * product region must match it exactly (Playwright's screenshot matcher requires equal
     * dimensions). */
    size: { width: number; height: number };
    /** Offset of the clip's top-left corner from the element's own top-left corner, in CSS px.
     * Defaults to a few px inset from the element's own right edge, vertically centred — every
     * element this suite samples is a bar/button whose content (label, chips, tags) is
     * left-anchored with padding on the right (D12's Tailwind spacing scale), so that corner is
     * reliably past any text/icon and still short of the rounded-corner pixels. Override only
     * when an element's own content genuinely fills its right edge. */
    offset?: { x: number; y: number };
    tolerance?: number;
  },
): Promise<void> {
  const locator = page.locator(locatorSelector).first();
  await expect(locator).toBeVisible();
  // The services/tab bars are pinned as the last, non-scrolling flex child of `AppShell`'s
  // `fillHeight` `main` (I3 E7a carry-over fix (a), manager review) — the card content above them
  // lives in its own scroll region. Scrolling that region to its end first mirrors "the trainee
  // scrolled down" for the header-strip elements this helper also samples.
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) throw new Error(`no bounding box for ${locatorSelector}`);

  mkdirSync(SHOTS_DIR, { recursive: true });
  await locator.screenshot({ path: path.join(SHOTS_DIR, `${opts.shotName}-full.png`) });

  const offset = opts.offset ?? {
    x: box.width - opts.size.width - 1,
    y: box.height / 2 - opts.size.height / 2,
  };
  const clip = {
    x: Math.round(box.x + offset.x),
    y: Math.round(box.y + offset.y),
    width: opts.size.width,
    height: opts.size.height,
  };
  const buffer = await page.screenshot({ clip });
  const { writeFileSync } = await import('node:fs');
  writeFileSync(path.join(SHOTS_DIR, `${opts.shotName}-swatch.png`), buffer);

  expect(buffer).toMatchSnapshot(opts.referenceName, { maxDiffPixelRatio: opts.tolerance ?? 0.1 });
}

/**
 * I3 E7a (manager review, item 5): a whole-element visual-regression comparison, catching a
 * LAYOUT regression (an element moved, resized or restructured) the small colour swatches above
 * cannot — those only sample a few pixels of solid background. Unlike `compareSwatch`, this
 * compares the product against its OWN prior screenshot (a checked-in baseline under
 * `e2e/reference/`, generated with `npx playwright test --update-snapshots` and reviewed like any
 * other change), not against the organizer's file — a different real system's screenshot could
 * never pass a whole-element pixel comparison regardless of how faithful the colours are (fonts/
 * icons/exact spacing differ). `mask` blanks out genuinely non-deterministic content (the session's
 * own `display_number`, the fill-timer's ticking digits) before the compare, so the test still
 * catches a real layout change without flaking on data that legitimately differs run to run.
 */
export async function compareRegion(
  page: Page,
  locatorSelector: string,
  opts: { name: string; mask?: string[]; tolerance?: number },
): Promise<void> {
  const locator = page.locator(locatorSelector).first();
  await expect(locator).toBeVisible();
  await locator.scrollIntoViewIfNeeded();
  await expect(locator).toHaveScreenshot(opts.name, {
    mask: (opts.mask ?? []).map((selector) => page.locator(selector)),
    maxDiffPixelRatio: opts.tolerance ?? 0.05,
  });
}
