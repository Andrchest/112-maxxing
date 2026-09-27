// S03: the ДДС status form's own checks — «Не принята» and «Отказ от выполнения работ» need a
// comment (the message is shown and nothing is saved), and a service's statuses go strictly in
// the memo's order (the «Статус» list offers only the next allowed ones).
import { button, check, scenario, text, visible, type Expectation, type StepDefinition } from './dsl';
import { FIRE_SERVICE, legStatusStep, legTab, openLegEditor, startedLessonSteps } from './steps';

function statusOptions(see: string, offered: string[], notOffered: string[]): Expectation {
  return check(see, async (page, _ctx, { expect, timeout }) => {
    const select = page.getByLabel('Статус', { exact: true });
    await expect(select).toBeVisible({ timeout });
    for (const option of offered) await expect(select.locator('option', { hasText: new RegExp(`^${option}$`) })).toHaveCount(1, { timeout });
    for (const option of notOffered) await expect(select.locator('option', { hasText: new RegExp(`^${option}$`) })).toHaveCount(0, { timeout });
  });
}

const commentRequired: Expectation = text('под полем «Комментарий» красное сообщение «Укажите комментарий.»', 'Укажите комментарий.');

function formStillOpen(service: string, status: string): Expectation {
  return check(`форма не закрылась, на вкладке «${service}» статус не «${status}»`, async (page, _ctx, { expect, timeout }) => {
    await expect(page.getByRole('button', { name: 'Подтвердить', exact: true })).toBeVisible({ timeout });
    await expect(legTab(page, service)).not.toContainText(status, { timeout });
  });
}

function cancelStep(service: string): StepDefinition {
  return {
    actor: 'newTrainee',
    do: 'Нажать крестик «Отмена» справа от галочки.',
    action: async (page) => {
      await page.getByRole('button', { name: 'Отмена', exact: true }).click();
    },
    expect: [
      check('форма статуса закрылась', async (page, _ctx, { expect, timeout }) => {
        await expect(page.getByRole('button', { name: 'Подтвердить', exact: true })).toHaveCount(0, { timeout });
      }),
      button('Изменить статус', `в окне вкладки «${service}» снова карандаш «Изменить статус»`),
    ],
  };
}

