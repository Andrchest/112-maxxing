// I6 SCENARIOS: the scenario runner's own Playwright config (`make e2e-scenarios`; not part of
// `make gate` — it needs a running stand). Separate from `frontend/playwright.config.ts` (the
// reference-look screenshots), and its entry file is not a `*.e2e.ts`, so neither suite collects
// the other's tests. Env: E2E_BASE_URL, E2E_{ADMIN,INSTRUCTOR,TRAINEE}_{USER,PASS}, optional
// E2E_SCENARIO (S03 or S01,S03) and E2E_RESULTS_DIR.
import { defineConfig } from '@playwright/test';
import path from 'node:path';

// Set here, in the main process, before the worker starts: the worker and the teardown both
// inherit the same results dir.
const startedAt = new Date();
process.env.E2E_RUN_STARTED_AT ??= startedAt.toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' });
process.env.E2E_RESULTS_DIR ??= path.join(
  '/tmp/teamwork-112-maxxing/reports/i6/scenario-runs',
  startedAt.toISOString().replace(/[:.]/g, '-'),
);

export default defineConfig({
  testDir: '.',
  testMatch: 'run.scenarios.ts',
  globalTeardown: './summary.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  // Every step has its own 5 s visibility timeout; this only bounds a whole scenario (S08 waits
  // out a card timer).
  timeout: 15 * 60_000,
  reporter: [['list']],
  outputDir: path.join(process.env.E2E_RESULTS_DIR, 'playwright-output'),
  use: {
    // The full Chromium build in its new headless mode, not the stripped headless shell: only the
    // full build has the PDF viewer the «Справочная база» «Открыть» button opens (S12).
    channel: 'chromium',
    launchOptions: {
      // The ДДС phone asks for the microphone; a fake device answers, as a headset would.
      args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
    },
  },
});
