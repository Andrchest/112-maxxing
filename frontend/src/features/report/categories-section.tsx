// §29 item 2: score by category. Renders `score_report.by_category` verbatim.
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import type { ScoreCategoryTotalView } from '@/shared/api';
import { scoringCategoryLabelRu } from './scoring-labels';

interface CategoriesSectionProps {
  byCategory: readonly ScoreCategoryTotalView[];
}

export function CategoriesSection({ byCategory }: CategoriesSectionProps) {
  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportCategoriesTitle')}</h2>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-1.5">
          {byCategory.map((category) => (
            <li key={category.category} className="flex items-center justify-between gap-2 text-sm">
              <span>{scoringCategoryLabelRu(category.category)}</span>
              <span className="font-mono tabular-nums text-muted-foreground">
                {category.points_awarded} / {category.max_points}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
