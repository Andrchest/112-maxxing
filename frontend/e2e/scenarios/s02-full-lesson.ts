// S02: the full lesson cycle of docs/demo-scenario.md — create, the trainee sees the waiting notice
// before the start, start, the card arrives by itself, the fire service walked to «Работы
// завершены», the rest «Не принята», close, the lesson completes by itself, report 18/18 «Сдал»,
// release, the trainee sees the report in «История», the admin's journal shows the actions.
import { button, check, heading, link, scenario, text, url, visible } from './dsl';
import {
  CARD_ARRIVAL_WAIT,
  FIRE_CHAIN,
  FIRE_SERVICE,
  TICKET_SCENARIO_TITLE,
  closeIncidentSteps,
  createLessonSteps,
  createUserSteps,
  ddsCardExpectations,
  ddsCardPhoneAvailableStep,
  legStatusStep,
  lessonCardRow,
  loginSteps,
  navLink,
  otherLegsDeclinedSteps,
  planCard,
  startLessonStep,
  traineeOpensCardStep,
} from './steps';

export const S02 = scenario(
  'S02',
  'Полный цикл занятия: от создания до отчёта у стажёра и журнала администратора',
  ['admin', 'instructor', 'newTrainee'],
  [
    ...loginSteps('admin', 'ADMIN', 'администратора (admin)'),
    ...createUserSteps('newTrainee', 'Стажёр', 'стажёр'),
    ...loginSteps('instructor', 'INSTRUCTOR', 'преподавателя (instructor)'),
    ...createLessonSteps({ instructor: 'instructor', trainee: 'newTrainee', label: 'S02' }),
    ...loginSteps('newTrainee', 'TRAINEE', 'нового стажёра (из «Тестовых данных»)'),
    {
      actor: 'newTrainee',
      do: 'Посмотреть на список «Мои занятия» (ничего не нажимать).',
      expect: [
        check(`одна карточка: «${TICKET_SCENARIO_TITLE} (v1)», «Одна роль · Состояние: Готово к началу», «Занятие: e2e S02 <суффикс>», кнопка «Открыть»`, async (page, ctx, { expect, timeout }) => {
          const rows = page.getByRole('main').getByRole('listitem');
          await expect(rows).toHaveCount(1, { timeout });
          await expect(rows.first()).toContainText(`${TICKET_SCENARIO_TITLE} (v1)`, { timeout });
          await expect(rows.first()).toContainText('Одна роль · Состояние: Готово к началу', { timeout });
          await expect(rows.first()).toContainText(`Занятие: ${ctx.vars.lessonTitle}`, { timeout });
          await expect(rows.first().getByRole('link', { name: 'Открыть', exact: true })).toBeVisible({ timeout });
        }),
      ],
    },
    {
      ...traineeOpensCardStep('newTrainee'),
      expect: [
        ...traineeOpensCardStep('newTrainee').expect,
        heading('Заявка ДДС ещё не поступила'),
        text(
          'пояснение «Занятие ещё не запущено преподавателем. Когда преподаватель нажмёт «Начать занятие», заявка появится здесь сама.»',
          'Занятие ещё не запущено преподавателем. Когда преподаватель нажмёт «Начать занятие», заявка появится здесь сама.',
        ),
        text('мелким шрифтом «Страница обновляется автоматически, перезагружать её не нужно…»', /Страница обновляется автоматически, перезагружать её не нужно/),
      ],
    },
    startLessonStep('instructor'),
    {
      actor: 'newTrainee',
      do: 'Смотреть на вкладку стажёра, ничего не нажимая и не перезагружая страницу.',
      wait: CARD_ARRIVAL_WAIT,
      action: async (page, { vars }) => {
        await page.getByText('Заявка от оператора 112').waitFor();
        vars.cardArrived = '1';
      },
      expect: ddsCardExpectations(),
    },
    ddsCardPhoneAvailableStep('newTrainee'),
    legStatusStep('newTrainee', FIRE_SERVICE, 'Принята', { order: 'Н-101', comment: 'Наряд выслан' }, [
      check('в истории над вкладкой: «Получена службой» и «Принята · Номер наряда: Н-101»', async (page, _ctx, { expect, timeout }) => {
        await expect(page.getByText('Получена службой')).toBeVisible({ timeout });
        await expect(page.getByText(/Принята\s*·\s*Номер наряда: Н-101/)).toBeVisible({ timeout });
      }),
      text('«Этап: Принято к исполнению»', /Этап:\s*Принято к исполнению/),
      button('Закрыть происшествие', 'вверху справа появилась кнопка «Закрыть происшествие»'),
    ]),
    ...FIRE_CHAIN.map((status) => legStatusStep('newTrainee', FIRE_SERVICE, status, { comment: `Доклад: ${status.toLowerCase()}` })),
    {
      actor: 'instructor',
      do: 'На странице занятия в блоке «Карточки занятия» нажать ссылку «Обзор карточки».',
      action: async (page) => {
        await page.getByRole('link', { name: 'Обзор карточки', exact: true }).click();
      },
      expect: [
        url('адрес /instructor/sessions/…', /\/instructor\/sessions\/[0-9a-f-]{36}$/),
        heading('Обзор занятия (инструктор)'),
        visible('ссылка «Открыть занятие «e2e S02 <суффикс>»»', (page, ctx) =>
          page.getByRole('link', { name: `Открыть занятие «${ctx.vars.lessonTitle}»` }),
        ),
        text('«Состояние: Идёт»', /Состояние:\s*Идёт/),
        text('«Активная роль: ДДС»', /Активная роль:\s*ДДС/),
        text('«Принято к исполнению»', 'Принято к исполнению'),
        text('«Истина сценария — видна только инструктору»', 'Истина сценария — видна только инструктору'),
        text('блок «Назначения ДДС»', 'Назначения ДДС'),
        text('блок «Готовность моделей»', 'Готовность моделей'),
        link('← Назад', 'слева вверху «← Назад»'),
      ],
    },
    ...otherLegsDeclinedSteps('newTrainee'),
    ...closeIncidentSteps('newTrainee'),
    {
      actor: 'instructor',
      do: 'Подождать 3 секунды после того, как у стажёра появилось «Занятие завершено.» (занятие завершается само за 1–2 с; страница занятия сама не обновляется), затем в «Обзоре занятия» нажать «← Назад» (слева вверху). Отдельно завершать занятие не нужно.',
      action: async (page) => {
        await page.waitForTimeout(3000);
        await page.getByRole('link', { name: '← Назад', exact: true }).click();
      },
      expect: [
        url('вернулись на страницу занятия', /\/instructor\/lessons\/[0-9a-f-]{36}$/),
        check('«План занятия» в состоянии «Завершено» (занятие завершилось само)', async (page, _ctx, { expect, timeout }) => {
          await expect(planCard(page)).toContainText('Завершено', { timeout });
        }),
        button('Выдать отчёт стажёрам'),
        check('у карточки состояние «Завершено» и статус «Отказ»', async (page, _ctx, { expect, timeout }) => {
          await expect(lessonCardRow(page)).toContainText('Завершено', { timeout });
          await expect(lessonCardRow(page)).toContainText('Отказ', { timeout });
        }),
        heading('Отчёты по карточкам', 'блок «Отчёты по карточкам»'),
        button('Скачать CSV'),
        check('строка отчёта: «18 / 18», «Итог» — «Сдал»', async (page, _ctx, { expect, timeout }) => {
          const row = page.getByRole('row').filter({ hasText: '18 / 18' }).first();
          await expect(row).toBeVisible({ timeout });
          await expect(row).toContainText('Сдал', { timeout });
        }),
        text('«Итог с учётом весов: 18 / 18»', /Итог с учётом весов:\s*18 \/ 18/),
      ],
    },
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
        check('«План занятия» по-прежнему «Завершено»', async (page, _ctx, { expect, timeout }) => {
          await expect(planCard(page)).toContainText('Завершено', { timeout });
        }),
      ],
    },
    {
      actor: 'instructor',
      do: 'В «Карточки занятия» нажать «Обзор карточки», затем в обзоре нажать «Перейти к отчёту».',
      action: async (page) => {
        await page.getByRole('link', { name: 'Обзор карточки', exact: true }).click();
        await page.getByRole('link', { name: 'Перейти к отчёту', exact: true }).click();
      },
      expect: [
        url('адрес /report/…', /\/report\/[0-9a-f-]{36}$/),
        heading('Отчёт по занятию'),
        text('«Итог: Сдал»', /Итог:\s*Сдал/),
        text('«Итоговый балл»', 'Итоговый балл'),
        text('баллы «18 / 18»', /18 \/ 18/),
        text('раздел «Баллы по категориям»', 'Баллы по категориям'),
        text('раздел «Критические ошибки»', 'Критические ошибки'),
        text('раздел «Хронология событий»', 'Хронология событий'),
        text('раздел «Решения ДДС»', 'Решения ДДС'),
        text('в «Решения ДДС» номер наряда «Н-101»', /Н-101/),
        text('раздел «Доказательства по правилам»', 'Доказательства по правилам'),
        text('раздел «Комментарии преподавателя»', 'Комментарии преподавателя'),
      ],
    },
    {
      actor: 'newTrainee',
      do: 'В шапке, в меню, нажать «Мои занятия», затем снова «История».',
      action: async (page) => {
        await navLink(page, 'Мои занятия').click();
        await navLink(page, 'История').click();
      },
      expect: [
        heading('Мои результаты'),
        heading('Итоги', 'блок «Итоги»'),
        heading('Завершённые сессии', 'таблица «Завершённые сессии»'),
        check('строка сценария: оценка «100%», нарушено правил «0», ссылка «Отчёт»', async (page, _ctx, { expect, timeout }) => {
          const row = page.getByRole('row').filter({ hasText: TICKET_SCENARIO_TITLE }).first();
          await expect(row).toContainText('100%', { timeout });
          await expect(row.getByRole('cell', { name: '0', exact: true })).toBeVisible({ timeout });
          await expect(row.getByRole('link', { name: 'Отчёт', exact: true })).toBeVisible({ timeout });
        }),
      ],
    },
    {
      actor: 'newTrainee',
      do: 'В строке сценария нажать «Отчёт».',
      action: async (page) => {
        await page.getByRole('row').filter({ hasText: TICKET_SCENARIO_TITLE }).first().getByRole('link', { name: 'Отчёт', exact: true }).click();
      },
      expect: [
        url('адрес /report/…', /\/report\/[0-9a-f-]{36}$/),
        heading('Отчёт по занятию'),
        text('«Итог: Сдал»', /Итог:\s*Сдал/),
        text('«18 / 18»', /18 \/ 18/),
        link('← Назад', 'слева вверху «← Назад»'),
      ],
    },
    {
      actor: 'newTrainee',
      do: 'Нажать «← Назад» (слева вверху).',
      action: async (page) => {
        await page.getByRole('link', { name: '← Назад', exact: true }).click();
      },
      expect: [url('вернулись в «Историю» (/history)', /\/history$/), heading('Мои результаты')],
    },
    {
      actor: 'admin',
      do: 'Во вкладке администратора в шапке нажать «Администрирование», затем вкладку «Журнал».',
      action: async (page) => {
        await navLink(page, 'Администрирование').click();
        await page.getByRole('tab', { name: 'Журнал', exact: true }).click();
      },
      expect: [
        ...['Время', 'Пользователь', 'Действие', 'Запрос', 'Статус', 'Результат', 'IP-адрес'].map((column) =>
          visible(`колонка «${column}»`, (page) => page.getByRole('cell', { name: column, exact: true })),
        ),
        text('строка «POST /api/v1/instructor/lessons/{lesson_id}/report/release» (выдача отчёта)', 'POST /api/v1/instructor/lessons/{lesson_id}/report/release'),
        text('строка «POST /api/v1/sessions/{session_id}/dds/close» (закрытие происшествия)', 'POST /api/v1/sessions/{session_id}/dds/close'),
        text('строки «POST /api/v1/sessions/{session_id}/dds/legs/{assignment_id}/status» (статусы служб)', 'POST /api/v1/sessions/{session_id}/dds/legs/{assignment_id}/status'),
        button('Следующая страница', 'внизу кнопка «Следующая страница»'),
      ],
    },
    {
      actor: 'admin',
      do: 'Во вкладке «Журнал» в фильтре «Действие» (слева вверху над таблицей) выбрать «Успешный вход».',
      action: async (page) => {
        await page.getByLabel('Действие', { exact: true }).selectOption({ label: 'Успешный вход' });
      },
      expect: [
        check('в таблице только строки «Успешный вход» с запросом «POST /api/v1/auth/login», статус 200, результат «ОК»', async (page, _ctx, { expect, timeout }) => {
          const rows = page.getByRole('row').filter({ hasText: 'POST /api/v1/auth/login' });
          await expect(rows.first()).toBeVisible({ timeout });
          await expect(rows.first()).toContainText('Успешный вход', { timeout });
          await expect(rows.first()).toContainText('200', { timeout });
          await expect(rows.first()).toContainText('ОК', { timeout });
          await expect(page.getByRole('row').filter({ hasText: 'HTTP-запрос' })).toHaveCount(0, { timeout });
        }),
      ],
    },
  ],
  {
    purpose:
      'Главный путь продукта целиком (как docs/demo-scenario.md): преподаватель создаёт и запускает занятие, стажёр в роли ДДС получает карточку сам, ведёт службы по памятке и закрывает происшествие, занятие завершается само, отчёт 18/18 «Сдал» выдаётся стажёру и виден ему в «Истории», администратор видит действия в журнале.',
    preconditions: ['Вход ещё не выполнен ни в одной вкладке (или нажмите «Выйти» во всех).'],
    testData: [
      'Новый стажёр: логин `e2e-<суффикс>-newtrainee`, «Отображаемое имя» `Стажёр <суффикс>`, роль «Стажёр», пароль `Pw-<суффикс>-Aa1!`.',
      'Занятие: «Название занятия» `e2e S02 <суффикс>`.',
      'Номер наряда пожарной службы `Н-101`.',
    ],
    cleanup: [
      'Если занятие `e2e S02 <суффикс>` не «Завершено»: преподаватель → «Занятия» → строка занятия «Открыть» → «Прервать занятие», «Причина» «уборка» → «Прервать».',
      'Администратор → «Администрирование» → «Пользователи» → строка `e2e-<суффикс>-newtrainee` → «Заблокировать».',
    ],
  },
);
