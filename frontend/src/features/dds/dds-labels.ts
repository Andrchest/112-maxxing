// Exhaustive `generated union -> ru.ts key` tables for the DDS console (D12 design decision #5;
// this task's CHECK: "enum labels ... exhaustive over the generated unions so a new member fails
// typecheck"). Every `Record<Enum, keyof typeof ru>` below fails `tsc` the moment `schema.d.ts`
// grows a new member and this file is not updated — the same pattern `client.ts`'s
// `PROBLEM_MESSAGE_KEYS` and `services-panel.tsx`'s `SERVICE_TYPE_LABEL_KEY` already use.
import { ru } from '@/shared/i18n/ru';
import { t } from '@/shared/i18n';
import type {
  ServiceType,
  DDSStageState,
  ResourceType,
  ResourceStatus,
  ResourceCapability,
  NotificationSeverity,
  StatusUpdateKind,
  ClosureReason,
} from '@/shared/api';

export const SERVICE_TYPE_LABEL_KEY: Record<ServiceType, keyof typeof ru> = {
  FIRE_RESCUE: 'serviceTypeFireRescue',
  POLICE: 'serviceTypePolice',
  AMBULANCE: 'serviceTypeAmbulance',
  GAS_SERVICE: 'serviceTypeGasService',
  UTILITY_EMERGENCY: 'serviceTypeUtilityEmergency',
  EDDS: 'serviceTypeEdds',
};
export function serviceTypeLabelRu(value: ServiceType): string {
  return t(SERVICE_TYPE_LABEL_KEY[value]);
}

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
