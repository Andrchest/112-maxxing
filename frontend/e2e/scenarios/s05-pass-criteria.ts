// S05: strict «сдал / не сдал» criteria: a card worked with a missed rule is «Не сдал», and the
// report names the criterion that did not hold.
import { check, scenario, text } from './dsl';
import {
  FIRE_SERVICE,
  OTHER_SERVICES,
  closeIncidentSteps,
  legStatusStep,
  lessonCompleted,
  openSessionReportStep,
  reopenLessonStep,
  reportRow,
  startedLessonSteps,
} from './steps';

export const S05 = scenario(
  'S05',
  'Критерии «сдал / не сдал»: строгие критерии дают «Не сдал» с названием невыполненного критерия',
  ['admin', 'instructor', 'newTrainee'],
  [
    ...startedLessonSteps({ label: 'S05', strictCriteria: { minScore: 100, maxFailedRules: 0 } }),
    legStatusStep('newTrainee', FIRE_SERVICE, 'Не принята', { comment: 'Нет сил' }),
    ...OTHER_SERVICES.map((service) => legStatusStep('newTrainee', service, 'Не принята', { comment: 'Не требуется' })),
    ...closeIncidentSteps('newTrainee'),
    reopenLessonStep('instructor', [
      lessonCompleted,
      check('в «Отчёты по карточкам» строка стажёра: баллы меньше максимума (например «14 / 18»), «Итог» — «Не сдал»', async (page, ctx, { expect, timeout }) => {
        const row = reportRow(page, ctx);
        await expect(row).toBeVisible({ timeout });
        await expect(row).not.toContainText('18 / 18', { timeout });
        await expect(row).toContainText('Не сдал', { timeout });
      }),
      check('под «Не сдал» — «Процент баллов ниже порога» и «Нарушено правил больше допустимого»', async (page, ctx, { expect, timeout }) => {
        await expect(reportRow(page, ctx)).toContainText('Процент баллов ниже порога', { timeout });
        await expect(reportRow(page, ctx)).toContainText('Нарушено правил больше допустимого', { timeout });
      }),
    ]),
    openSessionReportStep('instructor', [
      text('«Итог: Не сдал»', /Итог:\s*Не сдал/),
      text('невыполненный критерий «Процент баллов ниже порога»', 'Процент баллов ниже порога'),
      text('невыполненный критерий «Нарушено правил больше допустимого»', 'Нарушено правил больше допустимого'),
      text('строка «Критерии: Процент баллов не меньше 100%; Нарушенных правил не больше 0…»', /Критерии: Процент баллов не меньше 100%; Нарушенных правил не больше 0/),
    ]),
  ],
  {
    purpose:
      'Преподаватель задаёт строгие критерии (100 % баллов и ни одного нарушенного правила); стажёр отказывает пожарной службе («Не принята»), поэтому правило «Работы службы … завершены» не выполнено. В отчёте — «Не сдал» и названия невыполненных критериев.',
    preconditions: ['Вход ещё не выполнен ни в одной вкладке (или нажмите «Выйти» во всех).'],
    testData: [
      'Новый стажёр: логин `e2e-<суффикс>-newtrainee`, «Отображаемое имя» `Стажёр <суффикс>`, роль «Стажёр», пароль `Pw-<суффикс>-Aa1!`.',
      'Занятие: «Название занятия» `e2e S05 <суффикс>`; критерии: «Минимальный процент баллов» 100, «Не больше нарушенных правил» 0.',
    ],
    cleanup: [
      'Если занятие `e2e S05 <суффикс>` не «Завершено»: преподаватель → «Занятия» → «Открыть» → «Прервать занятие», «Причина» «уборка» → «Прервать».',
      'Администратор → «Администрирование» → «Пользователи» → строка `e2e-<суффикс>-newtrainee` → «Заблокировать».',
    ],
  },
);
