// Single keyed Russian string bundle (D12). No component holds a hard-coded
// UI string; everything is looked up here through the `t()` helper in
// `./index.ts`. Add new keys here only.
export const ru = {
  appName: 'Тренажёр 112',
  loginTitle: 'Вход в систему',
  operatorTitle: 'Оператор 112',
  ddsTitle: 'ЕДДС',
  instructorTitle: 'Инструктор',
  reportTitle: 'Отчёт по занятию',
  notFoundTitle: 'Страница не найдена',
  notFoundHint: 'Проверьте адрес или вернитесь на страницу входа.',
  roleBadgeNone: 'Роль не назначена',
  connectionPlaceholder: 'Нет соединения',
  placeholderNotice: 'Экран ещё не реализован.',
} as const;
