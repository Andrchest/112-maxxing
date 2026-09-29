// I3 E4b (70 §70.3.6, ui-check D-2/D-8): the query + search box shared by the ДДС «Список
// происшествий» and the 112 «реестр» — both are `GET /api/v1/incidents` filtered by `role_type`
// (`listMyIncidents`), nothing more. `IncidentListTable` owns rendering; this owns fetching.
//
// I7 E50 (G2/G3, memo p.11/p.40): the list used to load once and never refresh. It now polls
// every `REFRESH_INTERVAL_MS` while the tab is visible (off when hidden, and off entirely while
// «Автообновление» is unchecked) and filters by the existing `card_status` query param through a
// «Статус» select. There is no lesson- or list-scoped WebSocket to invalidate this query from (the
// only socket, `WS /api/v1/ws/sessions/{session_id}`, is per session, not per lesson/list —
// `backend/app/api/routers/realtime.py`), so polling is this page's whole live mechanism; a
// visible tab regaining focus already makes TanStack Query re-run `refetchInterval` (its own
// `refetchOnWindowFocus`), so the loop resumes on its own once the tab is visible again.
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { t } from '@/shared/i18n';
import {
  listMyIncidents,
  problemMessageRu,
  queryKeys,
  type CardStatus,
  type ProblemCode,
  type RoleType,
} from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { CARD_STATUS_LABEL_KEY, cardStatusLabelRu } from './lesson-labels';
import { IncidentListTable } from './incident-list-table';

const REFRESH_INTERVAL_MS = 3_000;
const AUTO_REFRESH_STORAGE_KEY = 'i112.incidentList.autoRefresh';
const CARD_STATUS_VALUES = Object.keys(CARD_STATUS_LABEL_KEY) as CardStatus[];

/** `localStorage` is a per-viewer convenience only — absent/blocked storage (private mode, quota)
 * still renders the switch, defaulted on, exactly as if nothing were ever saved. */
function readAutoRefreshPreference(): boolean {
  try {
    const stored = window.localStorage.getItem(AUTO_REFRESH_STORAGE_KEY);
    return stored === null ? true : stored === 'true';
  } catch {
    return true;
  }
}

function writeAutoRefreshPreference(value: boolean): void {
  try {
    window.localStorage.setItem(AUTO_REFRESH_STORAGE_KEY, String(value));
  } catch {
    // storage unavailable — the in-memory switch still works for this page's lifetime
  }
}

interface IncidentListScreenProps {
  roleType: RoleType;
  consoleBasePath: '/operator' | '/dds';
  searchInputId: string;
}

export function IncidentListScreen({ roleType, consoleBasePath, searchInputId }: IncidentListScreenProps) {
  const [q, setQ] = useState('');
  const [cardStatus, setCardStatus] = useState<CardStatus | ''>('');
  const [autoRefresh, setAutoRefresh] = useState(readAutoRefreshPreference);
  const trimmedQ = q.trim();
  const effectiveCardStatus = cardStatus === '' ? undefined : cardStatus;
  const incidentsQuery = useQuery({
    queryKey: queryKeys.incidents.list(roleType, trimmedQ, effectiveCardStatus),
    queryFn: () =>
      listMyIncidents({ roleType, q: trimmedQ === '' ? undefined : trimmedQ, cardStatus: effectiveCardStatus }),
    refetchInterval: autoRefresh
      ? () => (document.visibilityState === 'visible' ? REFRESH_INTERVAL_MS : false)
      : false,
  });

  const autoRefreshCheckboxId = `${searchInputId}-auto-refresh`;
  const statusSelectId = `${searchInputId}-status`;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex max-w-sm flex-col gap-1.5">
          <Label htmlFor={searchInputId}>{t('incidentListSearchLabel')}</Label>
          <Input
            id={searchInputId}
            value={q}
            placeholder={t('incidentListSearchPlaceholder')}
            onChange={(event) => setQ(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={statusSelectId}>{t('incidentListStatusFilterLabel')}</Label>
          <select
            id={statusSelectId}
            className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            value={cardStatus}
            onChange={(event) => setCardStatus(event.target.value as CardStatus | '')}
          >
            <option value="">{t('incidentListStatusFilterAll')}</option>
            {CARD_STATUS_VALUES.map((value) => (
              <option key={value} value={value}>
                {cardStatusLabelRu(value)}
              </option>
            ))}
          </select>
        </div>
        <label className="flex items-center gap-2 pb-1.5 text-sm" htmlFor={autoRefreshCheckboxId}>
          <input
            id={autoRefreshCheckboxId}
            type="checkbox"
            checked={autoRefresh}
            onChange={(event) => {
              const checked = event.target.checked;
              setAutoRefresh(checked);
              writeAutoRefreshPreference(checked);
            }}
          />
          {t('incidentListAutoRefreshLabel')}
        </label>
      </div>
      {incidentsQuery.isLoading ? <p className="text-sm text-muted-foreground">{t('incidentListLoading')}</p> : null}
      {incidentsQuery.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {incidentsQuery.error instanceof ProblemError
            ? problemMessageRu(incidentsQuery.error.code as ProblemCode)
            : t('problemUnknown')}
        </p>
      ) : null}
      {incidentsQuery.data ? <IncidentListTable items={incidentsQuery.data.items} consoleBasePath={consoleBasePath} /> : null}
    </div>
  );
}
