// S04: the report stays hidden from the trainee until «Выдать отчёт стажёрам», and shows after.
// Runs in «Аттестация»: in «Одна роль» and «Полный цикл» the product shows a trainee their report
// right after the card closes by design (`SessionPolicy.report_visible_to_trainee_before_release`).
import { button, check, heading, link, scenario, text, url } from './dsl';
import {
  TICKET_SCENARIO_TITLE,
  closeIncidentSteps,
  fireServiceDoneSteps,
  lessonCompleted,
  navLink,
  otherLegsDeclinedSteps,
  reopenLessonStep,
  startedLessonSteps,
} from './steps';

const historyRow = (page: import('@playwright/test').Page) => page.getByRole('row').filter({ hasText: TICKET_SCENARIO_TITLE }).first();

export const S04 = scenario(
  'S04',
  'Отчёт скрыт от стажёра до «Выдать отчёт стажёрам» (режим «Аттестация»)',
  ['admin', 'instructor', 'newTrainee'],
  [
    ...startedLessonSteps({ label: 'S04', mode: 'Аттестация' }),
    ...fireServiceDoneSteps('newTrainee'),
    ...otherLegsDeclinedSteps('newTrainee'),
    ...closeIncidentSteps('newTrainee'),
    {
      actor: 'newTrainee',
      do: 'Подождать 3 секунды после «Занятие завершено.» (отчёт по карточке считается 1–2 с; страница «История» сама не обновляется), затем в шапке, в меню, нажать «История».',
      action: async (page) => {
        await page.waitForTimeout(3000);
        await navLink(page, 'История').click();
      },
      expect: [
        heading('Мои результаты'),
        check('в «Завершённые сессии» строка сценария, в колонке «Оценка» — «ещё не опубликована»', async (page, _ctx, { expect, timeout }) => {
          await expect(historyRow(page)).toContainText('ещё не опубликована', { timeout });
        }),
        check('в строке нет процента', async (page, _ctx, { expect, timeout }) => {
          await expect(historyRow(page)).not.toContainText('%', { timeout });
        }),
      ],
    },
    {
      actor: 'newTrainee',
      do: 'В строке сценария нажать «Отчёт».',
      action: async (page) => {
        await historyRow(page).getByRole('link', { name: 'Отчёт', exact: true }).click();
      },
      expect: [
        url('адрес /report/…', /\/report\/[0-9a-f-]{36}$/),
        text('вместо отчёта сообщение «Отчёт ещё не открыт инструктором»', 'Отчёт ещё не открыт инструктором'),
        check('баллов и итога не видно (нет «Итог:»)', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByText(/Итог:/)).toHaveCount(0, { timeout });
        }),
      ],
    },
    reopenLessonStep('instructor', [lessonCompleted, button('Выдать отчёт стажёрам')]),
    {
      actor: 'instructor',
      do: 'В блоке «План занятия» нажать «Выдать отчёт стажёрам».',
      action: async (page) => {
        await page.getByRole('button', { name: 'Выдать отчёт стажёрам', exact: true }).click();
      },
      expect: [
        check('кнопка «Выдать отчёт стажёрам» исчезла', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByRole('button', { name: 'Выдать отчёт стажёрам', exact: true })).toHaveCount(0, { timeout });
        }),
      ],
    },
    {
      actor: 'newTrainee',
      do: 'Нажать «← Назад» (слева вверху), чтобы вернуться в «Историю».',
      action: async (page) => {
        await page.getByRole('link', { name: '← Назад', exact: true }).click();
      },
      expect: [
        heading('Мои результаты'),
        check('в строке сценария оценка «100%»', async (page, _ctx, { expect, timeout }) => {
          await expect(historyRow(page)).toContainText('100%', { timeout });
        }),
      ],
    },
    {
      actor: 'newTrainee',
      do: 'В строке сценария нажать «Отчёт».',
      action: async (page) => {
        await historyRow(page).getByRole('link', { name: 'Отчёт', exact: true }).click();
      },
      expect: [
        heading('Отчёт по занятию'),
        text('«Итог: Сдал»', /Итог:\s*Сдал/),
        text('«18 / 18»', /18 \/ 18/),
        link('← Назад', 'слева вверху «← Назад»'),
      ],
    },
  ],
  {
    purpose:
      'В режиме «Аттестация» стажёр после закрытия карточки не видит ни оценки в «Истории», ни отчёта — до тех пор, пока преподаватель не нажмёт «Выдать отчёт стажёрам»; после этого видит и оценку, и отчёт.',
    preconditions: ['Вход ещё не выполнен ни в одной вкладке (или нажмите «Выйти» во всех).'],
    testData: [
      'Новый стажёр: логин `e2e-<суффикс>-newtrainee`, «Отображаемое имя» `Стажёр <суффикс>`, роль «Стажёр», пароль `Pw-<суффикс>-Aa1!`.',
      'Занятие: «Название занятия» `e2e S04 <суффикс>`, «Режим занятия» «Аттестация». Номер наряда `Н-101`.',
    ],
    cleanup: [
      'Если занятие `e2e S04 <суффикс>` не «Завершено»: преподаватель → «Занятия» → «Открыть» → «Прервать занятие», «Причина» «уборка» → «Прервать».',
      'Администратор → «Администрирование» → «Пользователи» → строка `e2e-<суффикс>-newtrainee` → «Заблокировать».',
    ],
  },
);
