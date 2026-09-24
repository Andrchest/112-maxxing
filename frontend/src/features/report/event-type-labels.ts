// Exhaustive `EventType -> ru.ts key` table for the timeline's event-type filter (D6: "the
// event-type filter lists 30 raw enums"). `Record<EventType, …>` fails `tsc` the moment
// `schema.d.ts` grows a member this file has not been updated for — same treatment
// `timeline-labels.ts`'s `ACTOR_TYPE_LABEL_KEY` already gives `ActorType` in this file's own
// directory.
import { ru } from '@/shared/i18n/ru';
import { t } from '@/shared/i18n';
import type { EventType } from '@/shared/api';

export const EVENT_TYPE_LABEL_KEY: Record<EventType, keyof typeof ru> = {
  SESSION_CREATED: 'eventTypeSessionCreated',
  SESSION_STARTED: 'eventTypeSessionStarted',
  ROLE_STAGE_STARTED: 'eventTypeRoleStageStarted',
  CALL_RINGING: 'eventTypeCallRinging',
  CALL_ANSWERED: 'eventTypeCallAnswered',
  USER_SPEECH_STARTED: 'eventTypeUserSpeechStarted',
  USER_SPEECH_ENDED: 'eventTypeUserSpeechEnded',
  ASR_PARTIAL: 'eventTypeAsrPartial',
  ASR_FINAL: 'eventTypeAsrFinal',
  CALLER_RESPONSE_PLANNED: 'eventTypeCallerResponsePlanned',
  CALLER_RESPONSE_GENERATED: 'eventTypeCallerResponseGenerated',
  CALLER_TTS_STARTED: 'eventTypeCallerTtsStarted',
  CALLER_TTS_ENDED: 'eventTypeCallerTtsEnded',
  CALLER_UTTERANCE_INTERRUPTED: 'eventTypeCallerUtteranceInterrupted',
  CARD_FIELD_CHANGED: 'eventTypeCardFieldChanged',
  SERVICE_SELECTED: 'eventTypeServiceSelected',
  HANDOFF_CREATED: 'eventTypeHandoffCreated',
  HANDOFF_RECEIVED: 'eventTypeHandoffReceived',
  DDS_ACKNOWLEDGED: 'eventTypeDdsAcknowledged',
  RESOURCE_SELECTED: 'eventTypeResourceSelected',
  RESOURCE_DISPATCHED: 'eventTypeResourceDispatched',
  RESOURCE_STATUS_CHANGED: 'eventTypeResourceStatusChanged',
  WORLD_EVENT_TRIGGERED: 'eventTypeWorldEventTriggered',
  ROLE_STAGE_COMPLETED: 'eventTypeRoleStageCompleted',
  SCORING_RULE_EVALUATED: 'eventTypeScoringRuleEvaluated',
  SESSION_COMPLETED: 'eventTypeSessionCompleted',
  MODEL_FALLBACK_USED: 'eventTypeModelFallbackUsed',
  MODEL_ERROR: 'eventTypeModelError',
  SESSION_ABORTED: 'eventTypeSessionAborted',
  STAGE_STATE_CHANGED: 'eventTypeStageStateChanged',
  ROLE_TRANSITION_STARTED: 'eventTypeRoleTransitionStarted',
  ROLE_TRANSITION_COMPLETED: 'eventTypeRoleTransitionCompleted',
  SERVICE_DESELECTED: 'eventTypeServiceDeselected',
  RESOURCE_DESELECTED: 'eventTypeResourceDeselected',
  DDS_STATUS_UPDATE_SENT: 'eventTypeDdsStatusUpdateSent',
  DDS_INCIDENT_CLOSED: 'eventTypeDdsIncidentClosed',
  NOTIFICATION_CREATED: 'eventTypeNotificationCreated',
  NOTIFICATION_ACKNOWLEDGED: 'eventTypeNotificationAcknowledged',
  RADIO_MESSAGE_CREATED: 'eventTypeRadioMessageCreated',
  WORLD_TRUTH_MUTATED: 'eventTypeWorldTruthMutated',
  CALLER_BELIEF_MUTATED: 'eventTypeCallerBeliefMutated',
  CALLER_EMOTION_CHANGED: 'eventTypeCallerEmotionChanged',
  CALL_ENDED: 'eventTypeCallEnded',
  DIALOGUE_INTERPRETED: 'eventTypeDialogueInterpreted',
  FACT_GATE_EVALUATED: 'eventTypeFactGateEvaluated',
  FACTS_DELIVERED: 'eventTypeFactsDelivered',
  TRANSPORT_DISCONNECTED: 'eventTypeTransportDisconnected',
  TRANSPORT_RECONNECTED: 'eventTypeTransportReconnected',
  INFERENCE_HEALTH_CHANGED: 'eventTypeInferenceHealthChanged',
  DDS_CARD_STATUS_CHANGED: 'eventTypeDdsCardStatusChanged',
  RECIPIENTS_RESOLVED: 'eventTypeRecipientsResolved', // I3 E2b′
  DDS_CARD_OPENED: 'eventTypeDdsCardOpened', // I3 E5a
  DDS_SERVICE_STATUS_SET: 'eventTypeDdsServiceStatusSet', // I3 E5a
  DDS_CARD_ISSUE_FLAGGED: 'eventTypeDdsCardIssueFlagged', // I3 E5b
  DDS_CALL_STARTED: 'eventTypeDdsCallStarted', // I3 E6b
  DDS_CALL_ANSWERED: 'eventTypeDdsCallAnswered', // I3 E6b
  DDS_CALL_ENDED: 'eventTypeDdsCallEnded', // I3 E6b
  DDS_CALL_STATUS_PROPOSED: 'eventTypeDdsCallStatusProposed', // I3 E6c
  DDS_CALL_ASSERTION: 'eventTypeDdsCallAssertion', // I3 E6c
};

export function eventTypeLabelRu(value: EventType): string {
  return t(EVENT_TYPE_LABEL_KEY[value]);
}