export const S03 = scenario(
  'S03',
  'Валидация ДДС: обязательный комментарий и порядок статусов службы',
  ['admin', 'instructor', 'newTrainee'],
  [
    ...startedLessonSteps({ label: 'S03' }),
    {
      actor: 'newTrainee',
      do: `Внизу, в полосе «СЛУЖБЫ:», нажать вкладку «${FIRE_SERVICE}».`,
      action: async (page) => {
        await legTab(page, FIRE_SERVICE).click();
      },
      expect: [
        visible('над вкладкой открылось окно истории: «Записей пока нет.»', (page) => page.getByText('Записей пока нет.')),
        button('Изменить статус', 'в окне карандаш «Изменить статус»'),
      ],
    },
    {
      actor: 'newTrainee',
      do: 'Нажать карандаш «Изменить статус».',
      action: async (page) => {
        await page.getByRole('button', { name: 'Изменить статус', exact: true }).click();
      },
      expect: [
        statusOptions('в списке «Статус» ровно два варианта: «Принята» и «Не принята» (других статусов нет)', ['Принята', 'Не принята'], [
          'Начало реагирования',
          'Прибытие',
          'Проведение работ',
          'Работы завершены',
        ]),
        visible('поле «Номер наряда»', (page) => page.getByLabel('Номер наряда', { exact: true })),
        visible('поле «Комментарий» (пустое)', (page) => page.getByLabel('Комментарий', { exact: true })),
        button('Подтвердить', 'галочка «Подтвердить»'),
        button('Отмена', 'крестик «Отмена»'),
      ],
    },
    {
      actor: 'newTrainee',
      do: 'В «Статус» выбрать «Не принята», «Комментарий» оставить пустым, нажать галочку «Подтвердить».',
      action: async (page) => {
        await page.getByLabel('Статус', { exact: true }).selectOption({ label: 'Не принята' });
        await page.getByRole('button', { name: 'Подтвердить', exact: true }).click();
      },
      expect: [commentRequired, formStillOpen(FIRE_SERVICE, 'Не принята')],
    },
    cancelStep(FIRE_SERVICE),
    legStatusStep('newTrainee', FIRE_SERVICE, 'Принята', { order: 'Н-1' }, [
      text('«Этап: Принято к исполнению»', /Этап:\s*Принято к исполнению/),
    ]),
    {
      actor: 'newTrainee',
      do: `В окне вкладки «${FIRE_SERVICE}» снова нажать карандаш «Изменить статус».`,
      action: async (page) => {
        await openLegEditor(page, FIRE_SERVICE);
      },
      expect: [
        statusOptions(
          '«Статус» предлагает следующий по памятке «Начало реагирования» и «Отказ от выполнения работ»; «Принята», «Не принята», «Прибытие», «Проведение работ», «Работы завершены» не предлагаются',
          ['Начало реагирования', 'Отказ от выполнения работ'],
          ['Принята', 'Не принята', 'Прибытие', 'Проведение работ', 'Работы завершены'],
        ),
      ],
    },
    {
      actor: 'newTrainee',
      do: 'В «Статус» выбрать «Отказ от выполнения работ», «Комментарий» оставить пустым, нажать галочку «Подтвердить».',
      action: async (page) => {
        await page.getByLabel('Статус', { exact: true }).selectOption({ label: 'Отказ от выполнения работ' });
        await page.getByRole('button', { name: 'Подтвердить', exact: true }).click();
      },
      expect: [commentRequired, formStillOpen(FIRE_SERVICE, 'Отказ от выполнения работ')],
    },
    cancelStep(FIRE_SERVICE),
    legStatusStep('newTrainee', FIRE_SERVICE, 'Начало реагирования', { comment: 'Выехали' }),
    {
      actor: 'newTrainee',
      do: 'Снова нажать карандаш «Изменить статус».',
      action: async (page) => {
        await openLegEditor(page, FIRE_SERVICE);
      },
      expect: [
        statusOptions('«Статус» предлагает «Прибытие»; «Проведение работ» и «Работы завершены» (через шаг) не предлагаются', ['Прибытие'], [
          'Принята',
          'Начало реагирования',
          'Проведение работ',
          'Работы завершены',
        ]),
      ],
    },
    cancelStep(FIRE_SERVICE),
    {
      actor: 'newTrainee',
      do: 'Внизу нажать вкладку «ЦОДД», в её окне — карандаш «Изменить статус»; «Статус» «Не принята», «Комментарий» — «Не требуется»; галочка «Подтвердить».',
      action: async (page) => {
        await openLegEditor(page, 'ЦОДД');
        await page.getByLabel('Статус', { exact: true }).selectOption({ label: 'Не принята' });
        await page.getByLabel('Комментарий', { exact: true }).fill('Не требуется');
        await page.getByRole('button', { name: 'Подтвердить', exact: true }).click();
      },
      expect: [
        check('с комментарием «Не принята» сохранилась: на вкладке «ЦОДД» статус «Не принята»', async (page, _ctx, { expect, timeout }) => {
          await expect(legTab(page, 'ЦОДД')).toContainText('Не принята', { timeout });
        }),
        visible('в истории «ЦОДД» строка «… Не принята · Не требуется»', (page) => page.getByText(/Не принята\s*·\s*Не требуется/)),
      ],
    },
  ],
  {
    purpose:
      'Форма статуса службы у ДДС не принимает «Не принята» и «Отказ от выполнения работ» без комментария (видно сообщение «Укажите комментарий.», статус не сохраняется) и предлагает статусы строго по порядку памятки: сначала только «Принята»/«Не принята», потом «Начало реагирования», потом «Прибытие» и т. д.',
    preconditions: ['Вход ещё не выполнен ни в одной вкладке (или нажмите «Выйти» во всех).'],
    testData: [
      'Новый стажёр: логин `e2e-<суффикс>-newtrainee`, «Отображаемое имя» `Стажёр <суффикс>`, роль «Стажёр», пароль `Pw-<суффикс>-Aa1!`.',
      'Занятие: «Название занятия» `e2e S03 <суффикс>`. Номер наряда `Н-1`.',
    ],
    cleanup: [
      'Преподаватель → «Занятия» → у `e2e S03 <суффикс>` «Открыть» → «Прервать занятие», «Причина» «уборка» → «Прервать».',
      'Администратор → «Администрирование» → «Пользователи» → строка `e2e-<суффикс>-newtrainee` → «Заблокировать».',
    ],
  },
);
