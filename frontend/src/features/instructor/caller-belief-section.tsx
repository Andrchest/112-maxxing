// Caller belief panel (D3, D10, R4): "exposes ... CallerBelief ONLY here and in the report diff."
// `CallerBeliefView.label_ru` (E20-E R11, additive) labels the `facts`/`knowledge`/`certainty`
// keys, same join and same raw-`fact_id` fallback as `world-truth-section.tsx`.
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import type { CallerBeliefView } from '@/shared/api';
import { emotionLabelRu, knowledgeStateLabelRu } from './instructor-labels';
import { formatWorldTruthValueRu } from './format-fact-value';

interface CallerBeliefSectionProps {
  callerBelief: CallerBeliefView;
}

export function CallerBeliefSection({ callerBelief }: CallerBeliefSectionProps) {
  const factIds = Object.keys(callerBelief.facts).sort();
  const revealed = new Set(callerBelief.revealed_fact_ids);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <h2 className="font-heading text-base leading-snug font-medium">{t('instructorCallerBeliefTitle')}</h2>
        <div className="flex items-center gap-2">
          <Badge variant="outline">
            {t('instructorCallerBeliefEmotionLabel')}: {emotionLabelRu(callerBelief.emotion)}
          </Badge>
          <Badge variant="outline">
            {t('instructorCallerBeliefStressLabel')}: {callerBelief.stress_level}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {factIds.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('instructorCallerBeliefEmpty')}</p>
        ) : (
          <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {factIds.map((factId) => {
              const knowledge = callerBelief.knowledge[factId];
              return (
                <div key={factId} className="flex flex-col gap-0.5 rounded-md border border-border p-2">
                  <dt className="text-xs text-muted-foreground">{callerBelief.label_ru?.[factId] ?? factId}</dt>
                  <dd className="text-sm">{formatWorldTruthValueRu(factId, callerBelief.facts[factId])}</dd>
                  <dd className="text-xs text-muted-foreground">
                    {knowledge ? knowledgeStateLabelRu(knowledge) : null}
                    {' · '}
                    {t('instructorCallerBeliefCertaintyLabel')}: {callerBelief.certainty[factId] ?? t('factValueEmpty')}
                    {revealed.has(factId) ? (
                      <>
                        {' · '}
                        <span data-slot="revealed-marker">{t('instructorCallerBeliefRevealedLabel')}</span>
                      </>
                    ) : null}
                  </dd>
                </div>
              );
            })}
          </dl>
        )}
      </CardContent>
    </Card>
  );
}
