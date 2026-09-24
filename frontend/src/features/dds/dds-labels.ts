// Exhaustive `generated union -> ru.ts key` tables for the DDS console (D12 design decision #5;
// this task's CHECK: "enum labels ... exhaustive over the generated unions so a new member fails
// typecheck"). Every `Record<Enum, keyof typeof ru>` below fails `tsc` the moment `schema.d.ts`
// grows a new member and this file is not updated — the same pattern `client.ts`'s
// `PROBLEM_MESSAGE_KEYS` uses. A service is not an enum any more (I3 E2a, D18): its name is a
// service-catalog lookup (`entities/service-catalog`), re-exported here for the console.
import { ru } from '@/shared/i18n/ru';
import { t } from '@/shared/i18n';
import type {
  DDSStageState,
  ResourceType,
  ResourceStatus,
  ResourceCapability,
  NotificationSeverity,
  StatusUpdateKind,
  ClosureReason,
  ServiceResponseStatus,
  CardIssueKind,
} from '@/shared/api';

export { serviceLabelRu as serviceTypeLabelRu } from '@/entities/service-catalog';

export const DDS_STAGE_STATE_LABEL_KEY: Record<DDSStageState, keyof typeof ru> = {
  RECEIVED: 'ddsStageReceived',
  ACKNOWLEDGED: 'ddsStageAcknowledged',
  RESOURCE_SELECTION: 'ddsStageResourceSelection',
  DISPATCHED: 'ddsStageDispatched',
  EN_ROUTE: 'ddsStageEnRoute',
  ARRIVED: 'ddsStageArrived',
  WORKING: 'ddsStageWorking',
  RESOLVED: 'ddsStageResolved',
  CLOSED: 'ddsStageClosed',
};
export function ddsStageStateLabelRu(value: DDSStageState): string {
  return t(DDS_STAGE_STATE_LABEL_KEY[value]);
}

export const RESOURCE_TYPE_LABEL_KEY: Record<ResourceType, keyof typeof ru> = {
  FIRE_ENGINE: 'resourceTypeFireEngine',
  LADDER_TRUCK: 'resourceTypeLadderTruck',
  RESCUE_UNIT: 'resourceTypeRescueUnit',
  AMBULANCE_UNIT: 'resourceTypeAmbulanceUnit',
  RESUSCITATION_UNIT: 'resourceTypeResuscitationUnit',
  POLICE_PATROL: 'resourceTypePolicePatrol',
  GAS_EMERGENCY_UNIT: 'resourceTypeGasEmergencyUnit',
  UTILITY_CREW: 'resourceTypeUtilityCrew',
  FIRE_CHIEF_CAR: 'resourceTypeFireChiefCar',
};
export function resourceTypeLabelRu(value: ResourceType): string {
  return t(RESOURCE_TYPE_LABEL_KEY[value]);
}

export const RESOURCE_STATUS_LABEL_KEY: Record<ResourceStatus, keyof typeof ru> = {
  AVAILABLE: 'resourceStatusAvailable',
  SELECTED: 'resourceStatusSelected',
  DISPATCHED: 'resourceStatusDispatched',
  EN_ROUTE: 'resourceStatusEnRoute',
  ON_SCENE: 'resourceStatusOnScene',
  WORKING: 'resourceStatusWorking',
  RETURNING: 'resourceStatusReturning',
  OUT_OF_SERVICE: 'resourceStatusOutOfService',
  UNAVAILABLE: 'resourceStatusUnavailable',
};
export function resourceStatusLabelRu(value: ResourceStatus): string {
  return t(RESOURCE_STATUS_LABEL_KEY[value]);
}

export const RESOURCE_CAPABILITY_LABEL_KEY: Record<ResourceCapability, keyof typeof ru> = {
  FIRE_SUPPRESSION: 'resourceCapabilityFireSuppression',
  HIGH_RISE_ACCESS: 'resourceCapabilityHighRiseAccess',
  LADDER_RESCUE: 'resourceCapabilityLadderRescue',
  TECHNICAL_RESCUE: 'resourceCapabilityTechnicalRescue',
  SMOKE_DIVING: 'resourceCapabilitySmokeDiving',
  BASIC_LIFE_SUPPORT: 'resourceCapabilityBasicLifeSupport',
  ADVANCED_LIFE_SUPPORT: 'resourceCapabilityAdvancedLifeSupport',
  BURN_CARE: 'resourceCapabilityBurnCare',
  PUBLIC_ORDER: 'resourceCapabilityPublicOrder',
  TRAFFIC_CONTROL: 'resourceCapabilityTrafficControl',
  AREA_CORDON: 'resourceCapabilityAreaCordon',
  GAS_SHUTOFF: 'resourceCapabilityGasShutoff',
  GAS_LEAK_DETECTION: 'resourceCapabilityGasLeakDetection',
  POWER_SHUTOFF: 'resourceCapabilityPowerShutoff',
  WATER_SUPPLY: 'resourceCapabilityWaterSupply',
  COMMAND_AND_CONTROL: 'resourceCapabilityCommandAndControl',
};
export function resourceCapabilityLabelRu(value: ResourceCapability): string {
  return t(RESOURCE_CAPABILITY_LABEL_KEY[value]);
}

