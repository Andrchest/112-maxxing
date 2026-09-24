// I3 E7a (D20, C9): screenshot comparison of the reference look (the 112 card and the ДДС
// workstation) against the organizer's own extracted screenshots. The comparison is per screen
// region under a stated tolerance, not whole-page pixel equality (fonts/OS chrome differ between
// this app and the organizer's real system) — `e2e/reference/*.png` are small, near-solid colour
// crops of the organizer files (see `e2e/reference/README.md` for provenance), and
// `snapshotPathTemplate` points straight at that directory so those checked-in files ARE the
// expected baseline; nothing here writes or updates them (no `--update-snapshots` in `npm run
// e2e`). Needs the fake-provider backend + Vite dev server already running
// (`docs/RUNBOOK.md`'s "E2E screenshot comparison" section) — this config never starts them
// itself (`webServer` omitted), and the gate does not run this suite (no backend in `vitest`).
//
// Playwright version pinned in `package.json` to the one whose Chromium build (`chromium-1187` /
// `chromium_headless_shell-1187`) is already cached in `~/.cache/ms-playwright` (I3 E7a brief,
// A-12) — `npm run e2e` sets `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` so `npm install` never re-fetches
// a browser build.
import { defineConfig, devices } from '@playwright/test';

const BASE_URL = process.env.UI_BASE ?? 'http://127.0.0.1:5174';

export default defineConfig({
  testDir: './e2e',
  // `.e2e.ts`, not `.spec.ts` — vitest's own default `test.include` glob
  // (`**/*.{test,spec}.*`) would otherwise collect these files too (they use `@playwright/test`'s
  // `test`/`expect`, not vitest's), so this naming keeps the two runners' collections disjoint
  // without touching `vite.config.ts`'s vitest options.
  testMatch: '**/*.e2e.ts',
  snapshotPathTemplate: '{testDir}/reference/{arg}{ext}',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  reporter: [['list']],
  use: {
    baseURL: BASE_URL,
    viewport: { width: 1920, height: 1080 },
    locale: 'ru-RU',
    screenshot: 'off',
    trace: 'off',
    video: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
