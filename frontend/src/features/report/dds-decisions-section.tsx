// §29 item 11: DDS decisions — what was acknowledged, dispatched, reported and closed. Renders
// `dds_decisions` verbatim; empty when the viewer may not see it (R3) or the session never reached
// DDS.
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { formatCallDurationMs } from '@/entities/call';
import type { DdsDecisionView } from '@/shared/api';
import { serviceTypeLabelRu } from './snapshot-card-fields';
import { closureReasonLabelRu, statusUpdateKindLabelRu } from './dds-decision-labels';

interface DdsDecisionsSectionProps {
  decisions: readonly DdsDecisionView[];
}

export function DdsDecisionsSection({ decisions }: DdsDecisionsSectionProps) {
  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportDdsDecisionsTitle')}</h2>
      </CardHeader>
      <CardContent>
        {decisions.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('reportDdsDecisionsEmpty')}</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {decisions.map((decision) => (
              <li key={decision.assignment_id} className="flex flex-col gap-1.5 rounded-md border border-border p-2">
                <div className="flex items-center justify-between gap-2">
                  <Badge variant="outline">{serviceTypeLabelRu(decision.service_type)}</Badge>
                  {decision.acknowledged_at_offset_ms !== null ? (
                    <span className="text-xs text-muted-foreground">
                      {t('reportDdsAcknowledgedLabel')}: {formatCallDurationMs(decision.acknowledged_at_offset_ms)}
                    </span>
                  ) : null}
                </div>
                {decision.dispatch_events.length > 0 ? (
                  <div className="flex flex-col gap-1">
                    <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{t('reportDdsDispatchLabel')}</span>
                    <ul className="flex flex-col gap-1">
                      {decision.dispatch_events.map((dispatchEvent, index) => (
                        <li key={index} className="flex items-center gap-2 text-xs">
                          <span>{formatCallDurationMs(dispatchEvent.at_offset_ms)}</span>
                          <span>{dispatchEvent.callsigns.join(', ')}</span>
                          {dispatchEvent.is_additional ? <Badge variant="secondary">{t('reportDdsAdditionalDispatchBadge')}</Badge> : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {decision.status_updates.length > 0 ? (
                  <div className="flex flex-col gap-1">
                    <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{t('reportDdsStatusUpdatesLabel')}</span>
                    <ul className="flex flex-col gap-1">
                      {decision.status_updates.map((update, index) => (
                        <li key={index} className="text-xs">
                          <span className="text-muted-foreground">{statusUpdateKindLabelRu(update.update_kind)}:</span> {update.text_ru}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {decision.closure_reason ? (
                  <p className="text-xs">
                    {t('reportDdsClosureLabel')}: {closureReasonLabelRu(decision.closure_reason)}
                    {decision.closed_at_offset_ms !== null ? ` (${formatCallDurationMs(decision.closed_at_offset_ms)})` : null}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
