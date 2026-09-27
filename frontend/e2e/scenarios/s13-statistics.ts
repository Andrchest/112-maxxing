// S13: statistics and rating: after a lesson like S02 the new trainee is in «Статистика обучаемых»
// and in «Рейтинг»; «Скачать CSV» downloads a file with the «Рабочее место» column.
import type { Page } from '@playwright/test';
import { button, check, heading, scenario } from './dsl';
import {
  closeIncidentSteps,
  fireServiceDoneSteps,
  navLink,
  otherLegsDeclinedSteps,
  startedLessonSteps,
} from './steps';

const statsRow = (page: Page, name: string) => page.getByRole('row').filter({ hasText: name });
/** «Рейтинг» is the second table of the page, under its own heading. */
const ratingTable = (page: Page) => page.getByRole('table').nth(1);

export const S13 = scenario(
  'S13',
  'Статистика и рейтинг: новый стажёр в таблице и рейтинге, «Скачать CSV» с «Рабочее место»',
  ['admin', 'instructor', 'newTrainee'],
  [
    ...startedLessonSteps({ label: 'S13' }),
    ...fireServiceDoneSteps('newTrainee'),
    ...otherLegsDeclinedSteps('newTrainee'),
    ...closeIncidentSteps('newTrainee'),
    {
      actor: 'instructor',
      do: 'Подождать 3 секунды, затем в шапке, в меню, нажать «Статистика».',
      action: async (page) => {
        await page.waitForTimeout(3000);
        await navLink(page, 'Статистика').click();
      },
      expect: [
        heading('Статистика обучаемых'),
        check('фильтры «Группа» («Все обучаемые»), «С даты», «По дату (не включая)»', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByLabel('Группа', { exact: true }).locator('option:checked')).toHaveText('Все обучаемые', { timeout });
          await expect(page.getByLabel('С даты', { exact: true })).toBeVisible({ timeout });
          await expect(page.getByLabel('По дату (не включая)', { exact: true })).toBeVisible({ timeout });
        }),
        button('Скачать CSV', 'кнопки «Скачать CSV» (у таблицы и у рейтинга)'),
        check('в таблице строка «Стажёр <суффикс>»: «Сессий» 1, «Занятий» 1, «Средний процент» 100%', async (page, ctx, { expect, timeout }) => {
          const row = statsRow(page, ctx.vars['newTrainee.displayName'] ?? '').first();
          await expect(row).toBeVisible({ timeout });
          await expect(row.getByRole('cell').nth(1)).toHaveText('1', { timeout });
          await expect(row.getByRole('cell').nth(2)).toHaveText('1', { timeout });
          await expect(row).toContainText('100%', { timeout });
        }),
        heading('Рейтинг', 'блок «Рейтинг» с колонками «Место», «Обучаемый», «Средний процент», «Сдано»'),
        check('в «Рейтинг» есть строка «Стажёр <суффикс>» с местом и «100%»', async (page, ctx, { expect, timeout }) => {
          const row = ratingTable(page).getByRole('row').filter({ hasText: ctx.vars['newTrainee.displayName'] ?? '' });
          await expect(row).toBeVisible({ timeout });
          await expect(row.getByRole('cell').first()).toHaveText(/^\d+$/, { timeout });
          await expect(row).toContainText('100%', { timeout });
        }),
      ],
    },
    {
      actor: 'instructor',
      do: 'Нажать первую кнопку «Скачать CSV» (над таблицей обучаемых) и открыть файл.',
      action: async (page, ctx) => {
        const file = await ctx.download(page, () => page.getByRole('button', { name: 'Скачать CSV', exact: true }).first().click());
        ctx.vars.csvName = file.fileName;
        ctx.vars.csv = file.text();
      },
      expect: [
        check('скачался файл .csv', async (_page, ctx) => {
          if (!(ctx.vars.csvName ?? '').endsWith('.csv')) throw new Error(`скачан «${ctx.vars.csvName}»`);
        }),
        check('в первой строке файла есть колонка «Рабочее место»', async (_page, ctx) => {
          const header = (ctx.vars.csv ?? '').replace(/^\uFEFF/, '').split(/\r?\n/)[0] ?? '';
          if (!header.includes('Рабочее место')) throw new Error(`заголовок: ${header.slice(0, 200)}`);
        }),
        check('в файле есть строка нового стажёра (его логин `e2e-<суффикс>-newtrainee`)', async (_page, ctx) => {
          if (!(ctx.vars.csv ?? '').includes(ctx.vars['newTrainee.username'] ?? '')) throw new Error('логина нового стажёра в файле нет');
        }),
      ],
    },
    {
      actor: 'instructor',
      do: 'В блоке «Рейтинг» нажать его «Скачать CSV» и открыть файл.',
      action: async (page, ctx) => {
        const file = await ctx.download(page, () => page.getByRole('button', { name: 'Скачать CSV', exact: true }).last().click());
        ctx.vars.ratingCsvName = file.fileName;
        ctx.vars.ratingCsv = file.text();
      },
      expect: [
        check('скачался файл .csv, в нём «Стажёр <суффикс>»', async (_page, ctx) => {
          if (!(ctx.vars.ratingCsvName ?? '').endsWith('.csv')) throw new Error(`скачан «${ctx.vars.ratingCsvName}»`);
          if (!(ctx.vars.ratingCsv ?? '').includes(ctx.vars['newTrainee.displayName'] ?? '')) throw new Error('нового стажёра в рейтинге нет');
        }),
      ],
    },
  ],
  {
    purpose:
      'После полного прогона карточки (как S02) новый стажёр появляется в «Статистика обучаемых» и в «Рейтинг»; «Скачать CSV» скачивает файл с колонкой «Рабочее место» и строкой стажёра.',
    preconditions: ['Вход ещё не выполнен ни в одной вкладке (или нажмите «Выйти» во всех).'],
    testData: [
      'Новый стажёр: логин `e2e-<суффикс>-newtrainee`, «Отображаемое имя» `Стажёр <суффикс>`, роль «Стажёр», пароль `Pw-<суффикс>-Aa1!`.',
      'Занятие: «Название занятия» `e2e S13 <суффикс>`. Номер наряда `Н-101`.',
    ],
    cleanup: [
      'Если занятие `e2e S13 <суффикс>` не «Завершено»: преподаватель → «Занятия» → «Открыть» → «Прервать занятие», «Причина» «уборка» → «Прервать».',
      'Администратор → «Пользователи» → строка `e2e-<суффикс>-newtrainee` → «Заблокировать».',
    ],
  },
);
