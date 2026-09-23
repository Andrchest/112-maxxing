// The DDS resource board (SPEC §11: "available resources; resource capabilities; resource
// states; dispatch actions; ETA/travel-time metadata"). One `select`/`deselect` REST command per
// click (D12 design decision #1: "one click = one REST command, the view is replaced by the
// server's response, no optimistic state"); `selectable` is the backend's own hint — a button is
// disabled by it, but the backend re-checks the guard regardless (openapi.yaml
// `EmergencyResourceView.selectable`).
import { useState } from 'react';
import { Badge } from '@/shared/ui/badge';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { useResourceStore, type EmergencyResourceView } from '@/entities/resource';
import { useWorkItemStore, hasAvailableAction } from '@/entities/work-item';
import { selectDdsResource, deselectDdsResource, problemMessageRu, type ProblemCode } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { applyDdsStageView } from './apply-dds-stage-view';
import { serviceTypeLabelRu, resourceTypeLabelRu, resourceStatusLabelRu, resourceCapabilityLabelRu } from './dds-labels';

function groupByService(resources: readonly EmergencyResourceView[]): { service: string; items: EmergencyResourceView[] }[] {
  const groups: { service: string; items: EmergencyResourceView[] }[] = [];
  const indexByService = new Map<string, number>();
  for (const resource of resources) {
    const existing = indexByService.get(resource.service_type);
    if (existing === undefined) {
      indexByService.set(resource.service_type, groups.length);
      groups.push({ service: resource.service_type, items: [resource] });
    } else {
      groups[existing]!.items.push(resource);
    }
  }
  return groups;
}

/** `EtaProfile` read verbatim (D7): the sum of `turnout_delay_seconds` + `travel_time_seconds`,
 * in whole minutes — a pure function of the server's own numbers, no client clock involved. */
function estimatedArrivalMinutes(resource: EmergencyResourceView): number {
  return Math.round((resource.eta.turnout_delay_seconds + resource.eta.travel_time_seconds) / 60);
}

interface ResourceRowProps {
  resource: EmergencyResourceView;
  canSelect: boolean;
  canDeselect: boolean;
  pending: boolean;
  onSelect: (resourceId: string) => void;
  onDeselect: (resourceId: string) => void;
}

function ResourceRow({ resource, canSelect, canDeselect, pending, onSelect, onDeselect }: ResourceRowProps) {
  return (
    <li className="flex flex-col gap-1 rounded-lg border border-border p-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col">
          <span className="text-sm font-medium">
            {resource.callsign} — {resourceTypeLabelRu(resource.resource_type)}
          </span>
          <span className="text-xs text-muted-foreground">
            {t('ddsResourceHomeStationLabel')}: {resource.home_station_ru} · {t('ddsResourceCrewSizeLabel')}: {resource.crew_size} ·{' '}
            {t('ddsResourceEtaLabel')}: {estimatedArrivalMinutes(resource)}
          </span>
        </div>
        <Badge variant="outline">{resourceStatusLabelRu(resource.current_status)}</Badge>
      </div>
      <div className="flex flex-wrap gap-1">
        {resource.capabilities.map((capability) => (
          <Badge key={capability} variant="secondary" className="text-[0.65rem]">
            {resourceCapabilityLabelRu(capability)}
          </Badge>
        ))}
      </div>
      <div className="flex items-center gap-2">
        {/* D13: before resource selection is open (`canSelect` false — `select_resource` is not
            currently an available action at all), no «Выбрать»/hint is shown for an AVAILABLE
            unit; once selection is open, a unit the backend still will not let this trainee pick
            renders the disabled button plus the hint. */}
        {resource.current_status === 'AVAILABLE' && canSelect ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!resource.selectable || pending}
            onClick={() => onSelect(resource.resource_id)}
          >
            {t('ddsSelectButton')}
          </Button>
        ) : null}
        {resource.current_status === 'SELECTED' ? (
          <Button type="button" size="sm" variant="outline" disabled={!canDeselect || pending} onClick={() => onDeselect(resource.resource_id)}>
            {t('ddsDeselectButton')}
          </Button>
        ) : null}
        {resource.current_status === 'AVAILABLE' && canSelect && !resource.selectable ? (
          <span className="text-xs text-muted-foreground">{t('ddsNotSelectableHint')}</span>
        ) : null}
      </div>
    </li>
  );
}

interface ResourceBoardProps {
  sessionId: string;
}

export function ResourceBoard({ sessionId }: ResourceBoardProps) {
  const resources = useResourceStore((state) => state.resources);
  const availableActions = useWorkItemStore((state) => state.availableActions);
  const canSelect = hasAvailableAction(availableActions, 'select_resource');
  const canDeselect = hasAvailableAction(availableActions, 'deselect_resource');
  const [pendingResourceId, setPendingResourceId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSelect(resourceId: string): Promise<void> {
    setErrorMessage(null);
    setPendingResourceId(resourceId);
    try {
      applyDdsStageView(await selectDdsResource(sessionId, resourceId));
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPendingResourceId(null);
    }
  }

  async function handleDeselect(resourceId: string): Promise<void> {
    setErrorMessage(null);
    setPendingResourceId(resourceId);
    try {
      applyDdsStageView(await deselectDdsResource(sessionId, resourceId));
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPendingResourceId(null);
    }
  }

  const groups = groupByService(resources);

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('ddsResourceBoardTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {groups.map((group) => (
          <div key={group.service} className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              {serviceTypeLabelRu(group.service as EmergencyResourceView['service_type'])}
            </h3>
            <ul className="flex flex-col gap-2">
              {group.items.map((resource) => (
                <ResourceRow
                  key={resource.resource_id}
                  resource={resource}
                  canSelect={canSelect}
                  canDeselect={canDeselect}
                  pending={pendingResourceId === resource.resource_id}
                  onSelect={(id) => void handleSelect(id)}
                  onDeselect={(id) => void handleDeselect(id)}
                />
              ))}
            </ul>
          </div>
        ))}
        {errorMessage ? (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
