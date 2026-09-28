// I6 SCENARIOS: step factories and page helpers shared by several scenarios — sign-in, the role
// menu, creating a temporary account through «Администрирование», creating a lesson through the
// instructor's form, and working a ДДС service tab. Locators go by role, label and visible Russian
// text, the way a person finds things on the screen.
import type { Locator, Page } from '@playwright/test';
import {
  button,
  check,
  heading,
  link,
  notVisible,
  text,
  url,
  visible,
  type Actor,
  type Expectation,
  type ScenarioContext,
  type StepDefinition,
  type Tools,
} from './dsl';

// -- stand data -----------------------------------------------------------------------------------

/** The ticket scenario every lesson scenario uses: a generated ДДС card, five services. */
export const TICKET_SCENARIO_OPTION =
  'Сложность 3 · Билет 1, вызов 1: Возгорание мусорного контейнера, пострадавших нет';
export const TICKET_SCENARIO_TITLE = 'Билет 1, вызов 1: Возгорание мусорного контейнера, пострадавших нет';
export const FIRE_SERVICE = 'Пожарно-спасательная служба';
export const OTHER_SERVICES = ['ЦОДД', 'ОАТИ', 'Поселение Дорогомилово', 'Поселение ЗАО'];
export const FIRE_CHAIN = ['Начало реагирования', 'Прибытие', 'Проведение работ', 'Работы завершены'];

export const NAV: Record<'TRAINEE' | 'INSTRUCTOR' | 'ADMIN', string[]> = {
  TRAINEE: ['Мои занятия', 'История', 'Справочная база'],
  INSTRUCTOR: ['Занятия', 'Сессии', 'Статистика', 'Сценарии', 'Материалы'],
  ADMIN: ['Администрирование', 'Занятия', 'Сессии', 'Статистика', 'Сценарии', 'Материалы'],
};

export const HOME: Record<keyof typeof NAV, { path: RegExp; heading: string; nav: string }> = {
  TRAINEE: { path: /\/sessions$/, heading: 'Мои занятия', nav: 'Мои занятия' },
  INSTRUCTOR: { path: /\/instructor\/lessons$/, heading: 'Занятия (несколько карточек)', nav: 'Занятия' },
  ADMIN: { path: /\/admin$/, heading: 'Администрирование', nav: 'Администрирование' },
};

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/;

// -- locators ------------------------------------------------------------------------------------

export function navBar(page: Page): Locator {
  return page.getByRole('navigation', { name: 'Разделы' });
}

export function navLink(page: Page, name: string): Locator {
  return navBar(page).getByRole('link', { name, exact: true });
}

/** A ДДС service tab, by the service name it starts with. */
export function legTab(page: Page, service: string): Locator {
  return page.getByRole('tab', { name: new RegExp(`^${escapeRegExp(service)}`) });
}

export function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function uuidIn(value: string): string {
  const match = value.match(UUID);
  if (!match) throw new Error(`в адресе ${value} нет идентификатора`);
  return match[0];
}

// -- expectations shared by many steps -------------------------------------------------------------

/** The role menu shows exactly these items, in this order, and `current` is highlighted. */
export function roleMenu(role: keyof typeof NAV, current?: string): Expectation {
  const items = NAV[role];
  return check(
    `меню «${items.join(' · ')}»${current ? `, пункт «${current}» подсвечен` : ''}`,
    async (page, _ctx, { expect, timeout }) => {
      await expect(navBar(page).getByRole('link')).toHaveText(items, { timeout });
      if (current) await expect(navLink(page, current)).toHaveAttribute('aria-current', 'page', { timeout });
    },
  );
}

export const logoutVisible: Expectation = button('Выйти', 'справа вверху кнопка «Выйти»');

// -- sign-in ------------------------------------------------------------------------------------------

export function loginPageSteps(actor: Actor): StepDefinition {
  return {
    actor,
    do: 'Открыть новую вкладку браузера для этой роли и набрать адрес стенда + «/login» (страница входа).',
    action: async (page) => {
      await page.goto('/login');
    },
    expect: [
      heading('Вход в систему'),
      visible('поле «Имя пользователя»', (page) => page.getByLabel('Имя пользователя', { exact: true })),
      visible('поле «Пароль»', (page) => page.getByLabel('Пароль', { exact: true })),
      button('Войти'),
    ],
  };
}

