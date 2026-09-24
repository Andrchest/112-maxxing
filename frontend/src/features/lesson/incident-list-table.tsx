// I3 E4b (70 §70.3.6, D15; ui-check D-2/D-8): the row shape shared by the ДДС «Список
// происшествий» (`features/dds/incident-list-page.tsx`) and the 112 «реестр»
// (`features/operator/register-page.tsx`). Renders `IncidentListItem` verbatim: the status badge
// is `card_status` read straight off the row (never derived here), the red flag is the pure
// `isRedFlagCardStatus` predicate over that same field, and the countdowns are pure arithmetic
// over the row's own deadline/session offsets (`incident-countdown.ts`) — nothing here compares a
// wall-clock date to decide whether a card is late.
import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { Badge } from '@/shared/ui/badge';
import { t } from '@/shared/i18n';
import type { IncidentListItem } from '@/shared/api';
import { cardStatusLabelRu, isRedFlagCardStatus } from './lesson-labels';
import { formatDurationMs, remainingDeadlineMs } from './incident-countdown';

interface IncidentListTableProps {
  items: readonly IncidentListItem[];
  /** Where «Открыть» sends the trainee — the session's existing workstation page/socket
   * (`/operator/:sessionId` or `/dds/:sessionId`), never a new one built for this list. */
  consoleBasePath: '/operator' | '/dds';
}

/** Same shape `features/instructor/session-stages-section.tsx`'s `useCountdownSeconds` uses
 * (DESIGN: no client clock authority beyond ticking a countdown between server refreshes): the
 * remaining time is recomputed with the pure {@link remainingDeadlineMs} whenever the row's own
 * offsets change (the "adjust state during render" pattern — no `Date.now()`/ref read during
 * render, react-hooks/purity), then ticks down locally once a second via a plain updater — the
 * effect never reads an outside clock either. */
function useRemainingMs(deadlineOffsetMs: number | null, sessionOffsetMs: number): number | null {
  const [remaining, setRemaining] = useState(() => remainingDeadlineMs(deadlineOffsetMs, sessionOffsetMs, 0));
  const [trackedDeadline, setTrackedDeadline] = useState(deadlineOffsetMs);
  const [trackedOffset, setTrackedOffset] = useState(sessionOffsetMs);
  if (trackedDeadline !== deadlineOffsetMs || trackedOffset !== sessionOffsetMs) {
    setTrackedDeadline(deadlineOffsetMs);
    setTrackedOffset(sessionOffsetMs);
    setRemaining(remainingDeadlineMs(deadlineOffsetMs, sessionOffsetMs, 0));
  }

  useEffect(() => {
    if (deadlineOffsetMs === null) return;
    const interval = window.setInterval(() => {
      setRemaining((previous) => (previous === null ? previous : previous - 1000));
    }, 1000);
    return () => window.clearInterval(interval);
  }, [deadlineOffsetMs, sessionOffsetMs]);

  return remaining;
}

function CountdownCell({ deadlineOffsetMs, sessionOffsetMs }: { deadlineOffsetMs: number | null; sessionOffsetMs: number }) {
  const remaining = useRemainingMs(deadlineOffsetMs, sessionOffsetMs);
  if (remaining === null) {
    return <span className="text-muted-foreground">{t('incidentCountdownDash')}</span>;
  }
  if (remaining < 0) {
    return <span className="text-destructive">{t('incidentCountdownOverdue')}</span>;
  }
  return <span className="font-mono">{formatDurationMs(remaining)}</span>;
}

export function IncidentListTable({ items, consoleBasePath }: IncidentListTableProps) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{t('incidentListEmpty')}</p>;
  }

  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-border text-left text-xs text-muted-foreground">
          <th className="p-2 font-medium">{t('incidentListColumnNumber')}</th>
          <th className="p-2 font-medium">{t('incidentListColumnType')}</th>
          <th className="p-2 font-medium">{t('incidentListColumnAddress')}</th>
          <th className="p-2 font-medium">{t('incidentListColumnTime')}</th>
          <th className="p-2 font-medium">{t('incidentListColumnStatus')}</th>
          <th className="p-2 font-medium">{t('incidentListColumnAcceptCountdown')}</th>
          <th className="p-2 font-medium">{t('incidentListColumnFillCountdown')}</th>
          <th className="p-2 font-medium">{t('incidentListColumnNotCompletedCountdown')}</th>
          <th className="p-2" />
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.session_id} className="border-b border-border/60" data-slot="incident-row">
            <td className="p-2 font-mono whitespace-nowrap">
              {t('incidentListNumberPrefix')} {item.display_number}
            </td>
            <td className="p-2">{item.classifier_code ?? '—'}</td>
            <td className="p-2">{item.address_line_ru ?? '—'}</td>
            <td className="p-2 whitespace-nowrap">
              {item.arrived_at_utc ? new Date(item.arrived_at_utc).toLocaleString('ru-RU') : '—'}
            </td>
            <td className="p-2">
              <Badge variant={isRedFlagCardStatus(item.card_status) ? 'destructive' : 'outline'} data-slot="card-status-badge">
                {cardStatusLabelRu(item.card_status)}
              </Badge>
            </td>
            <td className="p-2">
              <CountdownCell deadlineOffsetMs={item.accept_deadline_offset_ms} sessionOffsetMs={item.session_offset_ms} />
            </td>
            <td className="p-2">
              <CountdownCell deadlineOffsetMs={item.fill_deadline_offset_ms} sessionOffsetMs={item.session_offset_ms} />
            </td>
            <td className="p-2">
              <CountdownCell
                deadlineOffsetMs={item.not_completed_deadline_offset_ms}
                sessionOffsetMs={item.session_offset_ms}
              />
            </td>
            <td className="p-2 text-right whitespace-nowrap">
              <Link className="text-primary underline-offset-2 hover:underline" to={`${consoleBasePath}/${item.session_id}`}>
                {t('incidentListOpenButton')}
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
