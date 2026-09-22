// Ground-truth panel (D3, D11, R4): "exposes WorldTruth ... ONLY here and in the report diff."
// Clearly titled so nobody mistakes it for anything a trainee could see. `WorldTruthView.label_ru`
// (E20-E R11, additive) is a `fact_id -> FactDefinition.label_ru` join; a fact the join could not
// resolve still renders, under its raw `fact_id` (never a blank row). Sorted by `fact_id` for a
// stable order, verdict-free (this is the scenario's truth, not a diff).
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import type { WorldTruthView } from '@/shared/api';
import { formatRawFactValueRu } from './format-fact-value';

interface WorldTruthSectionProps {
  worldTruth: WorldTruthView;
}

export function WorldTruthSection({ worldTruth }: WorldTruthSectionProps) {
  const factIds = Object.keys(worldTruth.facts).sort();

  return (
    <Card className="border-amber-600/40">
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium text-amber-600">{t('instructorWorldTruthTitle')}</h2>
        <p className="text-xs text-muted-foreground">
          {t('instructorWorldTruthRevisionLabel')}: {worldTruth.revision}
        </p>
      </CardHeader>
      <CardContent>
        {factIds.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('instructorWorldTruthEmpty')}</p>
        ) : (
          <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {factIds.map((factId) => (
              <div key={factId} className="flex flex-col gap-0.5">
                <dt className="text-xs text-muted-foreground">{worldTruth.label_ru?.[factId] ?? factId}</dt>
                <dd className="text-sm">{formatRawFactValueRu(worldTruth.facts[factId])}</dd>
              </div>
            ))}
          </dl>
        )}
      </CardContent>
    </Card>
  );
}
