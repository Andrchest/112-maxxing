// Exhaustive enum label tables for the DDS decisions section (§29 item 11) — the report's own
// copy of `features/dds/dds-labels.ts`'s `StatusUpdateKind`/`ClosureReason` maps (same
// duplication-over-cross-feature-import treatment as `snapshot-card-fields.ts`).
import { ru } from '@/shared/i18n/ru';
import { t } from '@/shared/i18n';
import type { ClosureReason, StatusUpdateKind, ServiceResponseStatus, CardIssueKind } from '@/shared/api';

type LegResponder = 'TRAINEE' | 'SCRIPTED';

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

// -- I3 E5c: the memo's per-leg vocabulary in the report (70 §70.4.1, D16) — the same table
// `features/dds/dds-labels.ts` keeps for the live console, duplicated per this file's own header
// comment's "same duplication-over-cross-feature-import treatment".
const SERVICE_RESPONSE_STATUS_LABEL_KEY: Record<ServiceResponseStatus, keyof typeof ru> = {
  ADDED: 'serviceResponseStatusAdded',
  RECEIVED: 'serviceResponseStatusReceived',
  ACCEPTED: 'serviceResponseStatusAccepted',
  NOT_ACCEPTED: 'serviceResponseStatusNotAccepted',
  RESPONSE_STARTED: 'serviceResponseStatusResponseStarted',
  ARRIVED: 'serviceResponseStatusArrived',
  WORKING: 'serviceResponseStatusWorking',
  COMPLETED: 'serviceResponseStatusCompleted',
  REFUSED: 'serviceResponseStatusRefused',
};
export function serviceResponseStatusLabelRu(value: ServiceResponseStatus): string {
  return t(SERVICE_RESPONSE_STATUS_LABEL_KEY[value]);
}

const CARD_ISSUE_KIND_LABEL_KEY: Record<CardIssueKind, keyof typeof ru> = {
  MISSING: 'cardIssueKindMissing',
  WRONG: 'cardIssueKindWrong',
  CONTRADICTION: 'cardIssueKindContradiction',
  OTHER: 'cardIssueKindOther',
};
export function cardIssueKindLabelRu(value: CardIssueKind): string {
  return t(CARD_ISSUE_KIND_LABEL_KEY[value]);
}

const LEG_RESPONDER_LABEL_KEY: Record<LegResponder, keyof typeof ru> = {
  TRAINEE: 'reportDdsResponderTrainee',
  SCRIPTED: 'reportDdsResponderScripted',
};
export function legResponderLabelRu(value: LegResponder): string {
  return t(LEG_RESPONDER_LABEL_KEY[value]);
}
