// I7 E53 (G13, ТЗ ¶324/¶334 «Выбор Преподавателем категории событий… (возможен множественный
// выбор)»): the category filter over `ScenarioSummary.category` shared by the lesson form and the
// «Сценарии» page. A category is a classifier group (`group_no`, `name_ru`); a scenario without
// one is under the «Без категории» key `NO_CATEGORY`. An empty selection means every category.
import { t } from '@/shared/i18n';
import type { ScenarioSummary } from '@/shared/api';

export const NO_CATEGORY = 0;

export interface CategoryOption {
  key: number;
  label: string;
}

export function categoryKeyOf(scenario: ScenarioSummary): number {
  return scenario.category?.group_no ?? NO_CATEGORY;
}

/** The categories present in `scenarios`, by group number, «Без категории» last. */
export function categoryOptionsOf(scenarios: readonly ScenarioSummary[]): CategoryOption[] {
  const byKey = new Map<number, string>();
  for (const scenario of scenarios) {
    const key = categoryKeyOf(scenario);
    if (!byKey.has(key)) byKey.set(key, scenario.category?.name_ru ?? t('scenarioCategoryNone'));
  }
  return [...byKey.entries()]
    .sort(([a], [b]) => (a === NO_CATEGORY ? 1 : b === NO_CATEGORY ? -1 : a - b))
    .map(([key, label]) => ({ key, label }));
}

export function matchesCategories(scenario: ScenarioSummary, selected: readonly number[]): boolean {
  return selected.length === 0 || selected.includes(categoryKeyOf(scenario));
}

export function toggleCategory(selected: readonly number[], key: number): number[] {
  return selected.includes(key) ? selected.filter((item) => item !== key) : [...selected, key];
}
