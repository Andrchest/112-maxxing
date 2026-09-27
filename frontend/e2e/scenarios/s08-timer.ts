// S08: a short «Решение «Принята» / «Не принята», с» (10 s) and a decision after it: the report
// shows the norm missed and the timeliness rule failed.
import { check, scenario } from './dsl';
import {
  FIRE_CHAIN,
  FIRE_SERVICE,
  closeIncidentSteps,
  legStatusStep,
  lessonCompleted,
  otherLegsDeclinedSteps,
  reopenLessonStep,
  reportRow,
  startedLessonSteps,
} from './steps';

export const S08 = scenario(
  'S08',
  'Таймер: короткий норматив решения (10 с) — в отчёте норматив не выполнен',
  ['admin', 'instructor', 'newTrainee'],
  [
    ...startedLessonSteps({ label: 'S08', acceptTimerSeconds: 10 }),
    {
      actor: 'newTrainee',
      do: 'Ничего не нажимать 15 секунд (норматив решения — 10 с, его нужно пропустить).',
      wait: { timeoutMs: 20_000, why: 'сценарий проверяет таймер: решение должно прийти позже норматива в 10 с' },
      action: async (page) => {
        await page.waitForTimeout(15_000);
      },
      expect: [
        check('карточка по-прежнему открыта, «Этап: Получено»', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByText(/Этап:\s*Получено/)).toBeVisible({ timeout });
        }),
      ],
    },
    legStatusStep('newTrainee', FIRE_SERVICE, 'Принята', { order: 'Н-8', comment: 'Поздно' }),
    ...FIRE_CHAIN.map((status) => legStatusStep('newTrainee', FIRE_SERVICE, status, { comment: `Доклад: ${status.toLowerCase()}` })),
    ...otherLegsDeclinedSteps('newTrainee'),
    ...closeIncidentSteps('newTrainee'),
    reopenLessonStep('instructor', [
      lessonCompleted,
      check('в «Время и норматив» строка «Принятие решения: Пожарно-спасательная служба 00:1x при норме 00:10 (+00:0x)» — время больше нормы, отклонение со знаком «+»', async (page, ctx, { expect, timeout }) => {
        await expect(reportRow(page, ctx)).toContainText(/Принятие решения: Пожарно-спасательная служба\s*\d\d:\d\d при норме 00:10\s*\(\+/, { timeout });
      }),
      check('«Нарушено правил» не 0; баллы меньше «18 / 18»', async (page, ctx, { expect, timeout }) => {
        const row = reportRow(page, ctx);
        await expect(row).not.toContainText('18 / 18', { timeout });
        await expect(row.getByRole('cell').nth(4)).not.toHaveText('0', { timeout });
      }),
    ]),
  ],
  {
    purpose:
      'Норматив «Решение «Принята» / «Не принята»» задаётся на карточку занятия. Стажёр решает позже 10 с — отчёт показывает время решения больше нормы с положительным отклонением и нарушенное правило своевременности.',
    preconditions: ['Вход ещё не выполнен ни в одной вкладке (или нажмите «Выйти» во всех).'],
    testData: [
      'Новый стажёр: логин `e2e-<суффикс>-newtrainee`, «Отображаемое имя» `Стажёр <суффикс>`, роль «Стажёр», пароль `Pw-<суффикс>-Aa1!`.',
      'Занятие: «Название занятия» `e2e S08 <суффикс>`, «Решение «Принята» / «Не принята», с» = 10.',
    ],
    cleanup: [
      'Если занятие `e2e S08 <суффикс>` не «Завершено»: преподаватель → «Занятия» → «Открыть» → «Прервать занятие», «Причина» «уборка» → «Прервать».',
      'Администратор → «Администрирование» → «Пользователи» → строка `e2e-<суффикс>-newtrainee` → «Заблокировать».',
    ],
  },
);
