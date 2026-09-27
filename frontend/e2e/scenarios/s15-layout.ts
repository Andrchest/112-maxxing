// S15: layout: at 1920×1080 the main content spans at least 90 % of the width; at 390×844 no page
// scrolls sideways — the key pages of every role.
import { check, heading, scenario, type Expectation, type StepDefinition } from './dsl';
import { loginSteps } from './steps';

const WIDE = { width: 1920, height: 1080 };
const PHONE = { width: 390, height: 844 };

const PAGES: Record<'trainee' | 'instructor' | 'admin', { path: string; title: string }[]> = {
  trainee: [
    { path: '/sessions', title: 'Мои занятия' },
    { path: '/history', title: 'Мои результаты' },
    { path: '/materials', title: 'Справочная база' },
  ],
  instructor: [
    { path: '/instructor/lessons', title: 'Занятия (несколько карточек)' },
    { path: '/instructor', title: 'Инструктор' },
    { path: '/instructor/statistics', title: 'Статистика обучаемых' },
    { path: '/instructor/scenarios', title: 'Сценарии' },
    { path: '/instructor/materials', title: 'Материалы' },
  ],
  admin: [{ path: '/admin', title: 'Администрирование' }],
};

const wideEnough: Expectation = check('основная область (всё под шапкой) занимает не меньше 90 % ширины окна: справа нет пустой полосы', async (page, _ctx, { expect, timeout }) => {
  const main = page.getByRole('main');
  await expect(main).toBeVisible({ timeout });
  const box = await main.boundingBox();
  const width = page.viewportSize()?.width ?? 0;
  if (!box || box.width < width * 0.9) throw new Error(`ширина основной области ${Math.round(box?.width ?? 0)} из ${width}`);
});

const noSideScroll: Expectation = check('страницу нельзя прокрутить вбок: нет горизонтальной полосы прокрутки', async (page) => {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  if (scrollWidth > clientWidth + 1) throw new Error(`ширина содержимого ${scrollWidth} больше окна ${clientWidth}`);
});

function pageSteps(actor: 'trainee' | 'instructor' | 'admin'): StepDefinition[] {
  const steps: StepDefinition[] = [];
  for (const { path, title } of PAGES[actor]) {
    steps.push({
      actor,
      do: `Окно 1920×1080 (обычный монитор, окно развёрнуто). Открыть адрес стенда + «${path}».`,
      action: async (page, ctx) => {
        await ctx.viewport(actor, WIDE);
        await page.goto(path);
      },
      expect: [heading(title), wideEnough, noSideScroll],
    });
    steps.push({
      actor,
      do: `Сузить окно до ширины телефона 390×844 (F12 → режим устройства, 390×844) и снова открыть «${path}».`,
      action: async (page, ctx) => {
        await ctx.viewport(actor, PHONE);
        await page.goto(path);
      },
      expect: [heading(title), noSideScroll],
    });
  }
  return steps;
}

export const S15 = scenario(
  'S15',
  'Раскладка: на 1920×1080 контент во всю ширину, на 390×844 без прокрутки вбок',
  ['trainee', 'instructor', 'admin'],
  [
    ...loginSteps('trainee', 'TRAINEE', 'стажёра (trainee)'),
    ...pageSteps('trainee'),
    ...loginSteps('instructor', 'INSTRUCTOR', 'преподавателя (instructor)'),
    ...pageSteps('instructor'),
    ...loginSteps('admin', 'ADMIN', 'администратора (admin)'),
    ...pageSteps('admin'),
  ],
  {
    purpose:
      'Ключевые страницы каждой роли на широком мониторе используют всю ширину (нет «интерфейса только слева»), а на экране телефона 390 px страница не уезжает вбок (шапка может прокручиваться внутри себя — это допустимо).',
    preconditions: [
      'Вход ещё не выполнен ни в одной вкладке (или нажмите «Выйти» во всех).',
      'Умение менять размер окна: развернуть окно на мониторе 1920×1080; для 390×844 — инструменты разработчика (F12) → режим устройства.',
    ],
    testData: ['Учётные записи `trainee`, `instructor`, `admin`. Ничего не создаётся.'],
    cleanup: [],
  },
);
