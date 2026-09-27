// S06: a typo the trainee types into a ДДС status comment («пажар») shows in the report's
// «Грамотность и адреса».
import { check, heading, scenario } from './dsl';
import {
  closeIncidentSteps,
  fireServiceDoneSteps,
  lessonCompleted,
  openSessionReportStep,
  otherLegsDeclinedSteps,
  reopenLessonStep,
  reportRow,
  startedLessonSteps,
} from './steps';

export const S06 = scenario(
  'S06',
  'Грамотность: опечатка в комментарии ДДС видна в «Грамотность и адреса»',
  ['admin', 'instructor', 'newTrainee'],
  [
    ...startedLessonSteps({ label: 'S06' }),
    ...fireServiceDoneSteps('newTrainee', 'Выехали на пажар'),
    ...otherLegsDeclinedSteps('newTrainee'),
    ...closeIncidentSteps('newTrainee'),
    reopenLessonStep('instructor', [
      lessonCompleted,
      check('в строке стажёра в «Отчёты по карточкам» колонка «Грамотность» — не «0» и не «—» (есть замечание)', async (page, ctx, { expect, timeout }) => {
        const cell = reportRow(page, ctx).getByRole('cell').last();
        await expect(cell).toHaveText(/^[1-9]\d*$/, { timeout });
      }),
    ]),
    openSessionReportStep('instructor', [
      heading('Грамотность и адреса', 'раздел «Грамотность и адреса»'),
      check('в разделе замечание со словом «пажар» (поле «Комментарий к статусу (ДДС)»)', async (page, _ctx, { expect, timeout }) => {
        const section = page.locator('[data-slot="card"]').filter({ has: page.getByRole('heading', { name: 'Грамотность и адреса' }) });
        await expect(section).toContainText('пажар', { timeout });
        await expect(section).toContainText('Комментарий к статусу (ДДС)', { timeout });
      }),
    ]),
  ],
  {
    purpose: 'Проверка грамотности находит слово с ошибкой, которое стажёр набрал в комментарии к статусу службы, и показывает его в отчёте в разделе «Грамотность и адреса».',
    preconditions: ['Вход ещё не выполнен ни в одной вкладке (или нажмите «Выйти» во всех).'],
    testData: [
      'Новый стажёр: логин `e2e-<суффикс>-newtrainee`, «Отображаемое имя» `Стажёр <суффикс>`, роль «Стажёр», пароль `Pw-<суффикс>-Aa1!`.',
      'Занятие: «Название занятия» `e2e S06 <суффикс>`. Комментарий к статусу «Принята» пожарной службы — `Выехали на пажар` (с ошибкой, так и надо).',
    ],
    cleanup: [
      'Если занятие `e2e S06 <суффикс>` не «Завершено»: преподаватель → «Занятия» → «Открыть» → «Прервать занятие», «Причина» «уборка» → «Прервать».',
      'Администратор → «Администрирование» → «Пользователи» → строка `e2e-<суффикс>-newtrainee` → «Заблокировать».',
    ],
  },
);