async function fillLogin(page: Page, ctx: ScenarioContext, actor: Actor): Promise<void> {
  const { username, password } = ctx.credentials(actor);
  await page.getByLabel('Имя пользователя', { exact: true }).fill(username);
  await page.getByLabel('Пароль', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
}

/** Sign in and land on the role's home page, with the role menu and «Выйти». */
export function loginSteps(actor: Actor, role: keyof typeof NAV, who: string): StepDefinition[] {
  const home = HOME[role];
  return [
    loginPageSteps(actor),
    {
      actor,
      do: `Ввести логин и пароль ${who}, нажать «Войти».`,
      action: (page, ctx) => fillLogin(page, ctx, actor),
      expect: [
        url(`открылась домашняя страница роли (${home.path.source.replace(/\\/g, '').replace('$', '')})`, home.path),
        heading(home.heading),
        roleMenu(role, home.nav),
        logoutVisible,
      ],
    },
  ];
}

// -- a temporary account through «Администрирование» ----------------------------------------------

/**
 * Admin creates an account (the admin must already be signed in, on any page). Stores the
 * credentials under `key` and registers a cleanup that blocks the account.
 */
export function createUserSteps(key: Actor, roleLabel: 'Стажёр' | 'Инструктор', what: string): StepDefinition[] {
  const username = (ctx: ScenarioContext) => ctx.vars[`${key}.username`] ?? '';
  const displayName = (ctx: ScenarioContext) => ctx.vars[`${key}.displayName`] ?? '';
  return [
    {
      actor: 'admin',
      do: 'В шапке, в меню, нажать «Администрирование»; под заголовком нажать вкладку «Пользователи».',
      action: async (page) => {
        await navLink(page, 'Администрирование').click();
        await page.getByRole('tab', { name: 'Пользователи', exact: true }).click();
      },
      expect: [
        heading('Администрирование'),
        visible('вкладка «Пользователи» выбрана', (page) =>
          page.getByRole('tab', { name: 'Пользователи', exact: true, selected: true }),
        ),
        button('Создать пользователя'),
        visible('таблица пользователей с колонкой «Логин»', (page) => page.getByRole('cell', { name: 'Логин', exact: true })),
      ],
    },
    {
      actor: 'admin',
      do: `Справа над таблицей нажать «Создать пользователя». В окне «Новый пользователь»: «Логин» — \`e2e-<суффикс>-${key.toLowerCase()}\`, «Отображаемое имя» — \`${what[0]?.toUpperCase()}${what.slice(1)} <суффикс>\`, «Роль» — «${roleLabel}», «Пароль» — \`Pw-<суффикс>-Aa1!\`; нажать «Создать».`,
      action: async (page, ctx) => {
        const login = `e2e-${ctx.unique}-${key}`.toLowerCase();
        ctx.vars[`${key}.username`] = login;
        ctx.vars[`${key}.displayName`] = `${what[0]?.toUpperCase()}${what.slice(1)} ${ctx.unique}`;
        ctx.setCredentials(key, { username: login, password: `Pw-${ctx.unique}-Aa1!` });
        ctx.onCleanup(`заблокировать ${login}`, (api) => api.blockUser(login));
        await page.getByRole('button', { name: 'Создать пользователя', exact: true }).click();
        const dialog = page.getByRole('dialog', { name: 'Новый пользователь' });
        await dialog.getByLabel('Логин', { exact: true }).fill(login);
        await dialog.getByLabel('Отображаемое имя', { exact: true }).fill(ctx.vars[`${key}.displayName`] ?? '');
        await dialog.getByLabel('Роль', { exact: true }).selectOption({ label: roleLabel });
        await dialog.getByLabel('Пароль', { exact: true }).fill(ctx.credentials(key).password);
        await dialog.getByRole('button', { name: 'Создать', exact: true }).click();
      },
      expect: [
        check('окно «Новый пользователь» закрылось', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByRole('dialog', { name: 'Новый пользователь' })).toHaveCount(0, { timeout });
        }),
        visible(`в таблице строка с логином \`e2e-<суффикс>-${key.toLowerCase()}\``, (page, ctx) => page.getByRole('row').filter({ hasText: username(ctx) })),
        check(`в строке: имя «${what[0]?.toUpperCase()}${what.slice(1)} <суффикс>», роль «${roleLabel}», статус «Активен», кнопки «Заблокировать», «Сбросить пароль»`, async (page, ctx, { expect, timeout }) => {
          const row = page.getByRole('row').filter({ hasText: username(ctx) });
          await expect(row).toContainText(displayName(ctx), { timeout });
          await expect(row.getByRole('combobox', { name: 'Роль' })).toHaveValue(
            roleLabel === 'Стажёр' ? 'TRAINEE' : 'INSTRUCTOR',
            { timeout },
          );
          await expect(row).toContainText('Активен', { timeout });
          await expect(row.getByRole('button', { name: 'Заблокировать', exact: true })).toBeVisible({ timeout });
          await expect(row.getByRole('button', { name: 'Сбросить пароль', exact: true })).toBeVisible({ timeout });
        }),
      ],
    },
  ];
}

