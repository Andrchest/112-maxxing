// Gate turns panel (D10, D3, R4): "what the caller was allowed to say per turn." One
// `GateTurnView` per dialogue turn, each with its `GateDecisionView[]` (one per candidate fact,
// `FACT_GATE_EVALUATED`) — instructor-only per `GateDecisionView`'s own schema doc ("Gate internals
// are instructor-only, D3").
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import type { GateTurnView } from '@/shared/api';
import { gateOutcomeLabelRu, gateReasonLabelRu } from './instructor-labels';

const OUTCOME_BADGE_VARIANT: Record<string, 'default' | 'destructive' | 'outline' | 'secondary'> = {
  ALLOWED: 'default',
  ALLOWED_SPONTANEOUS: 'default',
  ALLOWED_REPEAT: 'secondary',
  WITHHELD: 'destructive',
  NOT_YET: 'outline',
  UNAVAILABLE: 'outline',
};

interface GateTurnsSectionProps {
  gateTurns: readonly GateTurnView[];
}

export function GateTurnsSection({ gateTurns }: GateTurnsSectionProps) {
  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('instructorGateTurnsTitle')}</h2>
      </CardHeader>
      <CardContent>
        {gateTurns.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('instructorGateTurnsEmpty')}</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {gateTurns.map((turn) => (
              <li key={turn.turn_index} className="flex flex-col gap-1.5 rounded-md border border-border p-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">
                    {t('instructorGateTurnLabel')} {turn.turn_index + 1}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {turn.at_offset_ms} {t('reportOffsetMsUnit')}
                  </span>
                </div>
                <ul className="flex flex-col gap-1">
                  {turn.decisions.map((decision) => (
                    <li key={decision.fact_id} className="flex items-center gap-2 text-xs">
                      <Badge variant={OUTCOME_BADGE_VARIANT[decision.outcome] ?? 'outline'}>{gateOutcomeLabelRu(decision.outcome)}</Badge>
                      <span>{decision.fact_id}</span>
                      <span className="text-muted-foreground">{gateReasonLabelRu(decision.reason)}</span>
                    </li>
                  ))}
                </ul>
                <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                  <span>
                    {t('instructorGateTurnAllowedLabel')}: {turn.allowed_fact_ids.join(', ') || t('factValueEmpty')}
                  </span>
                  {turn.spontaneous_attached.length > 0 ? (
                    <span>
                      {t('instructorGateTurnSpontaneousLabel')}: {turn.spontaneous_attached.join(', ')}
                    </span>
                  ) : null}
                  <span>
                    {t('instructorGateTurnWithheldCountLabel')}: {turn.withheld_count}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
