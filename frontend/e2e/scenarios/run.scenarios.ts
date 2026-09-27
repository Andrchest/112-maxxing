// I6 SCENARIOS: the Playwright entry point — one test per scenario, in order, one worker. A broken
// scenario fails its own test only; the next scenario still runs (they are independent). Select
// with E2E_SCENARIO=S03 (or a comma list, S01,S03). The summary is written by `summary.ts`.
import { test } from '@playwright/test';
import { ALL_SCENARIOS } from './index';
import { runScenario, runnerEnvFromProcess } from './runner';

const wanted = (process.env.E2E_SCENARIO ?? '')
  .split(',')
  .map((id) => id.trim().toUpperCase())
  .filter((id) => id !== '');
const selected = wanted.length === 0 ? ALL_SCENARIOS : ALL_SCENARIOS.filter((item) => wanted.includes(item.id));
if (selected.length === 0) throw new Error(`нет сценариев с id ${wanted.join(', ')}`);

for (const scenario of selected) {
  test(`${scenario.id} ${scenario.title}`, async ({ browser }) => {
    const result = await runScenario(browser, scenario, runnerEnvFromProcess());
    if (result.failure) {
      const { stepId, notSeen, error } = result.failure;
      throw new Error(`СЛОМАН на шаге ${stepId}: не видно «${notSeen}» (${error})`);
    }
  });
}
