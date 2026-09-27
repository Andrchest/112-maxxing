// S14: the «Сценарии» page lists the scenarios; archiving one hides it from the lesson form's
// «Сценарий» list, unarchiving brings it back.
import type { Page } from '@playwright/test';
import { button, check, disabledButton, heading, scenario, visible } from './dsl';
import { loginSteps, navLink } from './steps';

const TARGET = 'Горит мусор на улице, Москва, СЗАО, Щукино';
const TARGET_OPTION = `Сложность 2 · ${TARGET}`;

/** The scenario's row: the innermost block holding its title and a button. */
const scenarioRow = (page: Page) =>
  page.locator('div').filter({ has: page.getByText(TARGET, { exact: true }) }).filter({ has: page.getByRole('button') }).last();

const optionCount = (page: Page) => page.getByLabel('Сценарий', { exact: true }).locator('option', { hasText: TARGET_OPTION });

export const S14 = scenario(
  'S14',
  'Сценарии: список у преподавателя, архив и возврат из архива меняют форму занятия',
  ['instructor'],
  [
    ...loginSteps('instructor', 'INSTRUCTOR', 'преподавателя (instructor)'),
    {
      actor: 'instructor',
      do: `Посмотреть в форму «Новое занятие (несколько карточек)»: открыть список «Сценарий» в блоке «Карточка 1».`,
      expect: [
        check(`в списке «Сценарий» есть «${TARGET_OPTION}»`, async (page, _ctx, { expect, timeout }) => {
          await expect(optionCount(page)).toHaveCount(1, { timeout });
        }),
      ],
    },
    {
      actor: 'instructor',
      do: 'В шапке, в меню, нажать «Сценарии».',
      action: async (page) => {
        await navLink(page, 'Сценарии').click();
      },
      expect: [
        heading('Сценарии'),
        button('Файл сценария (YAML или JSON)', 'кнопка выбора файла «Файл сценария (YAML или JSON)»'),
        disabledButton('Проверить', 'кнопка «Проверить» (неактивна, пока файл не выбран)'),
        disabledButton('Импортировать', 'кнопка «Импортировать» (неактивна, пока файл не выбран)'),
        visible('галочка «Показывать архивные»', (page) => page.getByRole('checkbox', { name: 'Показывать архивные' })),
        check(`в списке «${TARGET}» и «Билет 1, вызов 1: …», у каждого кнопка «Архивировать»`, async (page, _ctx, { expect, timeout }) => {
          await expect(scenarioRow(page).getByRole('button', { name: 'Архивировать', exact: true })).toBeVisible({ timeout });
          await expect(page.getByText('Билет 1, вызов 1: Возгорание мусорного контейнера, пострадавших нет', { exact: true })).toBeVisible({ timeout });
        }),
      ],
    },
    {
      actor: 'instructor',
      do: `У сценария «${TARGET}» нажать «Архивировать».`,
      action: async (page, ctx) => {
        ctx.onCleanup(`вернуть из архива «${TARGET}»`, (api) => api.unarchiveScenario(TARGET));
        await scenarioRow(page).getByRole('button', { name: 'Архивировать', exact: true }).click();
      },
      expect: [
        check('сценарий пропал из списка', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByText(TARGET, { exact: true })).toHaveCount(0, { timeout });
        }),
      ],
    },
    {
      actor: 'instructor',
      do: 'Отметить галочку «Показывать архивные».',
      action: async (page) => {
        await page.getByRole('checkbox', { name: 'Показывать архивные' }).check();
      },
      expect: [
        check(`«${TARGET}» снова в списке с пометкой «В архиве» и кнопкой «Вернуть из архива»`, async (page, _ctx, { expect, timeout }) => {
          await expect(scenarioRow(page)).toContainText('В архиве', { timeout });
          await expect(scenarioRow(page).getByRole('button', { name: 'Вернуть из архива', exact: true })).toBeVisible({ timeout });
        }),
      ],
    },
    {
      actor: 'instructor',
      do: 'В шапке нажать «Занятия» и открыть список «Сценарий» в форме «Новое занятие (несколько карточек)».',
      action: async (page) => {
        await navLink(page, 'Занятия').click();
      },
      expect: [
        check(`архивного «${TARGET_OPTION}» в списке «Сценарий» нет`, async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByLabel('Сценарий', { exact: true }).locator('option', { hasText: 'Билет 1, вызов 1' }).first()).toBeAttached({ timeout });
          await expect(optionCount(page)).toHaveCount(0, { timeout });
        }),
      ],
    },
    {
      actor: 'instructor',
      do: `В шапке нажать «Сценарии», отметить «Показывать архивные», у «${TARGET}» нажать «Вернуть из архива».`,
      action: async (page) => {
        await navLink(page, 'Сценарии').click();
        await page.getByRole('checkbox', { name: 'Показывать архивные' }).check();
        await scenarioRow(page).getByRole('button', { name: 'Вернуть из архива', exact: true }).click();
      },
      expect: [
        check('пометки «В архиве» у сценария нет, кнопка снова «Архивировать»', async (page, _ctx, { expect, timeout }) => {
          await expect(scenarioRow(page).getByRole('button', { name: 'Архивировать', exact: true })).toBeVisible({ timeout });
          await expect(scenarioRow(page)).not.toContainText('В архиве', { timeout });
        }),
      ],
    },
    {
      actor: 'instructor',
      do: 'В шапке нажать «Занятия» и открыть список «Сценарий» в форме занятия.',
      action: async (page) => {
        await navLink(page, 'Занятия').click();
      },
      expect: [
        check(`«${TARGET_OPTION}» снова в списке «Сценарий»`, async (page, _ctx, { expect, timeout }) => {
          await expect(optionCount(page)).toHaveCount(1, { timeout });
        }),
      ],
    },
  ],
  {
    purpose:
      'Преподаватель видит список сценариев в «Сценарии». Архивированный сценарий пропадает из списка (и виден с «Показывать архивные» с пометкой «В архиве») и из списка «Сценарий» формы занятия; «Вернуть из архива» возвращает его в форму.',
    preconditions: [
      'Вход ещё не выполнен ни в одной вкладке (или нажмите «Выйти» во всех).',
      `Сценарий «${TARGET}» не в архиве (стенд по умолчанию).`,
    ],
    testData: [`Архивируется и возвращается сценарий «${TARGET}» (на время сценария; им не пользуются другие сценарии).`],
    cleanup: [`Если «${TARGET}» остался в архиве: «Сценарии» → «Показывать архивные» → «Вернуть из архива».`],
  },
);
