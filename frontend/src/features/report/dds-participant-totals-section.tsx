// I3 E5c — the report's per-ДДС-participant totals (70 §70.4.5, D16). Renders
// `SessionReport.dds_participant_totals` verbatim; empty when the viewer may not see it (R3) or
// the session never reached DDS — same "empty state, never an error" contract every other §29
// section here follows.
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import type { SessionReport } from '@/shared/api';
import { serviceTypeLabelRu } from './snapshot-card-fields';

interface DdsParticipantTotalsSectionProps {
  totals: SessionReport['dds_participant_totals'];
}

export function DdsParticipantTotalsSection({ totals }: DdsParticipantTotalsSectionProps) {
  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportDdsParticipantTotalsTitle')}</h2>
      </CardHeader>
      <CardContent>
        {totals.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('reportDdsParticipantTotalsEmpty')}</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {totals.map((total) => (
              <li key={total.user_id} className="flex flex-col gap-1.5 rounded-md border border-border p-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{total.display_name_ru}</span>
                  {total.assigned_service_id ? (
                    <Badge variant="outline">
                      {t('reportDdsParticipantTotalsServiceLabel')}: {serviceTypeLabelRu(total.assigned_service_id)}
                    </Badge>
                  ) : null}
                </div>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">{t('reportDdsParticipantTotalsLegsLabel')}</dt>
                    <dd>{total.legs}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">{t('reportDdsParticipantTotalsStatusEntriesLabel')}</dt>
                    <dd>{total.status_entries}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">{t('reportDdsParticipantTotalsAcceptedLabel')}</dt>
                    <dd>{total.accepted}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">{t('reportDdsParticipantTotalsNotAcceptedLabel')}</dt>
                    <dd>{total.not_accepted}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">{t('reportDdsParticipantTotalsRefusedLabel')}</dt>
                    <dd>{total.refused}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">{t('reportDdsParticipantTotalsCompletedLabel')}</dt>
                    <dd>{total.completed}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">{t('reportDdsParticipantTotalsCardIssuesLabel')}</dt>
                    <dd>{total.card_issues}</dd>
                  </div>
                </dl>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
