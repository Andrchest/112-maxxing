// I7 E53 (G13): the «Категория событий» multi-select — one toggle chip per category present in
// the scenario list, plus «Все категории» to clear the selection (see `scenario-categories.ts`).
import { Button } from '@/shared/ui/button';
import { t } from '@/shared/i18n';
import type { CategoryOption } from './scenario-categories';
import { toggleCategory } from './scenario-categories';

interface CategoryChipsProps {
  options: readonly CategoryOption[];
  selected: readonly number[];
  onChange: (selected: number[]) => void;
}

export function CategoryChips({ options, selected, onChange }: CategoryChipsProps) {
  if (options.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-sm font-medium">{t('scenarioCategoryFilterLabel')}</span>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('scenarioCategoryFilterLabel')}>
        <Button
          type="button"
          size="sm"
          variant={selected.length === 0 ? 'default' : 'outline'}
          aria-pressed={selected.length === 0}
          onClick={() => onChange([])}
        >
          {t('scenarioCategoryAll')}
        </Button>
        {options.map((option) => {
          const isSelected = selected.includes(option.key);
          return (
            <Button
              key={option.key}
              type="button"
              size="sm"
              variant={isSelected ? 'default' : 'outline'}
              aria-pressed={isSelected}
              onClick={() => onChange(toggleCategory(selected, option.key))}
            >
              {option.label}
            </Button>
          );
        })}
      </div>
    </div>
  );
}
