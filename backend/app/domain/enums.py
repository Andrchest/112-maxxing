"""Domain enums (HLD `10-domain-model.md` §10.2), except `EventType` (`events/types.py`).

All enums are `str, Enum`; the member name is the wire value (member `NAME == VALUE` for every
member of every enum here). Names, members and member order are copied literally from §10.2 —
this module is law for every later slice that references these types. The one non-enum here is
`ServiceId` (I3 E2a, D18), which replaced the `ServiceType` enum.
"""

from __future__ import annotations

from enum import Enum
from typing import NewType


class SessionMode(str, Enum):
    """SPEC §1, D6."""

    SINGLE_ROLE = "SINGLE_ROLE"
    FULL_CYCLE_SINGLE_TRAINEE = "FULL_CYCLE_SINGLE_TRAINEE"
    MULTI_TRAINEE = "MULTI_TRAINEE"
    ASSESSMENT = "ASSESSMENT"


class SessionState(str, Enum):
    """SPEC §7, exact."""

    CREATED = "CREATED"
    READY = "READY"
    ACTIVE = "ACTIVE"
    ROLE_TRANSITION = "ROLE_TRANSITION"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class Operator112StageState(str, Enum):
    """SPEC §7, exact."""

    WAITING_FOR_CALL = "WAITING_FOR_CALL"
    RINGING = "RINGING"
    CONNECTED = "CONNECTED"
    INTERVIEW = "INTERVIEW"
    HANDOFF_PREPARATION = "HANDOFF_PREPARATION"
    HANDED_OFF = "HANDED_OFF"
    STAGE_COMPLETED = "STAGE_COMPLETED"


class DDSStageState(str, Enum):
    """SPEC §7, exact."""

    RECEIVED = "RECEIVED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOURCE_SELECTION = "RESOURCE_SELECTION"
    DISPATCHED = "DISPATCHED"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    WORKING = "WORKING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class RoleType(str, Enum):
    """SPEC §1, §14."""

    OPERATOR_112 = "OPERATOR_112"
    DDS = "DDS"
    EDDS = "EDDS"


class ActorType(str, Enum):
    """D5."""

    TRAINEE = "TRAINEE"
    INSTRUCTOR = "INSTRUCTOR"
    SIMULATION = "SIMULATION"
    MODEL = "MODEL"
    SYSTEM = "SYSTEM"


ServiceId = NewType("ServiceId", str)
"""A receiving service — an id of the reference pack's service catalog (HLD 70 §70.6.3, D18).

Replaces the closed `ServiceType` enum of §10.2: the catalog («СЛУЖБЫ 112»,
`reference/services/v1.yaml`) is data, so a service id is a string checked against it where it
enters — scenario import (rule R37), `selectRecipientService` (`422 SERVICE_UNKNOWN`) — rather than
a member of a Python enum. Every stored snapshot, payload and fixture stays valid by value.
"""

LEGACY_SERVICE_IDS: tuple[ServiceId, ...] = (
    ServiceId("FIRE_RESCUE"),
    ServiceId("POLICE"),
    ServiceId("AMBULANCE"),
    ServiceId("GAS_SERVICE"),
    ServiceId("UTILITY_EMERGENCY"),
    ServiceId("EDDS"),
)
"""The six ids the former `ServiceId` enum had, verbatim and in its order — the first six
catalog entries (§70.6.3). `UTILITY_EMERGENCY` is the demo's wrong-but-plausible choice so that
`SERVICE_SELECTION` scoring has something to penalise; the catalog keeps it as `deprecated` (C8).
"""


class ResourceType(str, Enum):
    FIRE_ENGINE = "FIRE_ENGINE"
    LADDER_TRUCK = "LADDER_TRUCK"
    RESCUE_UNIT = "RESCUE_UNIT"
    AMBULANCE_UNIT = "AMBULANCE_UNIT"
    RESUSCITATION_UNIT = "RESUSCITATION_UNIT"
    POLICE_PATROL = "POLICE_PATROL"
    GAS_EMERGENCY_UNIT = "GAS_EMERGENCY_UNIT"
    UTILITY_CREW = "UTILITY_CREW"
    FIRE_CHIEF_CAR = "FIRE_CHIEF_CAR"