// -- a lesson through the instructor's form ------------------------------------------------------

export interface LessonOptions {
  /** Actor who creates the lesson (signed in as an instructor). */
  instructor: Actor;
  /** Key of the trainee actor (its display name is picked as the ДДС participant). */
  trainee: Actor;
  /** Short label that goes into the lesson title after «e2e». */
  label: string;
  /** «Решение «Принята» / «Не принята», с» override. */
  acceptTimerSeconds?: number;
  /** Strict «сдал / не сдал» criteria: min score %, max failed rules. */
  strictCriteria?: { minScore: number; maxFailedRules: number };
  /** «Режим занятия» other than the default «Одна роль». */
  mode?: string;
}

export function lessonTitle(ctx: ScenarioContext, label: string): string {
  return `e2e ${label} ${ctx.unique}`;
}

export function createLessonSteps(options: LessonOptions): StepDefinition[] {
  const { instructor, trainee, label } = options;
  const steps: StepDefinition[] = [
    {
      actor: instructor,
      do: 'В шапке, в меню, нажать «Занятия».',
      action: async (page) => {
        await navLink(page, 'Занятия').click();
      },
      expect: [
        url('адрес /instructor/lessons', /\/instructor\/lessons$/),
        heading('Занятия (несколько карточек)', 'список «Занятия (несколько карточек)»'),
        heading('Новое занятие (несколько карточек)', 'форма «Новое занятие (несколько карточек)»'),
        heading('Группы учащихся', 'блок «Группы учащихся»'),
        visible('поле «Название занятия»', (page) => page.getByLabel('Название занятия', { exact: true })),
        check('«Режим занятия» по умолчанию «Одна роль»', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByLabel('Режим занятия', { exact: true })).toHaveValue(/SINGLE/, { timeout });
          await expect(page.getByLabel('Режим занятия', { exact: true }).locator('option:checked')).toHaveText('Одна роль', { timeout });
        }),
      ],
    },
    {
      actor: instructor,
      do: `В форме «Новое занятие (несколько карточек)» (справа) ввести «Название занятия» \`e2e ${label} <суффикс>\`${options.mode ? `, в «Режим занятия» выбрать «${options.mode}»` : ''}; в блоке «Карточка 1» выбрать «Сценарий» «${TICKET_SCENARIO_OPTION}», затем в «Версия сценария» — единственную версию («… (v1)»).`,
      action: async (page, ctx) => {
        await page.getByLabel('Название занятия', { exact: true }).fill(lessonTitle(ctx, label));
        if (options.mode) await page.getByLabel('Режим занятия', { exact: true }).selectOption({ label: options.mode });
        await page.getByLabel('Сценарий', { exact: true }).selectOption({ label: TICKET_SCENARIO_OPTION });
        const version = page.getByLabel('Версия сценария', { exact: true });
        await version.locator('option', { hasText: '(v1)' }).first().waitFor({ state: 'attached' });
        await version.selectOption({ index: 1 });
      },
      expect: [
        ...(options.mode
          ? [
              check(`«Режим занятия»: «${options.mode}»`, async (page: Page, _ctx: ScenarioContext, { expect, timeout }: Tools) => {
                await expect(page.getByLabel('Режим занятия', { exact: true }).locator('option:checked')).toHaveText(options.mode ?? '', {
                  timeout,
                });
              }),
            ]
          : []),
        visible('появились «Варианты карточки»', (page) => page.getByText('Варианты карточки', { exact: true })),
        check('«Источник карточки»: «Сгенерированная карточка (без звонка)»', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByLabel('Источник карточки', { exact: true }).locator('option:checked')).toHaveText(
            'Сгенерированная карточка (без звонка)',
            { timeout },
          );
        }),
        check('«Режим работы ДДС»: «Статусы служб (по памятке ДДС)»', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByLabel('Режим работы ДДС', { exact: true }).locator('option:checked')).toHaveText(
            'Статусы служб (по памятке ДДС)',
            { timeout },
          );
        }),
        visible('блок «Временные рамки карточки»', (page) => page.getByText('Временные рамки карточки', { exact: true })),
        visible('блок «Критерии «сдал / не сдал»»', (page) => page.getByText('Критерии «сдал / не сдал»', { exact: true })),
      ],
    },
  ];
  if (options.acceptTimerSeconds !== undefined) {
    const seconds = options.acceptTimerSeconds;
    steps.push({
      actor: instructor,
      do: `В блоке «Временные рамки карточки» (под «Карточка 1») ввести в поле «Решение «Принята» / «Не принята», с» число ${seconds}.`,
      action: async (page) => {
        await page.getByLabel('Решение «Принята» / «Не принята», с', { exact: true }).fill(String(seconds));
      },
      expect: [
        check(`в поле «Решение «Принята» / «Не принята», с» стоит ${seconds}`, async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByLabel('Решение «Принята» / «Не принята», с', { exact: true })).toHaveValue(String(seconds), { timeout });
        }),
      ],
    });
  }
  if (options.strictCriteria) {
    const { minScore, maxFailedRules } = options.strictCriteria;
    steps.push({
      actor: instructor,
      do: `В блоке «Критерии «сдал / не сдал»» (внизу формы) отметить галочку «Минимальный процент баллов» и ввести ${minScore}; отметить галочку «Не больше нарушенных правил» и ввести ${maxFailedRules}.`,
      action: async (page) => {
        const minOn = page.getByRole('checkbox', { name: 'Минимальный процент баллов' });
        if (!(await minOn.isChecked())) await minOn.check();
        await page.getByRole('textbox', { name: 'Минимальный процент баллов' }).fill(String(minScore));
        const maxOn = page.getByRole('checkbox', { name: 'Не больше нарушенных правил' });
        if (!(await maxOn.isChecked())) await maxOn.check();
        await page.getByRole('textbox', { name: 'Не больше нарушенных правил' }).fill(String(maxFailedRules));
      },
      expect: [
        check('оба критерия включены, значения введены', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByRole('checkbox', { name: 'Минимальный процент баллов' })).toBeChecked({ timeout });
          await expect(page.getByRole('textbox', { name: 'Минимальный процент баллов' })).toHaveValue(String(minScore), { timeout });
          await expect(page.getByRole('checkbox', { name: 'Не больше нарушенных правил' })).toBeChecked({ timeout });
          await expect(page.getByRole('textbox', { name: 'Не больше нарушенных правил' })).toHaveValue(String(maxFailedRules), {
            timeout,
          });
        }),
        check('нет сообщения об ошибке в критериях', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByText('Включите хотя бы один критерий.')).toHaveCount(0, { timeout });
          await expect(page.getByText('Введите целое число: процент — от 0 до 100, правила — от 0.')).toHaveCount(0, { timeout });
        }),
      ],
    });
  }
  steps.push(
    {
      actor: instructor,
      do: 'В блоке «Участники занятия» в списке «ID пользователя-стажёра — ДДС» выбрать нового стажёра («Стажёр <суффикс>»); «Служба ДДС» оставить «Не назначено (играет по сценарию)».',
      action: async (page, ctx) => {
        await page.getByLabel('ID пользователя-стажёра — ДДС', { exact: true }).selectOption({ label: ctx.vars[`${trainee}.displayName`] ?? '' });
      },
      expect: [
        check('выбран созданный стажёр', async (page, ctx, { expect, timeout }) => {
          await expect(page.getByLabel('ID пользователя-стажёра — ДДС', { exact: true }).locator('option:checked')).toHaveText(
            ctx.vars[`${trainee}.displayName`] ?? '',
            { timeout },
          );
        }),
        check('«Служба ДДС»: «Не назначено (играет по сценарию)»', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByLabel('Служба ДДС', { exact: true }).locator('option:checked')).toHaveText('Не назначено (играет по сценарию)', {
            timeout,
          });
        }),
        button('Создать занятие', 'кнопка «Создать занятие» активна'),
      ],
    },
    {
      actor: instructor,
      do: 'Внизу формы нажать «Создать занятие».',
      action: async (page, ctx) => {
        await page.getByRole('button', { name: 'Создать занятие', exact: true }).click();
        await page.waitForURL(/\/instructor\/lessons\/[0-9a-f-]{36}/);
        const lessonId = uuidIn(page.url());
        ctx.vars.lessonId = lessonId;
        ctx.vars.lessonTitle = lessonTitle(ctx, label);
        const owner = ctx.credentials(instructor);
        ctx.onCleanup(`прервать занятие ${ctx.vars.lessonTitle}`, (api) => api.abortLesson(lessonId, owner));
      },
      expect: [
        url('сразу открылась страница нового занятия', /\/instructor\/lessons\/[0-9a-f-]{36}$/),
        visible('заголовок — название занятия', (page, ctx) =>
          page.getByRole('heading', { name: ctx.vars.lessonTitle ?? '', exact: true }),
        ),
        link('← Назад', 'слева вверху «← Назад»'),
        heading('План занятия', 'блок «План занятия»'),
        check('состояние «Создано»', async (page, _ctx, { expect, timeout }) => {
          await expect(planCard(page)).toContainText('Создано', { timeout });
        }),
        button('Начать занятие'),
        button('Прервать занятие'),
        heading('Карточки занятия', 'блок «Карточки занятия»'),
        check('одна карточка: сценарий, «Готово к началу», статус «Зарегистрирована», «Обзор карточки»', async (page, _ctx, { expect, timeout }) => {
          const rows = page.getByRole('row').filter({ has: page.getByRole('link', { name: 'Обзор карточки' }) });
          await expect(rows).toHaveCount(1, { timeout });
          await expect(rows.first()).toContainText(TICKET_SCENARIO_TITLE, { timeout });
          await expect(rows.first()).toContainText('Готово к началу', { timeout });
          await expect(rows.first()).toContainText('Зарегистрирована', { timeout });
        }),
        text('пояснение «Отчёт станет доступен после завершения занятия.»', 'Отчёт станет доступен после завершения занятия.'),
      ],
    },
  );
  return steps;
}

