// S12: materials: the trainee's «Справочная база» lists the ДДС memo, the classifier and «КАРТОЧКА
// 112» and each downloads; the instructor uploads a PDF and archives it. I6 FIX1: the PDF is
// verified through «Скачать» (file name and type), never through a new browser tab — a
// screen-reading tester's browser may not show one.
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import type { Page } from '@playwright/test';
import { button, check, heading, scenario, visible, type StepDefinition } from './dsl';
import { downloadedToastCheck, loginSteps, navLink } from './steps';

const MEMO = 'Работа с АРМ-112 для ДДС от ОКр';
const CLASSIFIER = 'Классификатор происшествий v_046_24 (корректировка МВД + Департамент)';
const CARD = 'КАРТОЧКА 112';

const materialRow = (page: Page, title: string) => page.getByRole('listitem').filter({ has: page.getByText(title, { exact: true }) });

/** A one-page PDF, written where the runner can pick it (a tester uses any small PDF). */
function tinyPdf(): string {
  const body = [
    '%PDF-1.4',
    '1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj',
    '2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj',
    '3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj',
    'trailer<</Root 1 0 R>>',
    '%%EOF',
  ].join('\n');
  const file = path.join(mkdtempSync(path.join(tmpdir(), 'e2e-pdf-')), 'e2e-material.pdf');
  writeFileSync(file, body);
  return file;
}

function downloadStep(title: string, extension: string): StepDefinition {
  return {
    actor: 'trainee',
    do: `У материала «${title}» нажать «Скачать».`,
    action: async (page, ctx) => {
      const file = await ctx.download(page, () => materialRow(page, title).getByRole('button', { name: 'Скачать', exact: true }).click());
      ctx.vars.downloaded = file.fileName;
    },
    expect: [
      check(`браузер скачал файл с расширением ${extension}; его имя — то, что написано в строке материала под названием`, async (page, ctx, { expect, timeout }) => {
        const name = ctx.vars.downloaded ?? '';
        if (!name.endsWith(extension)) throw new Error(`скачан «${name}»`);
        await expect(materialRow(page, title)).toContainText(name, { timeout });
      }),
      downloadedToastCheck((ctx) => ctx.vars.downloaded ?? ''),
    ],
  };
}

