// I6 SCENARIOS: Playwright's global teardown — gathers every `<id>.json` the runner wrote into
// `summary.md` (a table: scenario, РАБОТАЕТ/СЛОМАН, failed step and what was not seen, duration)
// and `summary.json`, in the results dir.
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import type { ScenarioResult } from './runner';

function cell(value: string): string {
  return value.replace(/\|/g, '\\|').replace(/\n/g, ' ');
}

export function renderSummary(results: ScenarioResult[], baseUrl: string, startedAt: string): string {
  const working = results.filter((item) => item.status === 'РАБОТАЕТ').length;
  const lines = [
    '# Прогон тестовых сценариев',
    '',
    `Стенд: ${baseUrl}. Начало: ${startedAt}. РАБОТАЕТ: ${working}, СЛОМАН: ${results.length - working}.`,
    '',
    '| Сценарий | Статус | Шаг | Что не увидели | Длительность, с |',
    '|---|---|---|---|---|',
    ...results.map((item) =>
      [
        `${item.id} ${item.title}`,
        item.status,
        item.failure ? item.failure.stepId : '—',
        item.failure ? `${item.failure.notSeen} — ${item.failure.error}` : '—',
        (item.durationMs / 1000).toFixed(1),
      ]
        .map(cell)
        .join(' | ')
        .replace(/^/, '| ')
        .replace(/$/, ' |'),
    ),
    '',
  ];
  const broken = results.filter((item) => item.failure);
  if (broken.length > 0) {
    lines.push('## Где сломалось', '');
    for (const item of broken) {
      const failure = item.failure!;
      lines.push(
        `### ${item.id} ${item.title}`,
        '',
        `- Шаг: ${failure.stepId} — ${failure.do}`,
        `- Не увидели: ${failure.notSeen}`,
        `- Ошибка: ${failure.error}`,
        `- Адрес страницы: ${failure.url}`,
        `- Снимок экрана: ${failure.screenshot ?? 'не удалось снять'}`,
        '',
      );
    }
  }
  const failedCleanups = results.flatMap((item) => item.cleanup.filter((c) => !c.ok).map((c) => `${item.id}: ${c.label} — ${c.error}`));
  if (failedCleanups.length > 0) lines.push('## Уборка не удалась', '', ...failedCleanups.map((line) => `- ${line}`), '');
  return lines.join('\n');
}

export default function globalTeardown(): void {
  const dir = process.env.E2E_RESULTS_DIR;
  if (!dir || !existsSync(dir)) return;
  const order = (id: string) => Number(id.replace(/\D/g, ''));
  const results = readdirSync(dir)
    .filter((name) => /^S\d+\.json$/.test(name))
    .map((name) => JSON.parse(readFileSync(path.join(dir, name), 'utf8')) as ScenarioResult)
    .sort((a, b) => order(a.id) - order(b.id));
  const startedAt = process.env.E2E_RUN_STARTED_AT ?? '';
  const baseUrl = process.env.E2E_BASE_URL ?? '';
  writeFileSync(path.join(dir, 'summary.json'), JSON.stringify({ baseUrl, startedAt, results }, null, 2));
  const markdown = renderSummary(results, baseUrl, startedAt);
  writeFileSync(path.join(dir, 'summary.md'), markdown);
  console.log(`\n${markdown}\nИтоги: ${path.join(dir, 'summary.md')}`);
}
