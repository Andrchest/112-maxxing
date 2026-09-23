// DDS work item legs + resources panel (SPEC §10, §11; R4). `InstructorSessionOverview.assignments`
// is the per-service `dds_assignments` rows verbatim ("N-leg projection"), not the trainee-facing
// single work-item projection `features/dds/work-item-panel.tsx` renders — reuses the same
// `dds_decisions()`-shaped read the report already exposes, per the E17 backend route this task's
// frontend consumes (`backend/app/api/routers/instructor.py`). Read-only: no select/dispatch controls (D12 design
// decision #1 — commands belong to the DDS trainee's own console, never the instructor overview).
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { formatCallDurationMs } from '@/entities/call';
import type { DdsWorkItem, EmergencyResourceView } from '@/shared/api';
import { closureReasonLabelRu, ddsStageStateLabelRu, resourceStatusLabelRu, resourceTypeLabelRu, serviceTypeLabelRu } from './instructor-labels';

interface DdsWorkItemsSectionProps {
  assignments: readonly DdsWorkItem[];
  resources: readonly EmergencyResourceView[];
}

export function DdsWorkItemsSection({ assignments, resources }: DdsWorkItemsSectionProps) {
  const callsignByResourceId = new Map(resources.map((resource) => [resource.resource_id, resource.callsign]));
  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('instructorDdsWorkItemsTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {assignments.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('instructorDdsWorkItemsEmpty')}</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {assignments.map((assignment) => (
              <li key={assignment.assignment_id} className="flex flex-col gap-1.5 rounded-md border border-border p-2">
                <div className="flex items-center justify-between gap-2">
                  <Badge variant="outline">{serviceTypeLabelRu(assignment.service_type)}</Badge>
                  <Badge>{ddsStageStateLabelRu(assignment.state)}</Badge>
                </div>
                <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                  <span>
                    {t('instructorDdsReceivedAtLabel')}: {formatCallDurationMs(assignment.received_at_offset_ms)}
                  </span>
                  {assignment.dispatched_at_offset_ms !== null ? (
                    <span>
                      {t('instructorDdsDispatchedAtLabel')}: {formatCallDurationMs(assignment.dispatched_at_offset_ms)}
                    </span>
                  ) : null}
                  {assignment.closed_at_offset_ms !== null ? (
                    <span>
                      {t('instructorDdsClosedAtLabel')}: {formatCallDurationMs(assignment.closed_at_offset_ms)}
                    </span>
                  ) : null}
                  {assignment.closure_reason ? <span>{closureReasonLabelRu(assignment.closure_reason)}</span> : null}
                </div>
                {assignment.missing_field_paths.length > 0 ? (
                  <p className="text-xs text-amber-600">
                    {t('instructorDdsMissingFieldsLabel')}: {assignment.missing_field_paths.join(', ')}
                  </p>
                ) : null}
                {assignment.dispatched_resource_ids.length > 0 ? (
                  <p className="text-xs">
                    {assignment.dispatched_resource_ids.map((resourceId) => callsignByResourceId.get(resourceId) ?? resourceId).join(', ')}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}

        <div>
          <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{t('instructorDdsResourcesTitle')}</h3>
          {resources.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('instructorDdsResourcesEmpty')}</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {resources.map((resource) => (
                <li key={resource.resource_id} className="flex items-center justify-between gap-2 rounded-md border border-border p-2 text-xs">
                  <span>
                    {resource.callsign} — {resourceTypeLabelRu(resource.resource_type)} ({serviceTypeLabelRu(resource.service_type)})
                  </span>
                  <Badge variant="outline">{resourceStatusLabelRu(resource.current_status)}</Badge>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
