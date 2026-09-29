// I7 E56: the trainee's tour («Стажёр»). Plain data — edit the Russian texts here freely; `target`
// ids are the `data-tour` attributes on the pages. The console steps (ДДС, оператор 112) have no
// `route`: the tour cannot open a live lesson by itself, so they highlight the real blocks when the
// trainee is on a console, and otherwise explain in words (`explainIfMissing`).
import type { TourStep } from '../types';

const DDS_CONSOLE = /^\/dds\/[0-9a-f-]{36}$/;
const OPERATOR_CONSOLE = /^\/operator\/[0-9a-f-]{36}$/;

export const TRAINEE_TOUR: readonly TourStep[] = [
  {
    id: 'trainee-menu',
    route: '/sessions',
    target: 'app-nav',
    title: 'Меню разделов',
    text: 'Вверху всегда есть меню: «Мои занятия» — ваши карточки, «История» — результаты и отчёты, «Справочная база» — памятки и инструкции.',
  },
  {
    id: 'trainee-sessions',
    route: '/sessions',
    target: 'sessions-item',
    explainIfMissing: true,
    title: 'Мои занятия',
    text: 'Каждая строка — карточка занятия: сценарий, «Состояние» («Идёт», «Завершено») и название занятия. Пока список пуст — дождитесь, когда преподаватель начнёт занятие.',
  },
  {
    id: 'trainee-incident-list',
    route: '/sessions',
    target: 'incident-list-link',
    title: 'Список происшествий',
    text: '«Список происшествий» — все карточки, пришедшие в ДДС, с таймерами «Приём» и «Заполнение». Открыть карточку можно и отсюда.',
  },
  {
    id: 'trainee-open-lesson',
    route: '/sessions',
    target: 'sessions-open',
    explainIfMissing: true,
    clickOnNext: true,
    title: 'Открыть занятие',
    text: 'У карточки в состоянии «Идёт» нажмите «Открыть» справа — откроется ваше рабочее место. Если такая карточка есть, «Далее» откроет её сейчас.',
  },
  {
    id: 'trainee-dds-header',
    page: DDS_CONSOLE,
    target: 'dds-header',
    explainIfMissing: true,
    title: 'Рабочее место ДДС',
    text: 'Карточка приходит сама через несколько секунд после начала занятия. В этой строке — АОН заявителя и номер «Происшествие …»; слева вверху — этап, например «Этап: Получено».',
  },
  {
    id: 'trainee-dds-card',
    page: DDS_CONSOLE,
    target: 'dds-card',
    explainIfMissing: true,
    title: 'Карточка',
    text: '«Заявка от оператора 112»: заявитель, адрес, происшествие и службы, которые нужно оповестить. Прочитайте её до решения.',
  },
  {
    id: 'trainee-dds-accept',
    page: DDS_CONSOLE,
    target: 'dds-services',
    explainIfMissing: true,
    title: 'Решение по службе',
    text: 'Внизу, в полосе «СЛУЖБЫ:», нажмите вкладку службы, затем карандаш «Изменить статус». Выберите «Принята» и впишите «Номер наряда», который назвала служба.',
  },
  {
    id: 'trainee-dds-statuses',
    page: DDS_CONSOLE,
    target: 'dds-services',
    explainIfMissing: true,
    title: 'Статусы по памятке',
    text: 'Дальше ведите статусы по памятке: «Начало реагирования» → «Прибытие» → «Проведение работ» → «Работы завершены». Лишним службам ставьте «Не принята».',
  },
  {
    id: 'trainee-dds-comment',
    page: DDS_CONSOLE,
    target: 'dds-services',
    explainIfMissing: true,
    title: 'Комментарий',
    text: 'В поле «Комментарий» коротко запишите, что сообщила служба. Для «Не принята» и «Отказ от выполнения работ» комментарий обязателен.',
  },
  {
    id: 'trainee-dds-close',
    page: DDS_CONSOLE,
    target: 'dds-actions',
    explainIfMissing: true,
    title: 'Закрытие происшествия',
    text: 'Когда все службы отработали, нажмите «Закрыть происшествие», выберите «Причина закрытия» и нажмите «Подтвердить». «Уведомления и радиообмен» — журнал событий.',
  },
  {
    id: 'trainee-operator',
    page: OPERATOR_CONSOLE,
    target: 'operator-card',
    explainIfMissing: true,
    title: 'Оператор 112',
    text: 'Если в занятии у вас роль «Оператор 112», вы принимаете звонок и заполняете «Карточку происшествия»; внизу, в «Службы:», — кого оповестить.',
  },
  {
    id: 'trainee-report',
    route: '/history',
    target: 'history-sessions',
    explainIfMissing: true,
    title: 'Отчёт',
    text: 'Когда преподаватель выдаст отчёт, в «Завершённые сессии» у карточки появится оценка, а ссылка «Отчёт» откроет разбор ваших действий.',
  },
  {
    id: 'trainee-history',
    route: '/history',
    target: 'history-summary',
    explainIfMissing: true,
    title: 'История',
    text: '«Итоги» — сколько занятий пройдено, средний процент и какие правила нарушались чаще всего.',
  },
  {
    id: 'trainee-materials',
    route: '/materials',
    target: 'materials-list',
    explainIfMissing: true,
    title: 'Справочная база',
    text: 'Памятки и инструкции от преподавателя: «Открыть» — посмотреть в браузере, «Скачать» — сохранить файл.',
  },
  {
    id: 'trainee-help',
    route: '/materials',
    target: 'tour-button',
    title: 'Если что-то забыли',
    text: 'Кнопка «Обучение» запускает эту подсказку снова. В меню пользователя (значок справа) можно включить «Подсказки для новичков».',
  },
];