class ResourceStatus(str, Enum):
    """SPEC §11."""

    AVAILABLE = "AVAILABLE"
    SELECTED = "SELECTED"
    DISPATCHED = "DISPATCHED"
    EN_ROUTE = "EN_ROUTE"
    ON_SCENE = "ON_SCENE"
    WORKING = "WORKING"
    RETURNING = "RETURNING"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    UNAVAILABLE = "UNAVAILABLE"


class KnowledgeState(str, Enum):
    """SPEC §5, exact."""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    INCORRECT_BELIEF = "INCORRECT_BELIEF"
    UNCERTAIN = "UNCERTAIN"


class DisclosurePolicy(str, Enum):
    """SPEC §5, exact."""

    SPONTANEOUS = "SPONTANEOUS"
    ON_ASK = "ON_ASK"
    ONLY_IF_EXPLICITLY_ASKED = "ONLY_IF_EXPLICITLY_ASKED"
    NEVER_DISCLOSE = "NEVER_DISCLOSE"


class SpeechAct(str, Enum):
    """SPEC §20."""

    QUESTION = "QUESTION"
    ANSWER = "ANSWER"
    STATEMENT = "STATEMENT"
    CONFIRMATION = "CONFIRMATION"
    INSTRUCTION = "INSTRUCTION"
    GREETING = "GREETING"
    CLOSING = "CLOSING"
    REASSURANCE = "REASSURANCE"
    REPEAT_REQUEST = "REPEAT_REQUEST"
    UNINTELLIGIBLE = "UNINTELLIGIBLE"


class IncidentType(str, Enum):
    """Card value domain."""

    FIRE = "FIRE"
    MEDICAL = "MEDICAL"
    CRIME = "CRIME"
    TRAFFIC_ACCIDENT = "TRAFFIC_ACCIDENT"
    GAS_LEAK = "GAS_LEAK"
    UTILITY_FAILURE = "UTILITY_FAILURE"
    RESCUE = "RESCUE"
    OTHER = "OTHER"


class CallerRelationship(str, Enum):
    """SPEC §6 "relationship to incident"."""

    VICTIM = "VICTIM"
    WITNESS = "WITNESS"
    NEIGHBOUR = "NEIGHBOUR"
    RELATIVE = "RELATIVE"
    PASSERBY = "PASSERBY"
    OFFICIAL = "OFFICIAL"
    UNKNOWN = "UNKNOWN"


class AgeGroup(str, Enum):
    CHILD = "CHILD"
    TEEN = "TEEN"
    ADULT = "ADULT"
    ELDERLY = "ELDERLY"


class EmotionLabel(str, Enum):
    """SPEC §6."""

    CALM = "CALM"
    WORRIED = "WORRIED"
    FRIGHTENED = "FRIGHTENED"
    PANICKED = "PANICKED"
    ANGRY = "ANGRY"
    CONFUSED = "CONFUSED"
    APATHETIC = "APATHETIC"


class ValueType(str, Enum):
    """Fact and card value typing."""

    STRING = "STRING"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    BOOLEAN = "BOOLEAN"
    ENUM = "ENUM"
    STRING_LIST = "STRING_LIST"


class NotificationSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class StatusUpdateKind(str, Enum):
    """DDS -> incident status updates."""

    ACKNOWLEDGEMENT = "ACKNOWLEDGEMENT"
    EN_ROUTE_REPORT = "EN_ROUTE_REPORT"
    ON_SCENE_REPORT = "ON_SCENE_REPORT"
    SITUATION_UPDATE = "SITUATION_UPDATE"
    ADDITIONAL_FORCES_REQUESTED = "ADDITIONAL_FORCES_REQUESTED"
    RESOLUTION_REPORT = "RESOLUTION_REPORT"


