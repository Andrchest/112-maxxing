// I6 SCENARIOS: renders the scenario definitions as the Russian text a tester follows —
// `docs/test-scenarios/00-instructions.md` (the rules, the table of contents) and one
// `docs/test-scenarios/SNN.md` per scenario. `doc.test.ts` checks the committed files are exactly
// this output; `make e2e-scenarios-doc` rewrites them after a definition changes.
import type { Actor, Scenario } from './dsl';

/** How each actor is named in the text (the tab the tester works in). */
export const ACTOR_LABELS: Record<Actor, string> = {
  admin: 'Администратор',
  instructor: 'Преподаватель',
  trainee: 'Стажёр (учётная запись trainee)',
  newTrainee: 'Новый стажёр',
  secondInstructor: 'Второй преподаватель',
  tempUser: 'Проверяемый пользователь',
};

export function actorLabel(actor: Actor): string {
  return ACTOR_LABELS[actor] ?? actor;
}

function cell(value: string): string {
  return value.replace(/\|/g, '\\|').replace(/\n/g, ' ');
}

export function scenarioFileName(scenario: Scenario): string {
  return `${scenario.id}.md`;
}

/** I6 HTTP: `omitSecureOnly` drops every `secureOnly` step (the http bundle) instead of just
 * marking it — step ids never shift, since `scenario()` numbers them before this filter runs. */
export interface RenderOptions {
  omitSecureOnly?: boolean;
}

export function renderScenario(scenario: Scenario, options: RenderOptions = {}): string {
  const steps = options.omitSecureOnly ? scenario.steps.filter((step) => !step.secureOnly) : scenario.steps;
  const lines: string[] = [
    `# ${scenario.id}. ${scenario.title}`,
    '',
    '<!-- Файл создан из frontend/e2e/scenarios (make e2e-scenarios-doc). Правьте определения, не этот файл. -->',
    '',
    `**Цель.** ${scenario.purpose}`,
    '',
    `**Вкладки (роли):** ${scenario.roles.map(actorLabel).join(', ')}.`,
    '',
    '**Перед началом:**',
    '',
    ...scenario.preconditions.map((item) => `- ${item}`),
    '',
    '**Тестовые данные** (`<суффикс>` — придумайте в начале сценария, см. 00-instructions.md):',
    '',
    ...scenario.testData.map((item) => `- ${item}`),
    '',
    '## Шаги',
    '',
    '| Шаг | Что сделать | Должно быть видно |',
    '|---|---|---|',
  ];
  for (const step of steps) {
    const todo = `**${actorLabel(step.actor)}:** ${step.do}${step.secureOnly ? ' *(только https)*' : ''}`;
    const seen = [
      ...(step.wait ? [`*Ждать до ${Math.round(step.wait.timeoutMs / 1000)} с: ${step.wait.why}.*`] : []),
      ...step.expect.map((item) => `• ${item.see}`),
    ].join('<br>');
    lines.push(`| ${step.id} | ${cell(todo)} | ${cell(seen)} |`);
  }
  lines.push(
    '',
    '## Уборка (выполнить всегда, даже если сценарий СЛОМАН)',
    '',
    ...(scenario.cleanup.length > 0 ? scenario.cleanup.map((item) => `- ${item}`) : ['- Ничего убирать не нужно.']),
    '',
  );
  return lines.join('\n');
}

