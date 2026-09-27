// S01: sign-in and sign-out for the three roles, each role's menu, «Выйти» on every page, and
// another role's pages refused (typing the address sends you back to your own home page).
import { button, heading, notVisible, scenario, text, url, type StepDefinition } from './dsl';
import { HOME, loginPageSteps, loginSteps, logoutVisible, navLink, roleMenu, type NAV } from './steps';

function menuStep(actor: string, role: keyof typeof NAV, item: string, path: RegExp, title: string): StepDefinition {
  return {
    actor,
    do: `В шапке, в меню роли, нажать «${item}».`,
    action: async (page) => {
      await navLink(page, item).click();
    },
    expect: [
      url(`адрес ${path.source.replace(/\\/g, '').replace('$', '')}`, path),
      heading(title),
      roleMenu(role, item),
      logoutVisible,
    ],
  };
}

function refusedStep(actor: string, role: keyof typeof NAV, path: string, what: string, notTitle: string): StepDefinition {
  const home = HOME[role];
  return {
    actor,
    do: `В адресной строке открыть адрес стенда + «${path}» (${what}) и нажать Enter.`,
    action: async (page) => {
      await page.goto(path);
    },
    expect: [
      url(`страница не открылась: браузер вернулся на свою домашнюю страницу (${home.path.source.replace(/\\/g, '').replace('$', '')})`, home.path),
      heading(home.heading),
      notVisible(`заголовка «${notTitle}» нет`, (page) => page.getByRole('heading', { name: notTitle, exact: true })),
      roleMenu(role, home.nav),
    ],
  };
}

function logoutSteps(actor: string, protectedPath: string): StepDefinition[] {
  return [
    {
      actor,
      do: 'В шапке справа нажать «Выйти».',
      action: async (page) => {
        await page.getByRole('button', { name: 'Выйти', exact: true }).click();
      },
      expect: [
        url('адрес /login', /\/login$/),
        heading('Вход в систему'),
        button('Войти'),
        notVisible('меню роли в шапке нет', (page) => page.getByRole('navigation', { name: 'Разделы' })),
      ],
    },
    {
      actor,
      do: `После выхода открыть в адресной строке адрес стенда + «${protectedPath}».`,
      action: async (page) => {
        await page.goto(protectedPath);
      },
      expect: [url('без входа страница не открылась: адрес /login', /\/login$/), heading('Вход в систему')],
    },
  ];
}

export const S01 = scenario(
  'S01',
  'Вход и выход для трёх ролей, меню своей роли, чужие разделы недоступны',
  ['trainee', 'instructor', 'admin'],
  [
    loginPageSteps('trainee'),
    {
      actor: 'trainee',
      do: 'Ввести логин стажёра и НЕВЕРНЫЙ пароль «неверный-пароль», нажать «Войти».',
      action: async (page, ctx) => {
        await page.getByLabel('Имя пользователя', { exact: true }).fill(ctx.credentials('trainee').username);
        await page.getByLabel('Пароль', { exact: true }).fill('неверный-пароль');
        await page.getByRole('button', { name: 'Войти', exact: true }).click();
      },
      expect: [
        text('под полями сообщение «Неверные учётные данные или истёкшая сессия. Войдите снова.»', 'Неверные учётные данные или истёкшая сессия. Войдите снова.'),
        url('остались на /login', /\/login$/),
      ],
    },
    ...loginSteps('trainee', 'TRAINEE', 'стажёра (trainee)').slice(1),
    menuStep('trainee', 'TRAINEE', 'История', /\/history$/, 'Мои результаты'),
    menuStep('trainee', 'TRAINEE', 'Справочная база', /\/materials$/, 'Справочная база'),
    menuStep('trainee', 'TRAINEE', 'Мои занятия', /\/sessions$/, 'Мои занятия'),
    refusedStep('trainee', 'TRAINEE', '/instructor/lessons', 'раздел преподавателя', 'Занятия (несколько карточек)'),
    refusedStep('trainee', 'TRAINEE', '/admin', 'раздел администратора', 'Администрирование'),
    ...logoutSteps('trainee', '/sessions'),

    ...loginSteps('instructor', 'INSTRUCTOR', 'преподавателя (instructor)'),
    menuStep('instructor', 'INSTRUCTOR', 'Сессии', /\/instructor$/, 'Инструктор'),
    menuStep('instructor', 'INSTRUCTOR', 'Статистика', /\/instructor\/statistics$/, 'Статистика обучаемых'),
    menuStep('instructor', 'INSTRUCTOR', 'Сценарии', /\/instructor\/scenarios$/, 'Сценарии'),
    menuStep('instructor', 'INSTRUCTOR', 'Материалы', /\/instructor\/materials$/, 'Материалы'),
    menuStep('instructor', 'INSTRUCTOR', 'Занятия', /\/instructor\/lessons$/, 'Занятия (несколько карточек)'),
    refusedStep('instructor', 'INSTRUCTOR', '/admin', 'раздел администратора', 'Администрирование'),
    refusedStep('instructor', 'INSTRUCTOR', '/sessions', 'раздел стажёра', 'Мои занятия'),
    ...logoutSteps('instructor', '/instructor/lessons'),

    ...loginSteps('admin', 'ADMIN', 'администратора (admin)'),
    {
      actor: 'admin',
      do: 'Посмотреть на страницу «Администрирование» (ничего не нажимать).',
      expect: ['Пользователи', 'Журнал', 'Статистика', 'Нагрузка', 'Ошибки', 'Оповещения'].map((tab) => ({
        see: `вкладка «${tab}»`,
        run: async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByRole('tab', { name: tab, exact: true })).toBeVisible({ timeout });
        },
      })),
    },
    menuStep('admin', 'ADMIN', 'Занятия', /\/instructor\/lessons$/, 'Занятия (несколько карточек)'),
    menuStep('admin', 'ADMIN', 'Статистика', /\/instructor\/statistics$/, 'Статистика обучаемых'),
    menuStep('admin', 'ADMIN', 'Администрирование', /\/admin$/, 'Администрирование'),
    refusedStep('admin', 'ADMIN', '/sessions', 'раздел стажёра', 'Мои занятия'),
    ...logoutSteps('admin', '/admin'),
  ],
  {
    purpose:
      'Каждая роль входит под своим логином, видит только меню своей роли и кнопку «Выйти» на каждой странице; чужой раздел, открытый по адресу, не открывается; после «Выйти» без входа ничего не открывается.',
    preconditions: ['Стенд открыт в браузере; ни одна вкладка не выполнила вход (или нажмите «Выйти»).'],
    testData: ['Учётные записи `trainee`, `instructor`, `admin` (пароли — в access.md). Ничего не создаётся.'],
    cleanup: [],
  },
);
