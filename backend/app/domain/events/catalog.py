"""`EventSpec`, `EVENT_PAYLOAD_CATALOG`, `validate_payload` (HLD `10-domain-model.md` §10.13, D5).

Per the §10.1 module map this file holds `EventSpec`/`EVENT_PAYLOAD_CATALOG` only; `SessionEvent`/
`DomainEvent` live in `events/session_event.py` (ruling R2 — the module map wins over §10.13's
code-block header, which named `catalog.py` for all four classes).

`EVENT_PAYLOAD_CATALOG` covers every one of the 49 `EventType` members with the actor types,
payload keys and `visible_to` set that `10-domain-model.md` §10.13 lists, cross-checked against
`40-realtime-protocol.md` §40.4 (its "Consistency rule for implementers" says the two are one fact
expressed twice). Per this task's ruling R6, where the two tables disagreed on a row, §40.4 won:
`CALLER_TTS_STARTED` and `CALLER_TTS_ENDED` are visible to `OPERATOR_112` (redacted payload) per
§40.4 rows 12–13, though §10.13's prose column named `INSTRUCTOR` only for both — see the task
report, "R6 disagreements", for the two rows and the reasoning.

`payload_keys` values are the type expressions §10.13 prints (`"uuid"`, `"int"`, `"RoleType"`,
`"uuid | null"`, …); a key's expression containing the substring `"null"` marks it optional per
§10.13's own convention ("nullable/optional" — ruling R2), and `validate_payload` uses exactly
that to decide which keys a payload must contain.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.domain.common.errors import DomainError
from app.domain.enums import ActorType, RoleType
from app.domain.events.types import EventType

_INSTRUCTOR: Literal["INSTRUCTOR"] = "INSTRUCTOR"
_OP = RoleType.OPERATOR_112
_DDS = RoleType.DDS


class EventSpec(BaseModel):
    """One `EVENT_PAYLOAD_CATALOG` entry (§10.13)."""

    model_config = ConfigDict(frozen=True)

    event_type: EventType
    actor_types: frozenset[ActorType]
    payload_keys: Mapping[str, str]
    visible_to: frozenset[RoleType | Literal["INSTRUCTOR"]]


EVENT_PAYLOAD_CATALOG: Mapping[EventType, EventSpec] = {
    # ---------------------------------------------------------------------------------------
    # SPEC §8 events (28)
    # ---------------------------------------------------------------------------------------
    EventType.SESSION_CREATED: EventSpec(
        event_type=EventType.SESSION_CREATED,
        actor_types=frozenset({ActorType.SYSTEM, ActorType.INSTRUCTOR}),
        payload_keys={
            "session_id": "uuid",
            "scenario_id": "uuid",
            "scenario_version_id": "uuid",
            "scenario_slug": "str",
            "scenario_version": "int",
            "session_mode": "SessionMode",
            "session_seed": "str",
            "time_scale": "float",
            "role_chain": "list[RoleType]",
            "created_by_user_id": "uuid",
        },
        visible_to=frozenset({_INSTRUCTOR}),
    ),
    EventType.SESSION_STARTED: EventSpec(
        event_type=EventType.SESSION_STARTED,
        actor_types=frozenset({ActorType.INSTRUCTOR}),
        payload_keys={
            "started_at_utc": "datetime",
            "first_role_stage_id": "uuid",
            "first_role_type": "RoleType",
        },
        visible_to=frozenset({_OP, _DDS, _INSTRUCTOR}),
    ),
    EventType.ROLE_STAGE_STARTED: EventSpec(
        event_type=EventType.ROLE_STAGE_STARTED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "role_stage_id": "uuid",
            "role_type": "RoleType",
            "order_index": "int",
            "initial_state": "str",
            "participant_user_id": "uuid | null",
        },
        visible_to=frozenset({_OP, _DDS, _INSTRUCTOR}),
    ),
    EventType.CALL_RINGING: EventSpec(
        event_type=EventType.CALL_RINGING,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "call_id": "uuid",
            "room_name": "str",
            "caller_display_ru": "str",
            "at_offset_ms": "int",
        },
        visible_to=frozenset({_OP, _INSTRUCTOR}),
    ),
    EventType.CALL_ANSWERED: EventSpec(
        event_type=EventType.CALL_ANSWERED,
        actor_types=frozenset({ActorType.TRAINEE}),
        payload_keys={
            "call_id": "uuid",
            "at_offset_ms": "int",
            "ring_duration_ms": "int",
            "answered_by_user_id": "uuid",
        },
        visible_to=frozenset({_OP, _INSTRUCTOR}),
    ),
    EventType.USER_SPEECH_STARTED: EventSpec(
        event_type=EventType.USER_SPEECH_STARTED,
        actor_types=frozenset({ActorType.TRAINEE}),
        payload_keys={
            "call_id": "uuid",
            "turn_index": "int",
            "at_offset_ms": "int",
            "vad_provider": "str",
        },
        visible_to=frozenset({_OP, _INSTRUCTOR}),
    ),
    EventType.USER_SPEECH_ENDED: EventSpec(
        event_type=EventType.USER_SPEECH_ENDED,
        actor_types=frozenset({ActorType.TRAINEE}),
        payload_keys={
            "call_id": "uuid",
            "turn_index": "int",
            "at_offset_ms": "int",
            "speech_duration_ms": "int",
            "endpoint_silence_ms": "int",
        },
        visible_to=frozenset({_OP, _INSTRUCTOR}),
    ),
    EventType.ASR_PARTIAL: EventSpec(
        event_type=EventType.ASR_PARTIAL,
        actor_types=frozenset({ActorType.MODEL}),
        payload_keys={
            "call_id": "uuid",
            "turn_index": "int",
            "text": "str",
            "start_ms": "int",
            "end_ms": "int",
            "asr_provider": "str",
            "asr_model": "str",
        },
        visible_to=frozenset({_OP, _INSTRUCTOR}),
    ),
    EventType.ASR_FINAL: EventSpec(
        event_type=EventType.ASR_FINAL,
        actor_types=frozenset({ActorType.MODEL}),
        payload_keys={
            "call_id": "uuid",
            "turn_index": "int",
            "transcript_segment_id": "uuid",
            "audio_segment_id": "uuid | null",
            "text": "str",
            "start_ms": "int",
            "end_ms": "int",
            "confidence": "float | null",
            "asr_provider": "str",
            "asr_model": "str",
        },
        visible_to=frozenset({_OP, _INSTRUCTOR}),
    ),
    EventType.CALLER_RESPONSE_PLANNED: EventSpec(
        event_type=EventType.CALLER_RESPONSE_PLANNED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "call_id": "uuid",
            "turn_index": "int",
            "allowed_fact_ids": "list[str]",
            "spontaneous_fact_ids": "list[str]",
            "unavailable_fact_ids": "list[str]",
            "withheld_count": "int",
            "emotion": "EmotionLabel",
            "stress_level": "float",
        },
        visible_to=frozenset({_INSTRUCTOR}),
    ),
    EventType.CALLER_RESPONSE_GENERATED: EventSpec(
        event_type=EventType.CALLER_RESPONSE_GENERATED,
        actor_types=frozenset({ActorType.MODEL}),
        payload_keys={
            "call_id": "uuid",
            "turn_index": "int",
            "utterance_ru": "str",
            "output_token_count": "int",
            "llm_provider": "str",
            "llm_model": "str",
            "validator_verdict": 'Literal["PASS", "REGENERATED", "FALLBACK"]',
            "regeneration_count": "int",
        },
        visible_to=frozenset({_INSTRUCTOR}),
    ),
    EventType.CALLER_TTS_STARTED: EventSpec(
        event_type=EventType.CALLER_TTS_STARTED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "call_id": "uuid",
            "turn_index": "int",
            "text_sent_to_tts": "str",
            "tts_provider": "str",
            "tts_model": "str",
            "voice_id": "str",
            "at_offset_ms": "int",
        },
        # §40.4 row 12 wins over §10.13's prose column (ruling R6): redacted to
        # {call_id, turn_index, at_offset_ms} for OPERATOR_112, applied by the redaction layer,
        # not here.
        visible_to=frozenset({_OP, _INSTRUCTOR}),
    ),
    EventType.CALLER_TTS_ENDED: EventSpec(
        event_type=EventType.CALLER_TTS_ENDED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "call_id": "uuid",
            "turn_index": "int",
            "at_offset_ms": "int",
            "total_audio_ms": "int",
            "completed": "bool",
            "audio_segment_id": "uuid | null",
        },
        # §40.4 row 13 wins over §10.13's prose column (ruling R6): redacted to
        # {call_id, turn_index, at_offset_ms, completed} for OPERATOR_112.
        visible_to=frozenset({_OP, _INSTRUCTOR}),
    ),
    EventType.CALLER_UTTERANCE_INTERRUPTED: EventSpec(
        event_type=EventType.CALLER_UTTERANCE_INTERRUPTED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "call_id": "uuid",
            "turn_index": "int",
            "planned_text": "str",
            "delivered_text": "str",
            "delivered_audio_ms": "int",
            "total_audio_ms_generated": "int",
            "cutoff_latency_ms": "int",
        },
        visible_to=frozenset({_OP, _INSTRUCTOR}),
    ),
    EventType.CARD_FIELD_CHANGED: EventSpec(
        event_type=EventType.CARD_FIELD_CHANGED,
        actor_types=frozenset({ActorType.TRAINEE, ActorType.INSTRUCTOR}),
        payload_keys={
            "card_id": "uuid",
            "revision_id": "uuid",
            "revision_no": "int",
            "field_path": "str",
            "previous_value": "FactValue",
            "new_value": "FactValue",
            "value_type": "ValueType",
            "actor_user_id": "uuid",
            "at_offset_ms": "int",
        },
        visible_to=frozenset({_OP, _INSTRUCTOR}),
    ),
    EventType.SERVICE_SELECTED: EventSpec(
        event_type=EventType.SERVICE_SELECTED,
        actor_types=frozenset({ActorType.TRAINEE}),
        payload_keys={
            "card_id": "uuid",
            "revision_id": "uuid",
            "service_type": "ServiceType",
            "selected_services": "list[ServiceType]",
            "at_offset_ms": "int",
        },
        visible_to=frozenset({_OP, _INSTRUCTOR}),
    ),
    EventType.HANDOFF_CREATED: EventSpec(
        event_type=EventType.HANDOFF_CREATED,
        actor_types=frozenset({ActorType.TRAINEE}),
        payload_keys={
            "snapshot_id": "uuid",
            "incident_id": "uuid",
            "card_id": "uuid",
            "card_revision_id": "uuid",
            "recipient_services": "list[ServiceType]",
            "card_values": "object",
            "content_sha256": "str",
            "at_offset_ms": "int",
        },
        visible_to=frozenset({_OP, _INSTRUCTOR}),
    ),
    EventType.HANDOFF_RECEIVED: EventSpec(
        event_type=EventType.HANDOFF_RECEIVED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "snapshot_id": "uuid",
            "assignment_id": "uuid",
            "role_stage_id": "uuid",
            "service_type": "ServiceType",
            "at_offset_ms": "int",
        },
        visible_to=frozenset({_DDS, _INSTRUCTOR}),
    ),
    EventType.DDS_ACKNOWLEDGED: EventSpec(
        event_type=EventType.DDS_ACKNOWLEDGED,
        actor_types=frozenset({ActorType.TRAINEE}),
        payload_keys={
            "assignment_id": "uuid",
            "at_offset_ms": "int",
            "latency_from_handoff_ms": "int",
            "actor_user_id": "uuid",
        },
        visible_to=frozenset({_DDS, _INSTRUCTOR}),
    ),
    EventType.RESOURCE_SELECTED: EventSpec(
        event_type=EventType.RESOURCE_SELECTED,
        actor_types=frozenset({ActorType.TRAINEE}),
        payload_keys={
            "assignment_id": "uuid",
            "resource_id": "uuid",
            "callsign": "str",
            "service_type": "ServiceType",
            "resource_type": "ResourceType",
            "capabilities": "list[str]",
            "at_offset_ms": "int",
        },
        visible_to=frozenset({_DDS, _INSTRUCTOR}),
    ),
    EventType.RESOURCE_DISPATCHED: EventSpec(
        event_type=EventType.RESOURCE_DISPATCHED,
        actor_types=frozenset({ActorType.TRAINEE}),
        payload_keys={
            "assignment_id": "uuid",
            "resource_ids": "list[uuid]",
            "callsigns": "list[str]",
            "capabilities_union": "list[str]",
            "eta_seconds_by_resource": "object",
            # Additive (E9): `resource_id -> ServiceType` for every dispatched unit. §10.13 L1290
            # already claims the payload "carries `capabilities_union` and `service_type` per
            # resource, so no resource table lookup is needed" while the row had no such key.
            # It is needed because a unit's `assignment_id` does NOT imply its service: an
            # off-service unit attaches to the primary leg (E9 analyst R4), so `min_units_by_
            # service` may never be scored through leg -> service.
            "service_type_by_resource": "object",
            "at_offset_ms": "int",
            "is_additional": "bool",
        },
        visible_to=frozenset({_DDS, _INSTRUCTOR}),
    ),
    EventType.RESOURCE_STATUS_CHANGED: EventSpec(
        event_type=EventType.RESOURCE_STATUS_CHANGED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "resource_id": "uuid",
            "callsign": "str",
            "previous_status": "ResourceStatus",
            "new_status": "ResourceStatus",
            "trigger": "str",
            "assignment_id": "uuid | null",
            "source_world_event_id": "str | null",
            "at_offset_ms": "int",
        },
        visible_to=frozenset({_DDS, _INSTRUCTOR}),
    ),
    EventType.WORLD_EVENT_TRIGGERED: EventSpec(
        event_type=EventType.WORLD_EVENT_TRIGGERED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "world_event_id": "str",
            "kind": "WorldEventKind",
            "occurrence": "int",
            "title_ru": "str",
            "caller_observable": "bool",
            "trigger_reason": "str",
            "effect_kinds": "list[EffectKind]",
            "at_offset_ms": "int",
        },
        visible_to=frozenset({_INSTRUCTOR}),
    ),
    EventType.ROLE_STAGE_COMPLETED: EventSpec(
        event_type=EventType.ROLE_STAGE_COMPLETED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "role_stage_id": "uuid",
            "role_type": "RoleType",
            "final_state": "str",
            "duration_ms": "int",
        },
        visible_to=frozenset({_OP, _DDS, _INSTRUCTOR}),
    ),
    EventType.SCORING_RULE_EVALUATED: EventSpec(
        event_type=EventType.SCORING_RULE_EVALUATED,
        actor_types=frozenset({ActorType.SYSTEM}),
        payload_keys={
            "rule_id": "str",
            "evaluator_type": "EvaluatorType",
            "category": "ScoringCategory",
            "points_awarded": "float",
            "max_points": "float",
            "passed": "bool",
            "critical": "bool",
            "evidence": "list[object]",
        },
        visible_to=frozenset({_INSTRUCTOR}),
    ),
    EventType.SESSION_COMPLETED: EventSpec(
        event_type=EventType.SESSION_COMPLETED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "at_offset_ms": "int",
            "final_session_state": "SessionState",
            "total_events": "int",
        },
        visible_to=frozenset({_OP, _DDS, _INSTRUCTOR}),
    ),
    EventType.MODEL_FALLBACK_USED: EventSpec(
        event_type=EventType.MODEL_FALLBACK_USED,
        actor_types=frozenset({ActorType.SYSTEM}),
        payload_keys={
            "component": 'Literal["INTERPRETER", "GENERATOR", "VALIDATOR", "ASR", "TTS"]',
            "reason": "str",
            "attempt": "int",
            "fallback_kind": "str",
            "turn_index": "int | null",
        },
        visible_to=frozenset({_INSTRUCTOR}),
    ),
    EventType.MODEL_ERROR: EventSpec(
        event_type=EventType.MODEL_ERROR,
        actor_types=frozenset({ActorType.SYSTEM}),
        payload_keys={
            "component": "str",
            "provider": "str",
            "model": "str",
            "error_code": "str",
            "message": "str",
            "recoverable": "bool",
            "turn_index": "int | null",
        },
        visible_to=frozenset({_INSTRUCTOR}),
    ),
    # ---------------------------------------------------------------------------------------
    # Additive events (D5, 21)
    # ---------------------------------------------------------------------------------------
    EventType.SESSION_ABORTED: EventSpec(
        event_type=EventType.SESSION_ABORTED,
        actor_types=frozenset({ActorType.INSTRUCTOR, ActorType.SYSTEM}),
        payload_keys={
            "previous_state": "SessionState",
            "reason": "str",
            "at_offset_ms": "int",
            "aborted_by_user_id": "uuid | null",
        },
        visible_to=frozenset({_OP, _DDS, _INSTRUCTOR}),
    ),
    EventType.STAGE_STATE_CHANGED: EventSpec(
        event_type=EventType.STAGE_STATE_CHANGED,
        actor_types=frozenset({ActorType.SIMULATION, ActorType.TRAINEE, ActorType.INSTRUCTOR}),
        payload_keys={
            "role_stage_id": "uuid",
            "role_type": "RoleType",
            "previous_state": "str",
            "new_state": "str",
            "trigger": "str",
            "fired_by_actor_type": "ActorType",
            "fired_by_user_id": "uuid | null",
            "at_offset_ms": "int",
        },
        # §40.4 row 30: pushed only when role_type matches the connection's role — both trainee
        # roles are in the static whitelist; the per-connection filter is dynamic, not this set.
        visible_to=frozenset({_OP, _DDS, _INSTRUCTOR}),
    ),
    EventType.ROLE_TRANSITION_STARTED: EventSpec(
        event_type=EventType.ROLE_TRANSITION_STARTED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "from_role_stage_id": "uuid",
            "from_role_type": "RoleType",
            "to_role_stage_id": "uuid",
            "to_role_type": "RoleType",
            "pause_seconds": "int",
            "at_offset_ms": "int",
        },
        visible_to=frozenset({_OP, _DDS, _INSTRUCTOR}),
    ),
    EventType.ROLE_TRANSITION_COMPLETED: EventSpec(
        event_type=EventType.ROLE_TRANSITION_COMPLETED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "to_role_stage_id": "uuid",
            "to_role_type": "RoleType",
            "incident_id": "uuid",
            "at_offset_ms": "int",
        },
        visible_to=frozenset({_OP, _DDS, _INSTRUCTOR}),
    ),
    EventType.SERVICE_DESELECTED: EventSpec(
        event_type=EventType.SERVICE_DESELECTED,
        actor_types=frozenset({ActorType.TRAINEE}),
        payload_keys={
            "card_id": "uuid",
            "revision_id": "uuid",
            "service_type": "ServiceType",
            "selected_services": "list[ServiceType]",
            "at_offset_ms": "int",
        },
        visible_to=frozenset({_OP, _INSTRUCTOR}),
    ),
    EventType.RESOURCE_DESELECTED: EventSpec(
        event_type=EventType.RESOURCE_DESELECTED,
        actor_types=frozenset({ActorType.TRAINEE}),
        payload_keys={
            "assignment_id": "uuid",
            "resource_id": "uuid",
            "callsign": "str",
            "at_offset_ms": "int",
        },
        visible_to=frozenset({_DDS, _INSTRUCTOR}),
    ),
    EventType.DDS_STATUS_UPDATE_SENT: EventSpec(
        event_type=EventType.DDS_STATUS_UPDATE_SENT,
        actor_types=frozenset({ActorType.TRAINEE}),
        payload_keys={
            "assignment_id": "uuid",
            "update_kind": "StatusUpdateKind",
            "text_ru": "str",
            "at_offset_ms": "int",
            "actor_user_id": "uuid",
        },
        visible_to=frozenset({_DDS, _INSTRUCTOR}),
    ),
    EventType.DDS_INCIDENT_CLOSED: EventSpec(
        event_type=EventType.DDS_INCIDENT_CLOSED,
        actor_types=frozenset({ActorType.TRAINEE}),
        payload_keys={
            "assignment_id": "uuid",
            "closure_reason": "ClosureReason",
            "released_resource_ids": "list[uuid]",
            "at_offset_ms": "int",
            "actor_user_id": "uuid",
        },
        visible_to=frozenset({_DDS, _INSTRUCTOR}),
    ),
    EventType.NOTIFICATION_CREATED: EventSpec(
        event_type=EventType.NOTIFICATION_CREATED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "notification_id": "uuid",
            "audience_role": "RoleType",
            "severity": "NotificationSeverity",
            "title_ru": "str",
            "body_ru": "str",
            "source_world_event_id": "str | null",
            "at_offset_ms": "int",
        },
        # §40.4 row 37: pushed only to the notification's audience_role — both trainee roles are
        # in the static whitelist; the per-connection filter is dynamic, not this set.
        visible_to=frozenset({_OP, _DDS, _INSTRUCTOR}),
    ),
    EventType.NOTIFICATION_ACKNOWLEDGED: EventSpec(
        event_type=EventType.NOTIFICATION_ACKNOWLEDGED,
        actor_types=frozenset({ActorType.TRAINEE}),
        payload_keys={
            "notification_id": "uuid",
            # Additive (E9): the acknowledged notification's audience, copied from
            # `NOTIFICATION_CREATED`, so the realtime redaction of §40.4 can push the
            # acknowledgement to that role alone instead of to both trainee roles.
            "audience_role": "RoleType",
            "at_offset_ms": "int",
            "latency_ms": "int",
            "actor_user_id": "uuid",
        },
        visible_to=frozenset({_OP, _DDS, _INSTRUCTOR}),
    ),
    EventType.RADIO_MESSAGE_CREATED: EventSpec(
        event_type=EventType.RADIO_MESSAGE_CREATED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "radio_message_id": "uuid",
            "from_callsign": "str",
            "to_role": "RoleType",
            "text_ru": "str",
            "resource_id": "uuid | null",
            "source_world_event_id": "str | null",
            "at_offset_ms": "int",
        },
        # §40.4 row 39: pushed only when to_role matches the connection's role.
        visible_to=frozenset({_OP, _DDS, _INSTRUCTOR}),
    ),
    EventType.WORLD_TRUTH_MUTATED: EventSpec(
        event_type=EventType.WORLD_TRUTH_MUTATED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "revision": "int",
            "changes": "list[{fact_id: str, previous_value: FactValue, new_value: FactValue}]",
            "source_world_event_id": "str",
            "at_offset_ms": "int",
        },
        # §40.4 row 40: never to a trainee — the WorldTruth boundary (D3, D8, §42 tests 1 and 3).
        visible_to=frozenset({_INSTRUCTOR}),
    ),
    EventType.CALLER_BELIEF_MUTATED: EventSpec(
        event_type=EventType.CALLER_BELIEF_MUTATED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "revision": "int",
            "changes": (
                "list[{fact_id: str, previous_value: FactValue, new_value: FactValue, "
                "knowledge: KnowledgeState, certainty: float}]"
            ),
            "source_world_event_id": "str",
            "at_offset_ms": "int",
        },
        # §40.4 row 41: never to a trainee.
        visible_to=frozenset({_INSTRUCTOR}),
    ),
    EventType.CALLER_EMOTION_CHANGED: EventSpec(
        event_type=EventType.CALLER_EMOTION_CHANGED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "previous_emotion": "EmotionLabel",
            "new_emotion": "EmotionLabel",
            "previous_stress_level": "float",
            "new_stress_level": "float",
            "emotion_rule_id": "str | null",
            "trigger_kind": "str",
            "at_offset_ms": "int",
        },
        visible_to=frozenset({_INSTRUCTOR}),
    ),
    EventType.CALL_ENDED: EventSpec(
        event_type=EventType.CALL_ENDED,
        actor_types=frozenset({ActorType.TRAINEE, ActorType.SIMULATION}),
        payload_keys={
            "call_id": "uuid",
            "at_offset_ms": "int",
            "duration_ms": "int",
            "ended_by": "ActorType",
            "reason": "str",
        },
        visible_to=frozenset({_OP, _INSTRUCTOR}),
    ),
    EventType.DIALOGUE_INTERPRETED: EventSpec(
        event_type=EventType.DIALOGUE_INTERPRETED,
        actor_types=frozenset({ActorType.MODEL}),
        payload_keys={
            "turn_index": "int",
            "speech_act": "SpeechAct",
            "requested_facts": "list[{fact_id: str, explicit: bool}]",
            "operator_assertions": "list[{fact_id: str, asserted_value: FactValue}]",
            "confirmation_targets": "list[str]",
            "semantic_confidence": "float",
            "repair_retry_used": "bool",
        },
        visible_to=frozenset({_INSTRUCTOR}),
    ),
    EventType.FACT_GATE_EVALUATED: EventSpec(
        event_type=EventType.FACT_GATE_EVALUATED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "turn_index": "int",
            "decisions": "list[{fact_id: str, outcome: GateOutcome, reason: GateReason}]",
            "allowed_fact_ids": "list[str]",
            "spontaneous_attached": "list[str]",
            "withheld_count": "int",
            "at_offset_ms": "int",
        },
        # §40.4 row 45: never to a trainee — gate internals (D3, D10).
        visible_to=frozenset({_INSTRUCTOR}),
    ),
    EventType.FACTS_DELIVERED: EventSpec(
        event_type=EventType.FACTS_DELIVERED,
        actor_types=frozenset({ActorType.SIMULATION}),
        payload_keys={
            "turn_index": "int",
            "fact_ids": "list[str]",
            "delivered_via": 'Literal["TTS_COMPLETED"]',
            "at_offset_ms": "int",
        },
        visible_to=frozenset({_INSTRUCTOR}),
    ),
    EventType.TRANSPORT_DISCONNECTED: EventSpec(
        event_type=EventType.TRANSPORT_DISCONNECTED,
        actor_types=frozenset({ActorType.SYSTEM}),
        payload_keys={
            "call_id": "uuid",
            "participant_identity": "str",
            "reason": "str",
            "at_offset_ms": "int",
        },
        visible_to=frozenset({_OP, _INSTRUCTOR}),
    ),
    EventType.TRANSPORT_RECONNECTED: EventSpec(
        event_type=EventType.TRANSPORT_RECONNECTED,
        actor_types=frozenset({ActorType.SYSTEM}),
        payload_keys={
            "call_id": "uuid",
            "participant_identity": "str",
            "downtime_ms": "int",
            "at_offset_ms": "int",
        },
        visible_to=frozenset({_OP, _INSTRUCTOR}),
    ),
    EventType.INFERENCE_HEALTH_CHANGED: EventSpec(
        event_type=EventType.INFERENCE_HEALTH_CHANGED,
        actor_types=frozenset({ActorType.SYSTEM}),
        payload_keys={
            "component": "str",
            "previous_status": "HealthStatus",
            "new_status": "HealthStatus",
            "detail": "str",
        },
        visible_to=frozenset({_INSTRUCTOR}),
    ),
}

assert frozenset(EVENT_PAYLOAD_CATALOG) == frozenset(EventType)


def validate_payload(event_type: EventType, payload: Mapping[str, Any]) -> None:
    """Raise `DomainError` when `payload` lacks a catalogued required key for `event_type`
    (ruling R2). A key is optional iff its `EVENT_PAYLOAD_CATALOG` type expression contains the
    substring `"null"` (§10.13's own "nullable/optional" convention); every other catalogued key
    must be present (its value is not type-checked here — that is each domain method's job).
    """
    spec = EVENT_PAYLOAD_CATALOG[event_type]
    missing = sorted(
        key
        for key, type_expr in spec.payload_keys.items()
        if "null" not in type_expr and key not in payload
    )
    if missing:
        raise DomainError(
            f"{event_type.value} payload missing required key(s): {', '.join(missing)}"
        )
