// I6 FIX1: «Службы ДДС» on the instructor live overview — each notified service's current memo
// status («Принята», «Работы завершены», …) with its time, from the same broadcast `listDdsLegs`
// read every ДДС participant gets (70 §70.4.3: the instructor reads every leg). Read-only; the
// overview page invalidates this query on every realtime frame, so it follows the trainee live.
import { useQuery } from '@tanstack/react-query';
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { formatCallDurationMs } from '@/entities/call';
import { listDdsLegs, queryKeys } from '@/shared/api';
import { serviceResponseStatusLabelRu } from './instructor-labels';

interface DdsLegStatusesSectionProps {
  sessionId: string;
}

export function DdsLegStatusesSection({ sessionId }: DdsLegStatusesSectionProps) {
  const legsQuery = useQuery({
    queryKey: queryKeys.dds.legs(sessionId),
    queryFn: () => listDdsLegs(sessionId),
    enabled: sessionId !== '',
    retry: false,
  });
  const legs = Array.isArray(legsQuery.data) ? legsQuery.data : [];

  return (
    <Card data-slot="instructor-dds-leg-statuses">
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('instructorDdsLegStatusesTitle')}</h2>
      </CardHeader>
      <CardContent>
        {legs.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('instructorDdsLegStatusesEmpty')}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {legs.map((leg) => (
              <li
                key={leg.assignment_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-2 text-sm"
                data-slot="instructor-dds-leg-status"
              >
                <span className="font-medium">{leg.service_name_ru}</span>
                <span className="flex flex-wrap items-center gap-2">
                  <Badge>{serviceResponseStatusLabelRu(leg.response_status)}</Badge>
                  {leg.response_status_at_offset_ms !== null ? (
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {t('instructorDdsLegStatusAtLabel')} {formatCallDurationMs(leg.response_status_at_offset_ms)}
                    </span>
                  ) : null}
                  {leg.order_number ? (
                    <span className="text-xs text-muted-foreground">
                      {t('instructorDdsLegOrderLabel')} {leg.order_number}
                    </span>
                  ) : null}
                </span>
                {leg.last_comment_ru ? <p className="w-full text-xs text-muted-foreground">{leg.last_comment_ru}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