class HealthStatus(str, Enum):
    """D8."""

    READY = "READY"
    WARMING = "WARMING"
    NOT_READY = "NOT_READY"
    FATAL = "FATAL"


class ScoringCategory(str, Enum):
    INFORMATION_GATHERING = "INFORMATION_GATHERING"
    CARD_QUALITY = "CARD_QUALITY"
    SERVICE_ROUTING = "SERVICE_ROUTING"
    TIMELINESS = "TIMELINESS"
    WORKFLOW = "WORKFLOW"
    RESOURCE_MANAGEMENT = "RESOURCE_MANAGEMENT"
    COMMUNICATION = "COMMUNICATION"


class EvaluatorType(str, Enum):
    """SPEC §28, exact ten."""

    FACT_OBTAINED = "FACT_OBTAINED"
    CARD_FIELD_CORRECT = "CARD_FIELD_CORRECT"
    CARD_FIELD_PRESENT = "CARD_FIELD_PRESENT"
    CARD_CONTRADICTION = "CARD_CONTRADICTION"
    SERVICE_SELECTION = "SERVICE_SELECTION"
    DEADLINE = "DEADLINE"
    WORKFLOW_ACTION = "WORKFLOW_ACTION"
    RESOURCE_SELECTION = "RESOURCE_SELECTION"
    REQUIRED_STATUS_UPDATE = "REQUIRED_STATUS_UPDATE"
    HANDOFF_COMPLETENESS = "HANDOFF_COMPLETENESS"


class GateOutcome(str, Enum):
    """§21, D10."""

    ALLOWED = "ALLOWED"
    ALLOWED_SPONTANEOUS = "ALLOWED_SPONTANEOUS"
    ALLOWED_REPEAT = "ALLOWED_REPEAT"
    WITHHELD = "WITHHELD"
    NOT_YET = "NOT_YET"
    UNAVAILABLE = "UNAVAILABLE"


class GateReason(str, Enum):
    """§21, D10."""

    OK = "OK"
    NEVER_DISCLOSE = "NEVER_DISCLOSE"
    CALLER_DOES_NOT_KNOW = "CALLER_DOES_NOT_KNOW"
    NOT_YET_AVAILABLE = "NOT_YET_AVAILABLE"
    REQUIRES_EXPLICIT_QUESTION = "REQUIRES_EXPLICIT_QUESTION"
    UNKNOWN_FACT_ID = "UNKNOWN_FACT_ID"
    ALREADY_REVEALED = "ALREADY_REVEALED"


class WorldEventKind(str, Enum):
    """SPEC §12, exact."""

    TIMED = "TIMED"
    CONDITIONAL = "CONDITIONAL"
    ACTION_TRIGGERED = "ACTION_TRIGGERED"
    SEEDED_RANDOM = "SEEDED_RANDOM"


class EffectKind(str, Enum):
    """D7."""

    MUTATE_WORLD_TRUTH = "MUTATE_WORLD_TRUTH"
    MUTATE_CALLER_BELIEF = "MUTATE_CALLER_BELIEF"
    CREATE_NOTIFICATION = "CREATE_NOTIFICATION"
    CREATE_RADIO_MESSAGE = "CREATE_RADIO_MESSAGE"
    ALTER_RESOURCE_AVAILABILITY = "ALTER_RESOURCE_AVAILABILITY"
    TRIGGER_EVENT = "TRIGGER_EVENT"
    CHANGE_CALLER_EMOTION = "CHANGE_CALLER_EMOTION"


class ClosureReason(str, Enum):
    RESOLVED = "RESOLVED"
    FALSE_CALL = "FALSE_CALL"
    TRANSFERRED = "TRANSFERRED"
    CANCELLED_BY_CALLER = "CANCELLED_BY_CALLER"
