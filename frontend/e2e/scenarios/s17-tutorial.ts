// S17 (I7 E56): the in-app tutorial — the first-login card does not block the page, «Начать
// обучение» opens the guided tour (dimmed page, a step popover «N из M», «Назад» / «Далее» /
// «Пропустить», Esc), the header «Обучение» restarts it from the current page, the card is not
// offered again after an answer, and «Подсказки для новичков» in the user menu shows the «?» hints.
import type { Locator, Page } from '@playwright/test';
import { button, check, disabledButton, heading, notVisible, scenario, text, url, visible } from './dsl';
import { loginPageSteps, loginSteps, navLink, roleMenu } from './steps';

const card = (page: Page): Locator => page.getByRole('region', { name: 'Первое знакомство' });
const tour = (page: Page): Locator => page.getByRole('dialog').filter({ has: page.locator('[data-slot="tour-counter"]') });

function tourStep(title: string, counter: RegExp, see: string) {
  return check(see, async (page, _ctx, { expect, timeout }) => {
    await expect(tour(page)).toBeVisible({ timeout });
    await expect(tour(page).getByRole('heading', { level: 2 })).toHaveText(title, { timeout });
    await expect(tour(page).locator('[data-slot="tour-counter"]')).toHaveText(counter, { timeout });
  });
}

const noTour = notVisible('окна обучения нет, страница снова не затемнена', (page) => tour(page));
const noCard = notVisible('карточки «Впервые здесь?» внизу справа нет', (page) => card(page));

