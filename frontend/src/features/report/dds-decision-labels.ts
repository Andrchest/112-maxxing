// Exhaustive enum label tables for the DDS decisions section (§29 item 11) — the report's own
// copy of `features/dds/dds-labels.ts`'s `StatusUpdateKind`/`ClosureReason` maps (same
// duplication-over-cross-feature-import treatment as `snapshot-card-fields.ts`).
import { ru } from '@/shared/i18n/ru';
import { t } from '@/shared/i18n';
import type { ClosureReason, StatusUpdateKind } from '@/shared/api';

const STATUS_UPDATE_KIND_LABEL_KEY: Record<StatusUpdateKind, keyof typeof ru> = {
  ACKNOWLEDGEMENT: 'statusUpdateKindAcknowledgement',
  EN_ROUTE_REPORT: 'statusUpdateKindEnRouteReport',
  ON_SCENE_REPORT: 'statusUpdateKindOnSceneReport',
  SITUATION_UPDATE: 'statusUpdateKindSituationUpdate',
  ADDITIONAL_FORCES_REQUESTED: 'statusUpdateKindAdditionalForcesRequested',
  RESOLUTION_REPORT: 'statusUpdateKindResolutionReport',
};
export function statusUpdateKindLabelRu(value: StatusUpdateKind): string {
  return t(STATUS_UPDATE_KIND_LABEL_KEY[value]);
}

const CLOSURE_REASON_LABEL_KEY: Record<ClosureReason, keyof typeof ru> = {
  RESOLVED: 'closureReasonResolved',
  FALSE_CALL: 'closureReasonFalseCall',
  TRANSFERRED: 'closureReasonTransferred',
  CANCELLED_BY_CALLER: 'closureReasonCancelledByCaller',
};
export function closureReasonLabelRu(value: ClosureReason): string {
  return t(CLOSURE_REASON_LABEL_KEY[value]);
}
