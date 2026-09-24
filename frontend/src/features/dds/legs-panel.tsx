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

  // I3 E7a carry-over fix (a, manager review of E5c/E7a): pinned to the true viewport bottom —
  // rendered as the last, non-scrolling flex child of `AppShell`'s `fillHeight` `main`
  // (`console-page.tsx`), with the card summary above it in its own `overflow-y-auto` region, so
  // the bar sits at the bottom even when the content above it is shorter than the viewport (a
  // `position: sticky` bar alone cannot do that — it only pins once there is something to
  // scroll). Colour (D20, ui-check reference palette): the DDS card's own bottom bar,
  // `--reference-dds-bar` (`src/index.css`), a fixed accent used only here (this bar only ever
  // renders inside a `referenceTheme` route); each tab (`service-leg-block.tsx`) keeps the shared
  // `bg-card` chip colour against it.
  return (
    <div
      className="flex shrink-0 flex-col gap-1 bg-[var(--reference-dds-bar)] px-2 pt-1 pb-2 text-[var(--reference-dds-bar-foreground)]"
      data-slot="dds-services-tab-bar"
    >
      <span className="text-xs font-semibold tracking-wide uppercase opacity-90">{t('ddsLegsPanelTitle')}:</span>
      {legs.length === 0 ? (
        <p className="text-sm opacity-90">{t('ddsLegsEmpty')}</p>
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
