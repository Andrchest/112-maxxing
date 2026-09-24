// I3 E4b (70 §70.3.6, ui-check D-2/D-8): the query + search box shared by the ДДС «Список
// происшествий» and the 112 «реестр» — both are `GET /api/v1/incidents` filtered by `role_type`
// (`listMyIncidents`), nothing more. `IncidentListTable` owns rendering; this owns fetching.
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { t } from '@/shared/i18n';
import { listMyIncidents, problemMessageRu, queryKeys, type ProblemCode, type RoleType } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { IncidentListTable } from './incident-list-table';

interface IncidentListScreenProps {
  roleType: RoleType;
  consoleBasePath: '/operator' | '/dds';
  searchInputId: string;
}

export function IncidentListScreen({ roleType, consoleBasePath, searchInputId }: IncidentListScreenProps) {
  const [q, setQ] = useState('');
  const trimmedQ = q.trim();
  const incidentsQuery = useQuery({
    queryKey: queryKeys.incidents.list(roleType, trimmedQ),
    queryFn: () => listMyIncidents({ roleType, q: trimmedQ === '' ? undefined : trimmedQ }),
  });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex max-w-sm flex-col gap-1.5">
        <Label htmlFor={searchInputId}>{t('incidentListSearchLabel')}</Label>
        <Input
          id={searchInputId}
          value={q}
          placeholder={t('incidentListSearchPlaceholder')}
          onChange={(event) => setQ(event.target.value)}
        />
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
