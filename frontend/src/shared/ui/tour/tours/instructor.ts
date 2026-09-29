// I7 E56: the instructor's tour («Преподаватель»). Plain data — edit the Russian texts here freely;
// `target` ids are the `data-tour` attributes on the pages. The lesson page steps have no `route`
// (a lesson id is needed): «Далее» on «Открыть» follows the first lesson in the list, and with no
// lessons yet those steps explain in words instead (`explainIfMissing`).
import type { TourStep } from '../types';

const LESSON_DETAIL = /^\/instructor\/lessons\/[0-9a-f-]{36}$/;

export const INSTRUCTOR_TOUR: readonly TourStep[] = [
  {
    id: 'instructor-menu',
    route: '/instructor/lessons',
    target: 'app-nav',
    title: 'Меню разделов',
    text: '«Занятия» — создать и провести занятие, «Сессии» — все карточки, «Статистика» — успехи стажёров, «Сценарии» и «Материалы» — содержание обучения.',
  },
  {
    id: 'instructor-lesson-basics',
    route: '/instructor/lessons',
    target: 'lesson-form-basics',
    title: 'Новое занятие',
    text: 'В форме «Новое занятие (несколько карточек)» задайте «Название занятия» и «Режим занятия». «Группа» сразу подставит её стажёров в участники.',
  },
  {
    id: 'instructor-lesson-scenario',
    route: '/instructor/lessons',
    target: 'lesson-form-scenario',
    title: 'Сценарии карточек',
    text: 'Для каждой карточки выберите «Сценарий» и «Версия сценария». Ещё карточки добавляет кнопка «Добавить карточку».',
  },
  {
    id: 'instructor-lesson-participants',
    route: '/instructor/lessons',
    target: 'lesson-form-participants',
    explainIfMissing: true,
    title: 'Участники',
    text: 'После выбора сценария появится блок «Участники занятия»: выберите стажёров и их рабочие места. Стажёр увидит карточку в «Мои занятия» после запуска.',
  },
  {
    id: 'instructor-lesson-variants',
    route: '/instructor/lessons',
    target: 'lesson-form-variants',
    explainIfMissing: true,
    title: 'Варианты карточки',
    text: '«Варианты карточки» меняют рабочее место стажёра: режим ДДС, телефон, вид карточки. Они появляются после выбора версии сценария.',
  },
  {
    id: 'instructor-lesson-timers',
    route: '/instructor/lessons',
    target: 'lesson-form-timers',
    title: 'Таймеры',
    text: '«Временные рамки карточки» — сколько секунд даётся на решение «Принята» / «Не принята» и на заполнение. Пустое поле — значение из сценария.',
  },
  {
    id: 'instructor-lesson-criteria',
    route: '/instructor/lessons',
    target: 'lesson-form-criteria',
    title: 'Критерии «сдал / не сдал»',
    text: 'Отметьте условия зачёта: минимальный процент баллов, число нарушенных правил, без критических ошибок. Затем нажмите «Создать занятие» внизу формы.',
  },
  {
    id: 'instructor-lesson-open',
    route: '/instructor/lessons',
    target: 'lessons-open',
    explainIfMissing: true,
    clickOnNext: true,
    title: 'Открыть занятие',
    text: 'Созданные занятия — в списке «Занятия (несколько карточек)». «Открыть» ведёт на страницу занятия; «Далее» откроет первое из них.',
  },
  {
    id: 'instructor-lesson-start',
    page: LESSON_DETAIL,
    target: 'lesson-plan',
    explainIfMissing: true,
    title: 'Запуск',
    text: 'В блоке «План занятия» нажмите «Начать занятие» — карточки уйдут стажёрам. «Прервать занятие» останавливает его досрочно.',
  },
  {
    id: 'instructor-lesson-overview',
    page: LESSON_DETAIL,
    target: 'lesson-cards',
    explainIfMissing: true,
    title: 'Обзор занятия',
    text: 'В «Карточки занятия» видно состояние каждой карточки. «Обзор карточки» показывает, что делает стажёр прямо сейчас.',
  },
  {
    id: 'instructor-lesson-report',
    page: LESSON_DETAIL,
    target: 'lesson-report',
    explainIfMissing: true,
    title: 'Отчёты',
    text: 'После завершения здесь появятся «Отчёты по карточкам». Стажёры увидят оценки только после кнопки «Выдать отчёт стажёрам» в «План занятия».',
  },
  {
    id: 'instructor-statistics',
    route: '/instructor/statistics',
    target: 'statistics-filters',
    title: 'Статистика',
    text: 'Выберите «Группа» и период — таблица покажет средний процент, отклонения по времени и нарушенные правила каждого стажёра. Ниже — «Рейтинг».',
  },
  {
    id: 'instructor-scenarios',
    route: '/instructor/scenarios',
    target: 'scenario-upload',
    title: 'Сценарии',
    text: 'Выберите «Файл сценария (YAML или JSON)», нажмите «Проверить», затем «Импортировать». Ниже — список сценариев; ненужный убирает кнопка «Архивировать».',
  },
  {
    id: 'instructor-materials',
    route: '/instructor/materials',
    target: 'materials-upload',
    title: 'Материалы',
    text: 'Укажите «Название» и «Файл», нажмите «Загрузить» — материал появится у стажёров в «Справочная база».',
  },
  {
    id: 'instructor-groups',
    route: '/instructor/lessons',
    target: 'trainee-groups',
    title: 'Группы',
    text: '«Группы учащихся» — постоянные составы, например смена А. Группу можно выбрать в новом занятии и в статистике.',
  },
  {
    id: 'instructor-help',
    route: '/instructor/lessons',
    target: 'tour-button',
    title: 'Если что-то забыли',
    text: 'Кнопка «Обучение» запускает эту подсказку снова. В меню пользователя (значок справа) можно включить «Подсказки для новичков».',
  },
];
