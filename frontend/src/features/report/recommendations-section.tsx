// «Рекомендации по улучшению навыков» — G10 (ТЗ ¶267/¶237, final criteria ¶460/¶469, I7 E54).
// Renders `SessionReport.recommendations` exactly as the server ordered it (worst category
// first, at most 5) — this component sorts and filters nothing itself, same discipline as
// `PassVerdictSection` and `RuleEvidenceSection`. An empty array (every visible rule passed, or
// this viewer has none) renders «Замечаний нет», never a fabricated line.
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { scoringCategoryLabelRu } from './scoring-labels';
import type { RecommendationView } from '@/shared/api';

export function RecommendationsSection({
  recommendations,
}: {
  recommendations: readonly RecommendationView[];
}) {
  return (
    <Card data-slot="recommendations">
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportRecommendationsTitle')}</h2>
      </CardHeader>
      <CardContent>
        {recommendations.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-slot="recommendations-empty">
            {t('reportRecommendationsEmpty')}
          </p>
        ) : (
          <ul className="flex flex-col gap-2" data-slot="recommendations-list">
            {recommendations.map((item) => (
              <li key={item.category} className="rounded-md border border-border p-2 text-sm">
                <span className="font-medium">{scoringCategoryLabelRu(item.category)}.</span>{' '}
                <span>{item.text_ru}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
