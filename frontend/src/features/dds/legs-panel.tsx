// I3 E5c (manager review): the memo workstation's bottom «Службы:» tab bar
// (`ref/screenshot-dds/image6.png`) — one tab per notified service, in place of the vertical block
// list. Renders under `dds_mode: MEMO_STATUSES` in place of `ResourceBoard`/`DispatchTray`
// (`console-page.tsx`) — the `RESOURCE_PICKER` UI is unchanged and lives entirely in those two
// components. Only one tab's popup is open at a time (`openLegId`), matching the reference's one-
// popup-at-a-time behaviour.
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { t } from '@/shared/i18n';
import { listDdsLegs, queryKeys, type DdsLegView } from '@/shared/api';
import { ServiceLegBlock } from './service-leg-block';

interface LegsPanelProps {
  sessionId: string;
}

export function LegsPanel({ sessionId }: LegsPanelProps) {
  const queryClient = useQueryClient();
  const queryKey = queryKeys.dds.legs(sessionId);
  const [openLegId, setOpenLegId] = useState<string | null>(null);

  const legsQuery = useQuery({
    queryKey,
    queryFn: () => listDdsLegs(sessionId),
    enabled: sessionId !== '',
  });

  function patchLeg(updated: DdsLegView): void {
    queryClient.setQueryData<DdsLegView[]>(queryKey, (current) =>
      (current ?? []).map((leg) => (leg.assignment_id === updated.assignment_id ? updated : leg)),
    );
  }

  const legs = legsQuery.data ?? [];

  return (
    <div className="flex flex-col gap-1" data-slot="dds-services-tab-bar">
      <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{t('ddsLegsPanelTitle')}:</span>
      {legs.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('ddsLegsEmpty')}</p>
      ) : (
        <div className="flex flex-wrap items-end gap-1" role="tablist" aria-label={t('ddsLegsPanelTitle')}>
          {legs.map((leg) => (
            <ServiceLegBlock
              key={leg.assignment_id}
              sessionId={sessionId}
              leg={leg}
              expanded={openLegId === leg.assignment_id}
              onToggle={() => setOpenLegId((current) => (current === leg.assignment_id ? null : leg.assignment_id))}
              onLegUpdated={patchLeg}
            />
          ))}
        </div>
      )}
    </div>
  );
}
