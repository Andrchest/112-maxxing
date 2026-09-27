// S10: the administrator's user management and monitoring tabs: create, block (login refused),
// unblock, reset the password (login with the new one), the journal shows the actions, and the
// monitoring tabs open and say «нет данных» rather than 0 where a metric is missing.
import { button, check, disabledButton, heading, scenario, text, url, visible, type Expectation, type StepDefinition } from './dsl';
import { createUserSteps, loginPageSteps, loginSteps, logoutVisible } from './steps';

const userRow = (page: import('@playwright/test').Page, ctx: import('./dsl').ScenarioContext) =>
  page.getByRole('row').filter({ hasText: ctx.vars['tempUser.username'] ?? '' });

function tempLoginStep(passwordNote: string, password: (ctx: import('./dsl').ScenarioContext) => string, expectations: Expectation[]): StepDefinition {
  return {
    actor: 'tempUser',
    do: `На странице входа ввести логин проверяемого пользователя и ${passwordNote}, нажать «Войти».`,
    action: async (page, ctx) => {
      await page.goto('/login');
      await page.getByLabel('Имя пользователя', { exact: true }).fill(ctx.credentials('tempUser').username);
      await page.getByLabel('Пароль', { exact: true }).fill(password(ctx));
      await page.getByRole('button', { name: 'Войти', exact: true }).click();
    },
    expect: expectations,
  };
}

const refused: Expectation[] = [
  text('сообщение «Неверные учётные данные или истёкшая сессия. Войдите снова.»', 'Неверные учётные данные или истёкшая сессия. Войдите снова.'),
  url('остались на /login', /\/login$/),
];
const accepted: Expectation[] = [url('вход выполнен: адрес /sessions', /\/sessions$/), heading('Мои занятия'), logoutVisible];

function logoutStep(): StepDefinition {
  return {
    actor: 'tempUser',
    do: 'В шапке справа нажать «Выйти».',
    action: async (page) => {
      await page.getByRole('button', { name: 'Выйти', exact: true }).click();
    },
    expect: [heading('Вход в систему')],
  };
}

function tabStep(tab: string, expectations: Expectation[]): StepDefinition {
  return {
    actor: 'admin',
    do: `На странице «Администрирование» нажать вкладку «${tab}».`,
    action: async (page) => {
      await page.getByRole('tab', { name: tab, exact: true }).click();
    },
    expect: [
      visible(`вкладка «${tab}» выбрана`, (page) => page.getByRole('tab', { name: tab, exact: true, selected: true })),
      ...expectations,
    ],
  };
}