/** The «План занятия» card of the lesson page (its heading's card). */
export function planCard(page: Page): Locator {
  return page
    .locator('[data-slot="card"]')
    .filter({ has: page.getByRole('heading', { name: 'План занятия', exact: true }) });
}

/** The lesson's card row (the only one in these scenarios). */
export function lessonCardRow(page: Page): Locator {
  return page.getByRole('row').filter({ has: page.getByRole('link', { name: 'Обзор карточки' }) }).first();
}

export function startLessonStep(instructor: Actor): StepDefinition {
  return {
    actor: instructor,
    do: 'На странице занятия в блоке «План занятия» нажать «Начать занятие».',
    action: async (page) => {
      await page.getByRole('button', { name: 'Начать занятие', exact: true }).click();
    },
    expect: [
      check('«План занятия» в состоянии «Идёт»', async (page, _ctx, { expect, timeout }) => {
        await expect(planCard(page)).toContainText('Идёт', { timeout });
      }),
      check('кнопка «Начать занятие» исчезла', async (page, _ctx, { expect, timeout }) => {
        await expect(page.getByRole('button', { name: 'Начать занятие', exact: true })).toHaveCount(0, { timeout });
      }),
      button('Прервать занятие', 'кнопка «Прервать занятие» осталась'),
      check('у карточки состояние «Идёт»', async (page, _ctx, { expect, timeout }) => {
        await expect(lessonCardRow(page)).toContainText('Идёт', { timeout });
      }),
    ],
  };
}