export const S12 = scenario(
  'S12',
  'Материалы: справочная база стажёра, загрузка и архивация PDF преподавателем',
  ['trainee', 'instructor'],
  [
    ...loginSteps('trainee', 'TRAINEE', 'стажёра (trainee)'),
    {
      actor: 'trainee',
      do: 'В шапке, в меню, нажать «Справочная база».',
      action: async (page) => {
        await navLink(page, 'Справочная база').click();
      },
      expect: [
        heading('Справочная база'),
        check(`памятка ДДС «${MEMO}» (файл .pdf) с кнопками «Открыть» и «Скачать»`, async (page, _ctx, { expect, timeout }) => {
          await expect(materialRow(page, MEMO)).toContainText('.pdf', { timeout });
          await expect(materialRow(page, MEMO).getByRole('button', { name: 'Открыть', exact: true })).toBeVisible({ timeout });
          await expect(materialRow(page, MEMO).getByRole('button', { name: 'Скачать', exact: true })).toBeVisible({ timeout });
        }),
        check(`классификатор «${CLASSIFIER}» (файл .xlsx) с кнопкой «Скачать»`, async (page, _ctx, { expect, timeout }) => {
          await expect(materialRow(page, CLASSIFIER)).toContainText('.xlsx', { timeout });
          await expect(materialRow(page, CLASSIFIER).getByRole('button', { name: 'Скачать', exact: true })).toBeVisible({ timeout });
        }),
        check(`«${CARD}» (файл .docx) с кнопкой «Скачать»`, async (page, _ctx, { expect, timeout }) => {
          await expect(materialRow(page, CARD)).toContainText('.docx', { timeout });
          await expect(materialRow(page, CARD).getByRole('button', { name: 'Скачать', exact: true })).toBeVisible({ timeout });
        }),
        check('кнопок «Архивировать» и «Загрузить» у стажёра нет', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByRole('button', { name: 'Архивировать' })).toHaveCount(0, { timeout });
          await expect(page.getByRole('button', { name: 'Загрузить' })).toHaveCount(0, { timeout });
        }),
      ],
    },
    downloadStep(MEMO, '.pdf'),
    downloadStep(CLASSIFIER, '.xlsx'),
    downloadStep(CARD, '.docx'),
    ...loginSteps('instructor', 'INSTRUCTOR', 'преподавателя (instructor)'),
    {
      actor: 'instructor',
      do: 'В шапке, в меню, нажать «Материалы».',
      action: async (page) => {
        await navLink(page, 'Материалы').click();
      },
      expect: [
        heading('Материалы'),
        visible('поле «Название»', (page) => page.getByLabel('Название', { exact: true })),
        visible('поле «Файл» (выбор файла)', (page) => page.getByLabel('Файл', { exact: true })),
        button('Загрузить'),
        visible('галочка «Показывать архивные»', (page) => page.getByRole('checkbox', { name: 'Показывать архивные' })),
        check(`в списке «${MEMO}» с кнопками «Открыть» и «Архивировать»`, async (page, _ctx, { expect, timeout }) => {
          await expect(materialRow(page, MEMO).getByRole('button', { name: 'Архивировать', exact: true })).toBeVisible({ timeout });
        }),
      ],
    },
    {
      actor: 'instructor',
      do: '«Название» — `e2e памятка <суффикс>`; «Файл» — выбрать любой небольшой PDF; нажать «Загрузить».',
      action: async (page, ctx) => {
        ctx.vars.material = `e2e памятка ${ctx.unique}`;
        const title = ctx.vars.material;
        ctx.onCleanup(`архивировать материал ${title}`, (api) => api.archiveMaterial(title));
        await page.getByLabel('Название', { exact: true }).fill(title);
        await page.getByLabel('Файл', { exact: true }).setInputFiles(tinyPdf());
        await page.getByRole('button', { name: 'Загрузить', exact: true }).click();
      },
      expect: [
        check('в списке появился «e2e памятка <суффикс>» (файл .pdf) с кнопками «Открыть» и «Архивировать»', async (page, ctx, { expect, timeout }) => {
          const row = materialRow(page, ctx.vars.material ?? '');
          await expect(row).toContainText('.pdf', { timeout });
          await expect(row.getByRole('button', { name: 'Открыть', exact: true })).toBeVisible({ timeout });
          await expect(row.getByRole('button', { name: 'Архивировать', exact: true })).toBeVisible({ timeout });
        }),
      ],
    },
    {
      actor: 'trainee',
      do: 'Во вкладке стажёра в шапке нажать «Мои занятия», затем снова «Справочная база».',
      action: async (page) => {
        await navLink(page, 'Мои занятия').click();
        await navLink(page, 'Справочная база').click();
      },
      expect: [visible('стажёр видит новый материал «e2e памятка <суффикс>»', (page, ctx) => page.getByText(ctx.vars.material ?? '', { exact: true }))],
    },
    {
      actor: 'instructor',
      do: 'У материала «e2e памятка <суффикс>» нажать «Архивировать».',
      action: async (page, ctx) => {
        await materialRow(page, ctx.vars.material ?? '').getByRole('button', { name: 'Архивировать', exact: true }).click();
      },
      expect: [
        check('материал пропал из списка', async (page, ctx, { expect, timeout }) => {
          await expect(page.getByText(ctx.vars.material ?? '', { exact: true })).toHaveCount(0, { timeout });
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
        check('«e2e памятка <суффикс>» снова в списке с пометкой «· В архиве», без кнопки «Архивировать»', async (page, ctx, { expect, timeout }) => {
          const row = materialRow(page, ctx.vars.material ?? '');
          await expect(row).toContainText('В архиве', { timeout });
          await expect(row.getByRole('button', { name: 'Архивировать', exact: true })).toHaveCount(0, { timeout });
        }),
      ],
    },
    {
      actor: 'trainee',
      do: 'Во вкладке стажёра в шапке нажать «Мои занятия», затем снова «Справочная база».',
      action: async (page) => {
        await navLink(page, 'Мои занятия').click();
        await navLink(page, 'Справочная база').click();
      },
      expect: [
        heading('Справочная база'),
        check('архивного «e2e памятка <суффикс>» у стажёра нет', async (page, ctx, { expect, timeout }) => {
          await expect(page.getByText(MEMO, { exact: true })).toBeVisible({ timeout });
          await expect(page.getByText(ctx.vars.material ?? '', { exact: true })).toHaveCount(0, { timeout });
        }),
      ],
    },
  ],
  {
    purpose:
      'Стажёр в «Справочная база» видит памятку ДДС, классификатор и «КАРТОЧКА 112» и может их скачать (PDF проверяется кнопкой «Скачать», не новой вкладкой); преподаватель в «Материалы» загружает PDF (стажёр его видит) и архивирует его (у стажёра он пропадает).',
    preconditions: [
      'Вход ещё не выполнен ни в одной вкладке (или нажмите «Выйти» во всех).',
      'На стенде загружены три материала организатора (seed-materials). Под рукой любой небольшой PDF-файл.',
    ],
    testData: ['Материал: «Название» `e2e памятка <суффикс>`, файл — любой небольшой PDF.'],
    cleanup: ['Если `e2e памятка <суффикс>` не в архиве: преподаватель → «Материалы» → у него «Архивировать».'],
  },
);