export const S17 = scenario(
  'S17',
  'Обучение: карточка при первом входе не мешает, тур по шагам, «Обучение» в шапке, подсказки для новичков',
  ['trainee', 'instructor'],
  [
    ...loginSteps('trainee', 'TRAINEE', 'стажёра (trainee)'),
    {
      actor: 'trainee',
      do: 'Посмотреть в правый нижний угол страницы (ничего не нажимать).',
      expect: [
        visible('внизу справа карточка «Впервые здесь?» с текстом «Пройдите короткое обучение»', (page) => card(page).getByText('Пройдите короткое обучение')),
        check('на карточке кнопки «Начать обучение» и «Не сейчас»', async (page, _ctx, { expect, timeout }) => {
          await expect(card(page).getByRole('button', { name: 'Начать обучение', exact: true })).toBeVisible({ timeout });
          await expect(card(page).getByRole('button', { name: 'Не сейчас', exact: true })).toBeVisible({ timeout });
        }),
        button('Обучение', 'в шапке справа кнопка «Обучение» (значок шапочки)'),
        visible('в шапке справа значок «Меню пользователя»', (page) => page.getByRole('button', { name: 'Меню пользователя', exact: true })),
        notVisible('страница не затемнена, окна поверх неё нет', (page) => page.getByRole('dialog')),
      ],
    },
    {
      actor: 'trainee',
      do: 'Не трогая карточку, в шапке, в меню, нажать «История».',
      action: async (page) => {
        await navLink(page, 'История').click();
      },
      expect: [
        url('адрес /history — карточка не мешает работать', /\/history$/),
        heading('Мои результаты'),
        visible('карточка «Впервые здесь?» осталась внизу справа', (page) => card(page)),
      ],
    },
    {
      actor: 'trainee',
      do: 'На карточке внизу справа нажать «Начать обучение».',
      action: async (page) => {
        await card(page).getByRole('button', { name: 'Начать обучение', exact: true }).click();
      },
      expect: [
        url('обучение само открыло «Мои занятия» (/sessions)', /\/sessions$/),
        tourStep('Меню разделов', /^1 из \d+$/, 'окно обучения «Меню разделов», справа вверху счётчик «1 из …»'),
        visible('меню «Мои занятия · История · Справочная база» выделено жёлтой рамкой, остальная страница затемнена', (page) => page.locator('[data-slot="tour-spotlight"]')),
        disabledButton('Назад', 'кнопка «Назад» неактивна (это первый шаг)'),
        button('Далее'),
        button('Пропустить'),
        noCard,
      ],
    },
    {
      actor: 'trainee',
      do: 'В окне обучения нажать «Далее».',
      action: async (page) => {
        await tour(page).getByRole('button', { name: 'Далее', exact: true }).click();
      },
      expect: [tourStep('Мои занятия', /^2 из \d+$/, 'окно «Мои занятия», счётчик «2 из …»'), button('Назад', 'кнопка «Назад» теперь активна')],
    },
    {
      actor: 'trainee',
      do: 'В окне обучения нажать «Назад».',
      action: async (page) => {
        await tour(page).getByRole('button', { name: 'Назад', exact: true }).click();
      },
      expect: [tourStep('Меню разделов', /^1 из \d+$/, 'снова окно «Меню разделов», «1 из …»')],
    },
    {
      actor: 'trainee',
      do: 'Нажать клавишу Esc.',
      action: async (page) => {
        await page.keyboard.press('Escape');
      },
      expect: [noTour, noCard, heading('Мои занятия')],
    },
    {
      actor: 'trainee',
      do: 'В шапке справа нажать «Обучение».',
      action: async (page) => {
        await page.getByRole('button', { name: 'Обучение', exact: true }).click();
      },
      expect: [tourStep('Меню разделов', /^1 из \d+$/, 'обучение началось заново: окно «Меню разделов», «1 из …»')],
    },
    {
      actor: 'trainee',
      do: 'В окне обучения нажать «Пропустить».',
      action: async (page) => {
        await tour(page).getByRole('button', { name: 'Пропустить', exact: true }).click();
      },
      expect: [noTour],
    },
    {
      actor: 'trainee',
      do: 'В шапке, в меню, нажать «История», затем в шапке справа — «Обучение».',
      action: async (page) => {
        await navLink(page, 'История').click();
        await page.getByRole('heading', { name: 'Мои результаты', exact: true }).waitFor();
        await page.getByRole('button', { name: 'Обучение', exact: true }).click();
      },
      expect: [
        url('остались на /history', /\/history$/),
        tourStep('Отчёт', /^\d+ из \d+$/, 'обучение началось с шагов этой страницы: окно «Отчёт» (не с первого шага)'),
        check('счётчик не «1 из …»', async (page, _ctx, { expect, timeout }) => {
          await expect(tour(page).locator('[data-slot="tour-counter"]')).not.toHaveText(/^1 из/, { timeout });
        }),
      ],
    },
    {
      actor: 'trainee',
      do: 'В окне обучения нажать «Далее».',
      action: async (page) => {
        await tour(page).getByRole('button', { name: 'Далее', exact: true }).click();
      },
      expect: [
        tourStep('История', /^\d+ из \d+$/, 'окно «История»; выделен блок «Итоги» (если у стажёра ещё нет результатов — окно по центру)'),
      ],
    },
    {
      actor: 'trainee',
      do: 'Нажать клавишу Esc.',
      action: async (page) => {
        await page.keyboard.press('Escape');
      },
      expect: [noTour, heading('Мои результаты')],
    },
    {
      actor: 'trainee',
      do: 'В шапке справа нажать «Выйти» и снова войти под стажёром (trainee) в этой же вкладке.',
      action: async (page, ctx) => {
        await page.getByRole('button', { name: 'Выйти', exact: true }).click();
        await page.getByLabel('Имя пользователя', { exact: true }).fill(ctx.credentials('trainee').username);
        await page.getByLabel('Пароль', { exact: true }).fill(ctx.credentials('trainee').password);
        await page.getByRole('button', { name: 'Войти', exact: true }).click();
      },
      expect: [heading('Мои занятия'), roleMenu('TRAINEE', 'Мои занятия'), noCard],
    },

    loginPageSteps('instructor'),
    {
      actor: 'instructor',
      do: 'Ввести логин и пароль преподавателя (instructor), нажать «Войти»; на карточке внизу справа нажать «Не сейчас».',
      action: async (page, ctx) => {
        await page.getByLabel('Имя пользователя', { exact: true }).fill(ctx.credentials('instructor').username);
        await page.getByLabel('Пароль', { exact: true }).fill(ctx.credentials('instructor').password);
        await page.getByRole('button', { name: 'Войти', exact: true }).click();
        await card(page).getByRole('button', { name: 'Не сейчас', exact: true }).click();
      },
      expect: [
        url('адрес /instructor/lessons', /\/instructor\/lessons$/),
        noCard,
        noTour,
        notVisible('рядом с «Название занятия» значка «?» нет (подсказки выключены)', (page) => page.locator('[data-slot="beginner-hint"]')),
      ],
    },
    {
      actor: 'instructor',
      do: 'В шапке справа нажать значок «Меню пользователя» (кружок с человечком).',
      action: async (page) => {
        await page.getByRole('button', { name: 'Меню пользователя', exact: true }).click();
      },
      expect: [
        check('в меню пункт «Подсказки для новичков», без галочки', async (page, _ctx, { expect, timeout }) => {
          const item = page.getByRole('menuitemcheckbox', { name: 'Подсказки для новичков' });
          await expect(item).toBeVisible({ timeout });
          await expect(item).toHaveAttribute('aria-checked', 'false', { timeout });
        }),
      ],
    },
    {
      actor: 'instructor',
      do: 'Нажать «Подсказки для новичков», затем клавишу Esc (меню закроется).',
      action: async (page) => {
        await page.getByRole('menuitemcheckbox', { name: 'Подсказки для новичков' }).click();
        await page.keyboard.press('Escape');
      },
      expect: [
        visible('в форме «Новое занятие (несколько карточек)» рядом с «Название занятия» появился значок «?»', (page) =>
          page.getByRole('button', { name: /^Подсказка: Название видят вы и стажёры/ }),
        ),
      ],
    },
    {
      actor: 'instructor',
      do: 'Навести мышь на значок «?» рядом с «Название занятия».',
      action: async (page) => {
        await page.getByRole('button', { name: /^Подсказка: Название видят вы и стажёры/ }).hover();
      },
      expect: [text('всплывает одна фраза «Название видят вы и стажёры — по нему занятие находят в списках и отчётах.»', 'Название видят вы и стажёры — по нему занятие находят в списках и отчётах.')],
    },
  ],
  {
    purpose:
      'При первом входе справа внизу появляется карточка «Впервые здесь?», которая не мешает работать; «Начать обучение» проводит по интерфейсу шаг за шагом (затемнение, рамка вокруг нужного места, «Назад» / «Далее» / «Пропустить», Esc закрывает); кнопка «Обучение» в шапке запускает обучение снова — со страницы, на которой вы находитесь; ответ на карточку запоминается; «Подсказки для новичков» в меню пользователя включают значки «?» с одной фразой у ключевых полей.',
    preconditions: [
      'Стенд открыт в браузере; ни одна вкладка не выполнила вход (или нажмите «Выйти»).',
      'Браузер «чистый» для этих учётных записей: карточка «Впервые здесь?» ещё не закрывалась (новое окно в режиме инкогнито, или очистите данные сайта).',
    ],
    testData: ['Учётные записи `trainee` и `instructor`. Ничего не создаётся.'],
    cleanup: [],
  },
);