export const S10 = scenario(
  'S10',
  'Администратор: пользователи (создать, заблокировать, разблокировать, сбросить пароль), журнал, мониторинг',
  ['admin', 'tempUser'],
  [
    ...loginSteps('admin', 'ADMIN', 'администратора (admin)'),
    ...createUserSteps('tempUser', 'Стажёр', 'проверяемый').slice(1),
    loginPageSteps('tempUser'),
    tempLoginStep('его пароль', (ctx) => ctx.credentials('tempUser').password, accepted),
    logoutStep(),
    {
      actor: 'admin',
      do: 'В строке проверяемого пользователя нажать «Заблокировать».',
      action: async (page, ctx) => {
        await userRow(page, ctx).getByRole('button', { name: 'Заблокировать', exact: true }).click();
      },
      expect: [
        check('строка пропала из списка активных пользователей', async (page, ctx, { expect, timeout }) => {
          await expect(userRow(page, ctx)).toHaveCount(0, { timeout });
        }),
      ],
    },
    {
      actor: 'admin',
      do: 'Над таблицей отметить галочку «Показывать заблокированных».',
      action: async (page) => {
        await page.getByRole('checkbox', { name: 'Показывать заблокированных' }).check();
      },
      expect: [
        check('строка проверяемого пользователя снова видна, статус «Заблокирован», кнопка «Разблокировать»', async (page, ctx, { expect, timeout }) => {
          await expect(userRow(page, ctx)).toContainText('Заблокирован', { timeout });
          await expect(userRow(page, ctx).getByRole('button', { name: 'Разблокировать', exact: true })).toBeVisible({ timeout });
        }),
      ],
    },
    tempLoginStep('его пароль', (ctx) => ctx.credentials('tempUser').password, refused),
    {
      actor: 'admin',
      do: 'В строке проверяемого пользователя нажать «Разблокировать».',
      action: async (page, ctx) => {
        await userRow(page, ctx).getByRole('button', { name: 'Разблокировать', exact: true }).click();
      },
      expect: [
        check('статус «Активен», кнопка снова «Заблокировать»', async (page, ctx, { expect, timeout }) => {
          await expect(userRow(page, ctx)).toContainText('Активен', { timeout });
          await expect(userRow(page, ctx).getByRole('button', { name: 'Заблокировать', exact: true })).toBeVisible({ timeout });
        }),
      ],
    },
    tempLoginStep('его пароль', (ctx) => ctx.credentials('tempUser').password, accepted),
    logoutStep(),
    {
      actor: 'admin',
      do: 'В строке проверяемого пользователя нажать «Сбросить пароль».',
      action: async (page, ctx) => {
        await userRow(page, ctx).getByRole('button', { name: 'Сбросить пароль', exact: true }).click();
      },
      expect: [
        visible('окно «Новый пароль»', (page) => page.getByRole('dialog', { name: 'Новый пароль' })),
        visible('поле «Пароль»', (page) => page.getByRole('dialog').getByLabel('Пароль', { exact: true })),
        disabledButton('Сохранить', 'кнопка «Сохранить» (неактивна, пока поле пустое)'),
        button('Отмена'),
      ],
    },
    {
      actor: 'admin',
      do: 'В поле «Пароль» ввести новый пароль `New-<суффикс>-Bb2!`, нажать «Сохранить».',
      action: async (page, ctx) => {
        ctx.vars.newPassword = `New-${ctx.unique}-Bb2!`;
        await page.getByRole('dialog').getByLabel('Пароль', { exact: true }).fill(ctx.vars.newPassword);
        await page.getByRole('dialog').getByRole('button', { name: 'Сохранить', exact: true }).click();
      },
      expect: [
        check('окно закрылось', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByRole('dialog')).toHaveCount(0, { timeout });
        }),
      ],
    },
    tempLoginStep('СТАРЫЙ пароль', (ctx) => ctx.credentials('tempUser').password, refused),
    tempLoginStep('НОВЫЙ пароль `New-<суффикс>-Bb2!`', (ctx) => ctx.vars.newPassword ?? '', accepted),
    tabStep('Журнал', [
      text('строка «PATCH /api/v1/admin/users/{user_id}» (блокировка и разблокировка)', 'PATCH /api/v1/admin/users/{user_id}'),
      text('строка «POST /api/v1/admin/users/{user_id}/password» (сброс пароля)', 'POST /api/v1/admin/users/{user_id}/password'),
      text('строка «POST /api/v1/admin/users» (создание пользователя)', /^POST \/api\/v1\/admin\/users$/),
    ]),
    {
      actor: 'admin',
      do: 'В фильтре «Действие» выбрать «Неудачный вход».',
      action: async (page) => {
        await page.getByLabel('Действие', { exact: true }).selectOption({ label: 'Неудачный вход' });
      },
      expect: [
        check('строки «Неудачный вход» с запросом «POST /api/v1/auth/login» и статусом 401', async (page, _ctx, { expect, timeout }) => {
          const row = page.getByRole('row').filter({ hasText: 'Неудачный вход' }).first();
          await expect(row).toBeVisible({ timeout });
          await expect(row).toContainText('POST /api/v1/auth/login', { timeout });
          await expect(row).toContainText('401', { timeout });
        }),
      ],
    },
    tabStep('Статистика', [
      ...['Дата', 'Входы', 'Сессии', 'Занятия', 'Активные пользователи'].map((column) =>
        visible(`колонка «${column}»`, (page) => page.getByRole('tabpanel').getByRole('cell', { name: column, exact: true })),
      ),
      visible('фильтры «С даты» и «По дату (не включая)»', (page) => page.getByLabel('По дату (не включая)', { exact: true })),
    ]),
    tabStep('Нагрузка', [
      text('«Снято: <дата и время>»', /Снято:/),
      text('«Процессор» с процентом', 'Процессор'),
      text('«Память» в МБ', /МБ/),
      text('«Диск» в ГБ', /ГБ/),
      check('«Видеопамять» — «нет данных» (видеокарта не используется), а не «0»', async (page, _ctx, { expect, timeout }) => {
        const panel = page.getByRole('tabpanel');
        await expect(panel).toContainText(/Видеопамять\s*нет данных/, { timeout });
      }),
    ]),
    tabStep('Ошибки', [
      check('таблица с колонками «Время», «Источник», «Сообщение», «Сессия» или надпись «Ошибок нет.»', async (page, _ctx, { expect, timeout }) => {
        await expect(page.getByRole('tabpanel')).toContainText(/Время\s*Источник\s*Сообщение\s*Сессия|Ошибок нет\./, { timeout });
      }),
    ]),
    tabStep('Оповещения', [
      text('блок «Резервное копирование»', 'Резервное копирование'),
      check('оповещения списком или «Активных оповещений нет.»; сведения о копии или «Резервная копия недоступна.»', async (page, _ctx, { expect, timeout }) => {
        await expect(page.getByRole('tabpanel')).toContainText(/Активных оповещений нет\.|С \d\d\.\d\d\.\d{4}/, { timeout });
        await expect(page.getByRole('tabpanel')).toContainText(/Резервная копия недоступна\.|Завершено/, { timeout });
      }),
    ]),
    tabStep('Журнал', [
      check('в колонке «Пользователь» у строк администратора — кто это (логин или «Администратор»), а не служебное слово «ADMIN»', async (page, _ctx, { expect, timeout }) => {
        const row = page.getByRole('row').filter({ hasText: 'PATCH /api/v1/admin/users/{user_id}' }).first();
        await expect(row).toBeVisible({ timeout });
        await expect(row.getByRole('cell').nth(1)).not.toHaveText(/^(ADMIN|INSTRUCTOR|TRAINEE)$/, { timeout });
      }),
    ]),
  ],
  {
    purpose:
      'Администратор создаёт пользователя; блокирует его — вход отклоняется; разблокирует — вход снова работает; сбрасывает пароль — старый не подходит, новый подходит. Журнал показывает эти действия и неудачные входы. Вкладки «Статистика», «Нагрузка», «Ошибки», «Оповещения» открываются; где метрики нет, написано «нет данных», а не 0.',
    preconditions: ['Вход ещё не выполнен ни в одной вкладке (или нажмите «Выйти» во всех).'],
    testData: [
      'Проверяемый пользователь: логин `e2e-<суффикс>-tempuser`, «Отображаемое имя» `Проверяемый <суффикс>`, роль «Стажёр», пароль `Pw-<суффикс>-Aa1!`; новый пароль `New-<суффикс>-Bb2!`.',
    ],
    cleanup: ['Администратор → «Пользователи» → строка `e2e-<суффикс>-tempuser` → «Заблокировать».'],
  },
);