// -- the trainee's side ----------------------------------------------------------------------------

/** Trainee on «Мои занятия» opens the only card of the lesson. */
export function traineeOpensCardStep(trainee: Actor): StepDefinition {
  return {
    actor: trainee,
    do: 'В списке «Мои занятия» у карточки со строкой «Занятие: e2e … <суффикс>» нажать «Открыть» (справа).',
    action: async (page, ctx) => {
      const row = page.getByRole('listitem').filter({ hasText: `Занятие: ${ctx.vars.lessonTitle}` });
      await row.getByRole('link', { name: 'Открыть', exact: true }).click();
      await page.waitForURL(/\/dds\/[0-9a-f-]{36}/);
      ctx.vars.sessionId = uuidIn(page.url());
    },
    expect: [url('открылось рабочее место ДДС (/dds/…)', /\/dds\/[0-9a-f-]{36}$/), link('← Назад', 'слева вверху «← Назад»')],
  };
}

/** The ДДС card has arrived: the workstation's key blocks. The phone's call buttons are a
 * separate list ({@link ddsCardPhoneExpectations}) — I6 HTTP: they need a secure context and are
 * hidden on the temporary http demo, while everything here keeps working over plain http too. */
export function ddsCardExpectations(): Expectation[] {
  return [
    text('вверху слева «Этап: Получено»', /Этап:\s*Получено/),
    button('Уведомления и радиообмен', 'вверху справа кнопка «Уведомления и радиообмен»'),
    notVisible('кнопки «Закрыть происшествие» пока нет (она появится после решения по службе)', (page) =>
      page.getByRole('button', { name: 'Закрыть происшествие', exact: true }),
    ),
    text('«Заявка от оператора 112»', 'Заявка от оператора 112'),
    text('раздел «ЗАЯВИТЕЛЬ»', 'ЗАЯВИТЕЛЬ'),
    text('раздел «АДРЕС»', 'АДРЕС'),
    text('раздел «СЛУЖБЫ»', 'СЛУЖБЫ'),
    text('строка «АОН: …» и справа «Происшествие <номер>»', /АОН:/),
    text('тёмный блок «Происшествие 101»', 'Происшествие 101'),
    text('внизу полоса «СЛУЖБЫ:» с вкладками служб', 'СЛУЖБЫ:'),
    ...[FIRE_SERVICE, ...OTHER_SERVICES].map((service) =>
      check(`вкладка службы «${service}» со статусом «Добавлена»`, async (page, _ctx, { expect, timeout }) => {
        await expect(legTab(page, service)).toBeVisible({ timeout });
        await expect(legTab(page, service)).toContainText('Добавлена', { timeout });
      }),
    ),
  ];
}

