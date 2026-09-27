// S09: instructors change only their own lessons: a second instructor sees another's lesson, but
// «Начать занятие» is disabled there with a hint; on their own lesson it works.
import { button, check, disabledButton, heading, scenario, text, url, visible } from './dsl';
import { createLessonSteps, createUserSteps, loginSteps, navLink, planCard, startLessonStep } from './steps';

export const S09 = scenario(
  'S09',
  'Владение: второй преподаватель видит чужое занятие, но запустить его не может; своё — может',
  ['admin', 'instructor', 'secondInstructor'],
  [
    ...loginSteps('admin', 'ADMIN', 'администратора (admin)'),
    ...createUserSteps('newTrainee', 'Стажёр', 'стажёр'),
    ...createUserSteps('secondInstructor', 'Инструктор', 'преподаватель').slice(1),
    ...loginSteps('instructor', 'INSTRUCTOR', 'преподавателя (instructor)'),
    ...createLessonSteps({ instructor: 'instructor', trainee: 'newTrainee', label: 'S09 чужое' }),
    ...loginSteps('secondInstructor', 'INSTRUCTOR', 'второго преподавателя (логин и пароль из «Тестовых данных»)'),
    {
      actor: 'secondInstructor',
      do: 'В списке «Занятия (несколько карточек)» найти занятие «e2e S09 чужое <суффикс>» (его создал преподаватель instructor) и нажать у него «Открыть».',
      action: async (page, ctx) => {
        await page.getByRole('listitem').filter({ hasText: `e2e S09 чужое ${ctx.unique}` }).getByRole('link', { name: 'Открыть', exact: true }).click();
      },
      expect: [
        url('открылась страница чужого занятия', /\/instructor\/lessons\/[0-9a-f-]{36}$/),
        visible('заголовок «e2e S09 чужое <суффикс>»', (page, ctx) => page.getByRole('heading', { name: `e2e S09 чужое ${ctx.unique}`, exact: true })),
        check('«План занятия» в состоянии «Создано»', async (page, _ctx, { expect, timeout }) => {
          await expect(planCard(page)).toContainText('Создано', { timeout });
        }),
        disabledButton('Начать занятие'),
        disabledButton('Прервать занятие'),
        text('под кнопками подсказка «Изменять может только преподаватель, создавший занятие»', 'Изменять может только преподаватель, создавший занятие'),
      ],
    },
    {
      actor: 'secondInstructor',
      do: 'В шапке, в меню, нажать «Занятия».',
      action: async (page) => {
        await navLink(page, 'Занятия').click();
      },
      expect: [heading('Новое занятие (несколько карточек)', 'форма «Новое занятие (несколько карточек)»')],
    },
    ...createLessonSteps({ instructor: 'secondInstructor', trainee: 'newTrainee', label: 'S09 своё' }).slice(1),
    {
      actor: 'secondInstructor',
      do: 'Посмотреть на блок «План занятия» своего занятия (ничего не нажимать).',
      expect: [
        button('Начать занятие', 'кнопка «Начать занятие» активна'),
        check('подсказки «Изменять может только преподаватель, создавший занятие» нет', async (page, _ctx, { expect, timeout }) => {
          await expect(page.getByText('Изменять может только преподаватель, создавший занятие')).toHaveCount(0, { timeout });
        }),
      ],
    },
    startLessonStep('secondInstructor'),
  ],
  {
    purpose:
      'Преподаватель меняет только свои занятия: второй преподаватель видит занятие первого, но «Начать занятие» и «Прервать занятие» там неактивны с подсказкой; своё занятие он создаёт и запускает.',
    preconditions: ['Вход ещё не выполнен ни в одной вкладке (или нажмите «Выйти» во всех).'],
    testData: [
      'Новый стажёр: логин `e2e-<суффикс>-newtrainee`, «Отображаемое имя» `Стажёр <суффикс>`, роль «Стажёр», пароль `Pw-<суффикс>-Aa1!`.',
      'Второй преподаватель: логин `e2e-<суффикс>-secondinstructor`, «Отображаемое имя» `Преподаватель <суффикс>`, роль «Инструктор», пароль `Pw-<суффикс>-Aa1!`.',
      'Занятия: `e2e S09 чужое <суффикс>` (создаёт instructor) и `e2e S09 своё <суффикс>` (создаёт второй преподаватель).',
    ],
    cleanup: [
      'Преподаватель instructor → «Занятия» → `e2e S09 чужое <суффикс>` → «Открыть» → «Прервать занятие», «Причина» «уборка» → «Прервать».',
      'Второй преподаватель → «Занятия» → `e2e S09 своё <суффикс>` → «Открыть» → «Прервать занятие», «Причина» «уборка» → «Прервать».',
      'Администратор → «Пользователи» → «Заблокировать» у `e2e-<суффикс>-newtrainee` и у `e2e-<суффикс>-secondinstructor`.',
    ],
  },
);
