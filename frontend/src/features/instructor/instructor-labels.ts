// Exhaustive `generated union -> ru.ts key` tables for the instructor live overview (D12 design
// decision #5, same treatment `features/dds/dds-labels.ts` and `features/report/*-labels.ts` each
// keep locally — every feature that renders a generated enum keeps its own copy, not a shared
// import). `Record<Enum, keyof typeof ru>` fails `tsc` the moment `schema.d.ts` grows a member
// this file has not been updated for.
import { ru } from '@/shared/i18n/ru';
import { t } from '@/shared/i18n';
import type {
  ServiceType,
  ResourceType,
  ResourceStatus,
  DDSStageState,
  ClosureReason,
  GateOutcome,
  GateReason,
  EmotionLabel,
  KnowledgeState,
  CallStateView,
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

export const CLOSURE_REASON_LABEL_KEY: Record<ClosureReason, keyof typeof ru> = {
  RESOLVED: 'closureReasonResolved',
  FALSE_CALL: 'closureReasonFalseCall',
  TRANSFERRED: 'closureReasonTransferred',
  CANCELLED_BY_CALLER: 'closureReasonCancelledByCaller',
};
export function closureReasonLabelRu(value: ClosureReason): string {
  return t(CLOSURE_REASON_LABEL_KEY[value]);
}

export const GATE_OUTCOME_LABEL_KEY: Record<GateOutcome, keyof typeof ru> = {
  ALLOWED: 'gateOutcomeAllowed',
  ALLOWED_SPONTANEOUS: 'gateOutcomeAllowedSpontaneous',
  ALLOWED_REPEAT: 'gateOutcomeAllowedRepeat',
  WITHHELD: 'gateOutcomeWithheld',
  NOT_YET: 'gateOutcomeNotYet',
  UNAVAILABLE: 'gateOutcomeUnavailable',
};
export function gateOutcomeLabelRu(value: GateOutcome): string {
  return t(GATE_OUTCOME_LABEL_KEY[value]);
}

export const GATE_REASON_LABEL_KEY: Record<GateReason, keyof typeof ru> = {
  OK: 'gateReasonOk',
  NEVER_DISCLOSE: 'gateReasonNeverDisclose',
  CALLER_DOES_NOT_KNOW: 'gateReasonCallerDoesNotKnow',
  NOT_YET_AVAILABLE: 'gateReasonNotYetAvailable',
  REQUIRES_EXPLICIT_QUESTION: 'gateReasonRequiresExplicitQuestion',
  UNKNOWN_FACT_ID: 'gateReasonUnknownFactId',
  ALREADY_REVEALED: 'gateReasonAlreadyRevealed',
};
export function gateReasonLabelRu(value: GateReason): string {
  return t(GATE_REASON_LABEL_KEY[value]);
}

export const EMOTION_LABEL_KEY: Record<EmotionLabel, keyof typeof ru> = {
  CALM: 'emotionLabelCalm',
  WORRIED: 'emotionLabelWorried',
  FRIGHTENED: 'emotionLabelFrightened',
  PANICKED: 'emotionLabelPanicked',
  ANGRY: 'emotionLabelAngry',
  CONFUSED: 'emotionLabelConfused',
  APATHETIC: 'emotionLabelApathetic',
};
export function emotionLabelRu(value: EmotionLabel): string {
  return t(EMOTION_LABEL_KEY[value]);
}

export const KNOWLEDGE_STATE_LABEL_KEY: Record<KnowledgeState, keyof typeof ru> = {
  KNOWN: 'knowledgeStateKnown',
  UNKNOWN: 'knowledgeStateUnknown',
  INCORRECT_BELIEF: 'knowledgeStateIncorrectBelief',
  UNCERTAIN: 'knowledgeStateUncertain',
};
export function knowledgeStateLabelRu(value: KnowledgeState): string {
  return t(KNOWLEDGE_STATE_LABEL_KEY[value]);
}

export const CALL_PHASE_LABEL_KEY: Record<CallStateView['phase'], keyof typeof ru> = {
  NO_CALL: 'callPhaseNoCall',
  RINGING: 'callPhaseRinging',
  CONNECTED: 'callPhaseConnected',
  ENDED: 'callPhaseEnded',
};
export function callPhaseLabelRu(value: CallStateView['phase']): string {
  return t(CALL_PHASE_LABEL_KEY[value]);
}