/** I6 HTTP: the ДДС phone's call buttons — need a secure context (LiveKit), hidden over plain
 * http behind the note «Недоступно по http…» (ru.ts `secureContextRequiredNotice`). Used only by
 * {@link ddsCardPhoneAvailableStep}, a `secureOnly` step, so an http tester never sees them. */
export function ddsCardPhoneExpectations(): Expectation[] {
  return [
    text('блок «Телефон» — «Нет звонка»', 'Нет звонка'),
    button(`Позвонить старшему · ${FIRE_SERVICE}`, `кнопки «Позвонить старшему · …» для каждой службы (например, «Позвонить старшему · ${FIRE_SERVICE}»)`),
    button('Позвонить заявителю'),
    button('Позвонить в 112'),
  ];
}

/** I6 HTTP: `secureOnly` step checking the phone's call buttons on the already-arrived ДДС card
 * (no action — the card is already on screen). Omitted from the http bundle and, with
 * `E2E_SKIP_SECURE_ONLY=1`, from the runner. */
export function ddsCardPhoneAvailableStep(trainee: Actor): StepDefinition {
  return {
    actor: trainee,
    do: 'Посмотреть на блок «Телефон» на уже открытой карточке (ничего не нажимать).',
    expect: ddsCardPhoneExpectations(),
    secureOnly: true,
  };
}

/** Opens a service tab's popup if it is closed, then «Изменить статус». */
export async function openLegEditor(page: Page, service: string): Promise<void> {
  const tab = legTab(page, service);
  if ((await tab.getAttribute('aria-selected')) !== 'true') await tab.click();
  await page.getByRole('button', { name: 'Изменить статус', exact: true }).click();
}

/** Picks a status, fills the order number and comment, confirms. */
export async function submitLegStatus(
  page: Page,
  status: string,
  fields: { order?: string; comment?: string } = {},
): Promise<void> {
  await page.getByLabel('Статус', { exact: true }).selectOption({ label: status });
  if (fields.order !== undefined) await page.getByLabel('Номер наряда', { exact: true }).fill(fields.order);
  if (fields.comment !== undefined) await page.getByLabel('Комментарий', { exact: true }).fill(fields.comment);
  await page.getByRole('button', { name: 'Подтвердить', exact: true }).click();
}

