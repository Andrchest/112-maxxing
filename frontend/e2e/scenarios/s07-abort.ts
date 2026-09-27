// S07: «Прервать занятие» mid-card: the lesson is «Прервано» and the card shows in the report
// without points.
import { button, check, disabledButton, heading, scenario, text, visible } from './dsl';
import { FIRE_SERVICE, legStatusStep, lessonCardRow, planCard, startedLessonSteps } from './steps';

export const S07 = scenario(
  'S07',
  'Досрочное прерывание: «Прервать занятие» — карточка в отчёте без баллов',
  ['admin', 'instructor', 'newTrainee'],
  [
    ...startedLessonSteps({ label: 'S07' }),
    legStatusStep('newTrainee', FIRE_SERVICE, 'Принята', { order: 'Н-7' }),
    {
      actor: 'instructor',
      do: 'На странице занятия в блоке «План занятия» нажать «Прервать занятие».',
      action: async (page) => {
        await page.getByRole('button', { name: 'Прервать занятие', exact: true }).click();
      },
      expect: [
        visible('окно «Прервать занятие»', (page) => page.getByRole('dialog', { name: 'Прервать занятие' })),
        visible('поле «Причина»', (page) => page.getByRole('dialog').getByLabel('Причина', { exact: true })),
        disabledButton('Прервать', 'кнопка «Прервать» неактивна, пока причина пустая'),
        button('Отмена'),
      ],
    },
    {
      actor: 'instructor',
      do: 'В «Причина» ввести «Проверка прерывания», нажать «Прервать».',
      action: async (page) => {
        await page.getByRole('dialog').getByLabel('Причина', { exact: true }).fill('Проверка прерывания');
        await page.getByRole('dialog').getByRole('button', { name: 'Прервать', exact: true }).click();
      },
      expect: [
        check('окно закрылось', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByRole('dialog')).toHaveCount(0, { timeout });
        }),
        check('«План занятия» в состоянии «Прервано»', async (page, _ctx, { expect, timeout }) => {
          await expect(planCard(page)).toContainText('Прервано', { timeout });
        }),
        check('кнопок «Начать занятие» и «Прервать занятие» больше нет', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByRole('button', { name: 'Прервать занятие', exact: true })).toHaveCount(0, { timeout });
          await expect(page.getByRole('button', { name: 'Начать занятие', exact: true })).toHaveCount(0, { timeout });
        }),
        button('Выдать отчёт стажёрам'),
        check('у карточки состояние «Прервано»', async (page, _ctx, { expect, timeout }) => {
          await expect(lessonCardRow(page)).toContainText('Прервано', { timeout });
        }),
        heading('Отчёты по карточкам', 'блок «Отчёты по карточкам»'),
        text('у карточки «Без оценки: карточка не завершена»', 'Без оценки: карточка не завершена'),
        check('в отчёте нет строки с баллами «… / 18»', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByText(/\d+ \/ 18/)).toHaveCount(0, { timeout });
        }),
      ],
    },
    {
      actor: 'newTrainee',
      do: 'Посмотреть на рабочее место ДДС у стажёра (ничего не нажимать).',
      expect: [
        text('вместо карточки — сообщение о завершении занятия («Занятие завершено.» или «Занятие прервано»)', /Занятие (завершено\.|прервано)/),
      ],
    },
  ],
  {
    purpose:
      'Преподаватель прерывает идущее занятие («Прервать занятие» с причиной): занятие и карточка «Прервано», в «Отчёты по карточкам» карточка помечена «Без оценки: карточка не завершена», баллов нет.',
    preconditions: ['Вход ещё не выполнен ни в одной вкладке (или нажмите «Выйти» во всех).'],
    testData: [
      'Новый стажёр: логин `e2e-<суффикс>-newtrainee`, «Отображаемое имя» `Стажёр <суффикс>`, роль «Стажёр», пароль `Pw-<суффикс>-Aa1!`.',
      'Занятие: «Название занятия» `e2e S07 <суффикс>`. Причина прерывания «Проверка прерывания».',
    ],
    cleanup: ['Администратор → «Администрирование» → «Пользователи» → строка `e2e-<суффикс>-newtrainee` → «Заблокировать».'],
  },
);
