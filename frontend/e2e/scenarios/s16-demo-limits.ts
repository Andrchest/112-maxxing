// S16: the demo stand's EXPECTED limitations, checked as such: no voice models, so the UI says
// «Готовность: Не готово», the ДДС phone connects silently and the report says «Стенограмма
// недоступна.». These steps pass when the interface is honest about it.
import { button, check, heading, scenario, text } from './dsl';
import {
  FIRE_SERVICE,
  OTHER_SERVICES,
  closeIncidentSteps,
  legStatusStep,
  navLink,
  openSessionReportStep,
  reopenLessonStep,
  startedLessonSteps,
} from './steps';

export const S16 = scenario(
  'S16',
  'Ограничения демо-стенда показаны честно: «Готовность: Не готово», звонок без звука, «Стенограмма недоступна.»',
  ['admin', 'instructor', 'newTrainee'],
  [
    ...startedLessonSteps({ label: 'S16' }),
    {
      actor: 'newTrainee',
      do: 'В блоке «Телефон» нажать «Позвонить заявителю».',
      wait: { timeoutMs: 15_000, why: 'соединение звонка (LiveKit) устанавливается несколько секунд' },
      action: async (page) => {
        await page.getByRole('button', { name: 'Позвонить заявителю', exact: true }).click();
      },
      expect: [
        text('в блоке «Телефон» — «Разговор» (перед этим может мелькнуть «Набор номера…»); собеседник молчит — это ожидаемо', 'Разговор'),
        button('Положить трубку'),
      ],
    },
    {
      actor: 'newTrainee',
      do: 'Нажать «Положить трубку».',
      action: async (page) => {
        await page.getByRole('button', { name: 'Положить трубку', exact: true }).click();
      },
      expect: [text('в блоке «Телефон» — «Звонок завершён»', 'Звонок завершён'), text('и «трубка положена · <длительность>»', /трубка положена/)],
    },
    legStatusStep('newTrainee', FIRE_SERVICE, 'Не принята', { comment: 'Проверка ограничений' }),
    ...OTHER_SERVICES.map((service) => legStatusStep('newTrainee', service, 'Не принята', { comment: 'Не требуется' })),
    ...closeIncidentSteps('newTrainee'),
    {
      actor: 'instructor',
      do: 'В шапке, в меню, нажать «Сессии».',
      action: async (page) => {
        await navLink(page, 'Сессии').click();
      },
      expect: [
        heading('Инструктор'),
        text('в шапке справа значок «Готовность: Не готово» (голосовые модели на стенде не запущены — ожидаемо)', /Готовность:\s*Не готово/),
      ],
    },
    reopenLessonStep('instructor', []),
    openSessionReportStep('instructor', [
      text('раздел «Стенограмма и запись»', 'Стенограмма и запись'),
      text('в нём «Стенограмма недоступна.» (голоса нет — ожидаемо)', 'Стенограмма недоступна.'),
      check('отчёт при этом построен: есть «Итог:» и баллы «… / 18»', async (page, _ctx, { expect, timeout }) => {
        await expect(page.getByText(/Итог:/).first()).toBeVisible({ timeout });
        await expect(page.getByText(/\d+ \/ 18/).first()).toBeVisible({ timeout });
      }),
    ]),
  ],
  {
    purpose:
      'На демо-стенде не запущены распознавание речи, языковая модель и синтез речи. Это ОЖИДАЕМО. Сценарий проверяет, что интерфейс честно это показывает: «Готовность: Не готово» у преподавателя, звонок ДДС соединяется без звука, в отчёте «Стенограмма недоступна.» — и что всё остальное (карточка, статусы, отчёт) при этом работает.',
    preconditions: ['Вход ещё не выполнен ни в одной вкладке (или нажмите «Выйти» во всех). Браузеру разрешён микрофон (или его запрос можно подтвердить).'],
    testData: [
      'Новый стажёр: логин `e2e-<суффикс>-newtrainee`, «Отображаемое имя» `Стажёр <суффикс>`, роль «Стажёр», пароль `Pw-<суффикс>-Aa1!`.',
      'Занятие: «Название занятия» `e2e S16 <суффикс>`.',
    ],
    cleanup: [
      'Если занятие `e2e S16 <суффикс>` не «Завершено»: преподаватель → «Занятия» → «Открыть» → «Прервать занятие», «Причина» «уборка» → «Прервать».',
      'Администратор → «Пользователи» → строка `e2e-<суффикс>-newtrainee` → «Заблокировать».',
    ],
  },
);