/** One step: a service tab → «Изменить статус» → status (+order, comment) → «Подтвердить». */
export function legStatusStep(
  trainee: Actor,
  service: string,
  status: string,
  fields: { order?: string; comment?: string } = {},
  extra: Expectation[] = [],
): StepDefinition {
  const details = [
    fields.order ? `«Номер наряда» ${fields.order}` : '',
    fields.comment ? `«Комментарий» «${fields.comment}»` : '',
  ].filter(Boolean);
  return {
    actor: trainee,
    do: `Внизу, в полосе «СЛУЖБЫ:», нажать вкладку «${service}» (если её окно истории ещё не открыто); в открывшемся окне над вкладкой нажать карандаш «Изменить статус»; в «Статус» выбрать «${status}»${details.length ? `; ${details.join('; ')}` : ''}; нажать галочку «Подтвердить».`,
    action: async (page) => {
      await openLegEditor(page, service);
      await submitLegStatus(page, status, fields);
    },
    expect: [
      check(`на вкладке «${service}» статус «${status}»`, async (page, _ctx, { expect, timeout }) => {
        await expect(legTab(page, service)).toContainText(status, { timeout });
      }),
      check('форма статуса закрылась', async (page, _ctx, { expect, timeout }) => {
        await expect(page.getByRole('button', { name: 'Подтвердить', exact: true })).toHaveCount(0, { timeout });
      }),
      ...extra,
    ],
  };
}

/** Walks the four other services to «Не принята» with a comment. */
export function otherLegsDeclinedSteps(trainee: Actor): StepDefinition[] {
  return OTHER_SERVICES.map((service) => legStatusStep(trainee, service, 'Не принята', { comment: 'Не требуется' }));
}

/** «Закрыть происшествие» → «Урегулировано» + comment → «Подтвердить» → «Занятие завершено.». */
export function closeIncidentSteps(trainee: Actor): StepDefinition[] {
  return [
    {
      actor: trainee,
      do: 'Нажать кнопку «Закрыть происшествие» (вверху справа, рядом с «Уведомления и радиообмен»).',
      action: async (page) => {
        if ((await page.getByRole('button', { name: 'Изменить статус' }).count()) > 0) await page.keyboard.press('Escape');
        await page.getByRole('button', { name: 'Закрыть происшествие', exact: true }).click();
      },
      expect: [
        visible('окно «Закрытие происшествия»', (page) => page.getByRole('dialog', { name: 'Закрытие происшествия' })),
        check('в «Причина закрытия» варианты «Урегулировано», «Ложный вызов», «Передано другой службе», «Отменено заявителем»', async (page, _ctx, { expect, timeout }) => {
          const reason = page.getByRole('dialog').getByLabel('Причина закрытия', { exact: true });
          for (const option of ['Урегулировано', 'Ложный вызов', 'Передано другой службе', 'Отменено заявителем']) {
            await expect(reason.locator('option', { hasText: option })).toHaveCount(1, { timeout });
          }
        }),
        visible('поле «Комментарий»', (page) => page.getByRole('dialog').getByLabel('Комментарий', { exact: true })),
      ],
    },
    {
      actor: trainee,
      do: 'В окне «Закрытие происшествия»: «Причина закрытия» — «Урегулировано», «Комментарий» — «Все службы отработали»; нажать «Подтвердить».',
      action: async (page) => {
        const dialog = page.getByRole('dialog');
        await dialog.getByLabel('Причина закрытия', { exact: true }).selectOption({ label: 'Урегулировано' });
        await dialog.getByLabel('Комментарий', { exact: true }).fill('Все службы отработали');
        await dialog.getByRole('button', { name: 'Подтвердить', exact: true }).click();
      },
      expect: [text('«Занятие завершено.»', 'Занятие завершено.'), link('Перейти к отчёту', 'кнопка «Перейти к отчёту»')],
    },
  ];
}

/** Waits for the ДДС card to reach the trainee after the lesson start (legitimate product wait). */
export const CARD_ARRIVAL_WAIT = {
  timeoutMs: 10_000,
  why: 'карточка приходит к стажёру сама после «Начать занятие»; по продукту — до ~3–5 с, плюс доставка по сети',
};