export function renderInstructions(scenarios: Scenario[]): string {
  return [
    '# Тестовые сценарии тренажёра 112: инструкция для проверяющего',
    '',
    '<!-- Файл создан из frontend/e2e/scenarios/doc.ts (make e2e-scenarios-doc). Правьте генератор, не этот файл. -->',
    '',
    'Вы проверяете веб-интерфейс тренажёра 112 через браузер, глядя на экран. Каждый сценарий —',
    'отдельный файл `SNN.md` с таблицей шагов. Ваша задача — пройти шаги по порядку и честно',
    'отметить, работает сценарий или сломан. Ничего не чините, не обходите и не придумывайте.',
    '',
    '## Стенд и учётные записи',
    '',
    '- Адрес стенда и логины/пароли трёх учётных записей — `admin` (администратор), `instructor`',
    '  (преподаватель), `trainee` (стажёр, на экране «Стажёр») — даны отдельно (файл `access.md`',
    '  рядом с этими файлами или переменные окружения `E2E_BASE_URL`, `E2E_ADMIN_USER`/`E2E_ADMIN_PASS`,',
    '  `E2E_INSTRUCTOR_USER`/`E2E_INSTRUCTOR_PASS`, `E2E_TRAINEE_USER`/`E2E_TRAINEE_PASS`). В сценариях',
    '  пароли не пишутся: «пароль преподавателя» значит пароль учётной записи `instructor` оттуда.',
    '- На стенде не запущены голосовые модели. Это нормально: сценарий S16 проверяет, что интерфейс',
    '  честно это показывает («Готовность: Не готово», «Стенограмма недоступна.»).',
    '',
    '## Вкладки и роли',
    '',
    '- Каждая роль работает в своей вкладке браузера. Открывайте новую вкладку и набирайте адрес',
    '  стенда заново (не «Дублировать вкладку»): вход хранится отдельно в каждой вкладке, поэтому',
    '  роли не мешают друг другу. В таблице шагов перед действием написано, в чьей вкладке оно',
    '  выполняется: **Администратор:**, **Преподаватель:**, **Стажёр …:**, **Новый стажёр:** и т. п.',
    '- «Новый стажёр», «Второй преподаватель», «Проверяемый пользователь» — учётные записи, которые',
    '  сценарий сам создаёт на шаге администратора; их логин и пароль указаны в «Тестовых данных».',
    '',
    '## Где что на экране',
    '',
    '- **Шапка** — тёмная полоса вверху каждой страницы после входа. Слева направо: «← Назад»',
    '  (только на вложенных страницах: занятие, обзор карточки, отчёт, рабочее место ДДС),',
    '  «Тренажёр 112», название раздела, **меню роли** (пункты-ссылки; текущий раздел подсвечен);',
    '  справа — имя пользователя, роль, значки соединения/готовности и кнопка «Выйти».',
    '- **Меню роли:** у преподавателя «Занятия · Сессии · Статистика · Сценарии · Материалы»; у',
    '  администратора «Администрирование» и те же пункты; у стажёра «Мои занятия · История ·',
    '  Справочная база».',
    '- Рабочее место ДДС (у стажёра) — светлое, остальные страницы — тёмные.',
    '',
    '## Как читать шаг',
    '',
    '- **«Что сделать»** называет точные надписи кнопок, полей, пунктов меню и вкладок — в «кавычках»,',
    '  как на экране, — и где они находятся. Выполняйте ровно это действие.',
    '- **«Должно быть видно»** — список (•). Каждый пункт — конкретная надпись, состояние (кнопка',
    '  активна/неактивна, пункт подсвечен), статус или число. Проверьте каждый пункт.',
    '- **Время.** Всё, что перечислено, должно появиться примерно за 5 секунд. Если шаг говорит',
    '  *«Ждать до N с: …»*, продукт действительно ждёт (например, карточка приходит сама после запуска',
    '  занятия) — ждите до N секунд, ничего не нажимая и не перезагружая страницу.',
    '- **`<суффикс>`.** В начале каждого сценария придумайте суффикс — текущее время ЧЧММСС',
    '  (например, `142305`) — и подставляйте его везде, где написано `<суффикс>`: в названия занятий,',
    '  логины, имена. Так сценарии не путают свои данные с чужими.',
    '',
    '## Правило немедленной остановки',
    '',
    '1. Если хоть что-то из «Должно быть видно» не появилось на экране примерно за 5 секунд (или за',
    '   указанное время ожидания), **или** действие из «Что сделать» выполнить нельзя (нет такой',
    '   кнопки, поле неактивно, пункт не выбирается) — **немедленно остановите этот сценарий**.',
    '2. Отметьте его **«СЛОМАН на шаге SNN.MM»**, запишите: что именно ожидалось (пункт из «Должно',
    '   быть видно» дословно) и что на экране вместо этого; сделайте снимок экрана.',
    '3. Выполните раздел «Уборка» этого сценария (он для того и нужен, чтобы не мешать следующим).',
    '4. Переходите к **следующему** сценарию. Сценарии независимы: каждый создаёт свои данные.',
    '5. Никогда не импровизируйте и не обходите проблему (не перезагружайте страницу, не ищите',
    '   другой путь, не исправляйте данные), если шаг прямо этого не говорит.',
    '',
    'Сценарий, у которого все шаги прошли, — **РАБОТАЕТ**.',
    '',
    '## Итоговый отчёт',
    '',
    'Одна таблица по всем сценариям, затем заметки по каждому сломанному:',
    '',
    '| Сценарий | Статус | Шаг | Что не увидел | Что было на экране |',
    '|---|---|---|---|---|',
    '| S01 Вход и выход … | РАБОТАЕТ | — | — | — |',
    '| S03 Валидация ДДС … | СЛОМАН | S03.09 | «Укажите комментарий.» под полем «Комментарий» | статус сохранился без сообщения |',
    '',
    'Заметки: для каждого СЛОМАН — шаг, ожидание, что было на экране, путь к снимку экрана.',
    '',
    '## Сценарии',
    '',
    '| Файл | Сценарий | Шагов |',
    '|---|---|---|',
    ...scenarios.map((item) => `| [${item.id}.md](${item.id}.md) | ${cell(item.title)} | ${item.steps.length} |`),
    '',
  ].join('\n');
}

/** Every file of `docs/test-scenarios/`, by name. `options.omitSecureOnly` (I6 HTTP) renders the
 * http-only variant (build-bundle.sh's `--http`): the instructions file is unchanged, each
 * scenario file drops its `secureOnly` steps. */
export function renderAll(scenarios: Scenario[], options: RenderOptions = {}): Map<string, string> {
  const files = new Map<string, string>([['00-instructions.md', renderInstructions(scenarios)]]);
  for (const item of scenarios) files.set(scenarioFileName(item), renderScenario(item, options));
  return files;
}