export const NOTIFICATION_SEVERITY_LABEL_KEY: Record<NotificationSeverity, keyof typeof ru> = {
  INFO: 'notificationSeverityInfo',
  WARNING: 'notificationSeverityWarning',
  CRITICAL: 'notificationSeverityCritical',
};
export function notificationSeverityLabelRu(value: NotificationSeverity): string {
  return t(NOTIFICATION_SEVERITY_LABEL_KEY[value]);
}

export const STATUS_UPDATE_KIND_LABEL_KEY: Record<StatusUpdateKind, keyof typeof ru> = {
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

export const CLOSURE_REASON_LABEL_KEY: Record<ClosureReason, keyof typeof ru> = {
  RESOLVED: 'closureReasonResolved',
  FALSE_CALL: 'closureReasonFalseCall',
  TRANSFERRED: 'closureReasonTransferred',
  CANCELLED_BY_CALLER: 'closureReasonCancelledByCaller',
};
export function closureReasonLabelRu(value: ClosureReason): string {
  return t(CLOSURE_REASON_LABEL_KEY[value]);
}

// -- I3 E5c: the memo's per-leg vocabulary (70 §70.4.1, D16) — memo p21-22, verbatim ------------
export const SERVICE_RESPONSE_STATUS_LABEL_KEY: Record<ServiceResponseStatus, keyof typeof ru> = {
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

// -- I3 E5b/E5c: card-check issue kinds (70 §70.7, C1) -------------------------------------------
export const CARD_ISSUE_KIND_LABEL_KEY: Record<CardIssueKind, keyof typeof ru> = {
  MISSING: 'cardIssueKindMissing',
  WRONG: 'cardIssueKindWrong',
  CONTRADICTION: 'cardIssueKindContradiction',
  OTHER: 'cardIssueKindOther',
};
export function cardIssueKindLabelRu(value: CardIssueKind): string {
  return t(CARD_ISSUE_KIND_LABEL_KEY[value]);
}

// -- I3 E5c: leg-status trigger helpers (moved from the deleted `dds-legs-api.ts` on the
// manager's ruling — `shared/api/client.ts` now owns every REST wrapper, this file keeps the
// domain helpers that are not one) -------------------------------------------------------------

/** `SetServiceStatusRequest.status` is a target `ServiceResponseStatus`; the leg's own
 * `available_actions` carry the *trigger* name (`action_id`/`trigger`, `views.py::leg_actions`
 * — `action_id = trigger`, e.g. `"accept"`), because the same trigger name can leave from more
 * than one source status. This is `SERVICE_RESPONSE_TRANSITIONS`' trigger -> target column
 * (`backend/app/domain/dds/response.py` §70.4.2), copied verbatim — every trigger the leg
 * dropdown can ever offer a caller maps to exactly one target regardless of source. */
export const TRIGGER_TARGET_STATUS: Readonly<Record<string, ServiceResponseStatus>> = {
  receive: 'RECEIVED',
  accept: 'ACCEPTED',
  decline: 'NOT_ACCEPTED',
  start_response: 'RESPONSE_STARTED',
  arrive: 'ARRIVED',
  start_work: 'WORKING',
  complete: 'COMPLETED',
  refuse: 'REFUSED',
  complete_without_brigade: 'COMPLETED',
};

/** The comment is mandatory for «Не принята» / «Отказ от выполнения работ» (§70.4.1, 422
 * `COMMENT_REQUIRED`) — the client-side mirror of the guard, keyed on the trigger the leg block
 * dropdown offers (same two triggers the backend's `guard_comment_present_and_policy_allows_
 * refusal` gates: `decline`, `refuse`). */
export function triggerRequiresComment(trigger: string): boolean {
  return trigger === 'decline' || trigger === 'refuse';
}