// -- composite flows -------------------------------------------------------------------------------

/**
 * Everything up to the trainee looking at the arrived ДДС card: the admin creates a new trainee,
 * the instructor creates and starts the lesson, the trainee signs in and opens the card.
 */
export function startedLessonSteps(options: Omit<LessonOptions, 'instructor' | 'trainee'>): StepDefinition[] {
  return [
    ...loginSteps('admin', 'ADMIN', 'администратора (admin)'),
    ...createUserSteps('newTrainee', 'Стажёр', 'стажёр'),
    ...loginSteps('instructor', 'INSTRUCTOR', 'преподавателя (instructor)'),
    ...createLessonSteps({ ...options, instructor: 'instructor', trainee: 'newTrainee' }),
    startLessonStep('instructor'),
    ...loginSteps('newTrainee', 'TRAINEE', 'нового стажёра (логин и пароль из «Тестовых данных»)'),
    {
      ...traineeOpensCardStep('newTrainee'),
      wait: CARD_ARRIVAL_WAIT,
      expect: [...traineeOpensCardStep('newTrainee').expect, ...ddsCardExpectations()],
    },
    ddsCardPhoneAvailableStep('newTrainee'),
  ];
}

/** The fire service walked to «Работы завершены» (the first status with order «Н-101»). */
export function fireServiceDoneSteps(trainee: Actor, firstComment = 'Наряд выслан'): StepDefinition[] {
  return [
    legStatusStep(trainee, FIRE_SERVICE, 'Принята', { order: 'Н-101', comment: firstComment }, [
      text('«Этап: Принято к исполнению»', /Этап:\s*Принято к исполнению/),
    ]),
    ...FIRE_CHAIN.map((status) => legStatusStep(trainee, FIRE_SERVICE, status, { comment: `Доклад: ${status.toLowerCase()}` })),
  ];
}

/** Back to the lesson page after the card closed: the page does not refresh by itself. */
export function reopenLessonStep(instructor: Actor, extra: Expectation[]): StepDefinition {
  return {
    actor: instructor,
    do: 'Подождать 3 секунды после «Занятие завершено.» у стажёра (занятие завершается само за 1–2 с; открытая страница занятия сама не обновляется). Затем в шапке нажать «Занятия» и в списке «Занятия (несколько карточек)» у занятия «e2e … <суффикс>» нажать «Открыть».',
    action: async (page, ctx) => {
      await page.waitForTimeout(3000);
      await navLink(page, 'Занятия').click();
      await page.getByRole('listitem').filter({ hasText: ctx.vars.lessonTitle ?? '' }).getByRole('link', { name: 'Открыть', exact: true }).click();
    },
    expect: [
      url('открылась страница занятия', /\/instructor\/lessons\/[0-9a-f-]{36}$/),
      visible('заголовок — название занятия', (page, ctx) => page.getByRole('heading', { name: ctx.vars.lessonTitle ?? '', exact: true })),
      ...extra,
    ],
  };
}

export const lessonCompleted: Expectation = check('«План занятия» в состоянии «Завершено»', async (page, _ctx, { expect, timeout }) => {
  await expect(planCard(page)).toContainText('Завершено', { timeout });
});

/** From the lesson page: «Обзор карточки» → «Перейти к отчёту». */
export function openSessionReportStep(instructor: Actor, extra: Expectation[]): StepDefinition {
  return {
    actor: instructor,
    do: 'В блоке «Карточки занятия» нажать «Обзор карточки», затем на странице «Обзор занятия (инструктор)» нажать «Перейти к отчёту».',
    action: async (page) => {
      await page.getByRole('link', { name: 'Обзор карточки', exact: true }).click();
      await page.getByRole('link', { name: 'Перейти к отчёту', exact: true }).click();
    },
    expect: [url('адрес /report/…', /\/report\/[0-9a-f-]{36}$/), heading('Отчёт по занятию'), ...extra],
  };
}

/** The lesson report table's row of the new trainee (its «Рабочее место» is their login). */
export function reportRow(page: Page, ctx: ScenarioContext, trainee: Actor = 'newTrainee'): Locator {
  return page.getByRole('row').filter({ hasText: ctx.vars[`${trainee}.username`] ?? '' }).first();
}
