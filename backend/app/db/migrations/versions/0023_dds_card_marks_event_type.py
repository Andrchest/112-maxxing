"""session_events.event_type gains DDS_CARD_MARKS_SET (I7 E55 ДДС ЧС/ЧП marks).

E55 added the event type to `app.domain.events.types.EventType` but no migration: a database built
from `0001_baseline` after E55 has it (the baseline reads the enum), an older one rejects the
event with `ck_session_events_event_type` (seen on the demo: `POST /dds/card-marks` -> 500).
Additive only: the CHECK is replaced with the full list at this revision. The list is inlined, not
imported (same rule as 0016/0019/0021).

Revision ID: 0023_dds_card_marks_event_type
Revises: 0022_ml_audit
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from app.db.base import enum_check

revision: str = "0023_dds_card_marks_event_type"
down_revision: str | None = "0022_ml_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "session_events"
_CONSTRAINT = "event_type"

_NEW_EVENT_TYPES = (
    "SESSION_CREATED",
    "SESSION_STARTED",
    "ROLE_STAGE_STARTED",
    "CALL_RINGING",
    "CALL_ANSWERED",
    "USER_SPEECH_STARTED",
    "USER_SPEECH_ENDED",
    "ASR_PARTIAL",
    "ASR_FINAL",
    "CALLER_RESPONSE_PLANNED",
    "CALLER_RESPONSE_GENERATED",
    "CALLER_TTS_STARTED",
    "CALLER_TTS_ENDED",
    "CALLER_UTTERANCE_INTERRUPTED",
    "CARD_FIELD_CHANGED",
    "SERVICE_SELECTED",
    "HANDOFF_CREATED",
    "HANDOFF_RECEIVED",
    "DDS_ACKNOWLEDGED",
    "RESOURCE_SELECTED",
    "RESOURCE_DISPATCHED",
    "RESOURCE_STATUS_CHANGED",
    "WORLD_EVENT_TRIGGERED",
    "ROLE_STAGE_COMPLETED",
    "SCORING_RULE_EVALUATED",
    "SESSION_COMPLETED",
    "MODEL_FALLBACK_USED",
    "MODEL_ERROR",
    "SESSION_ABORTED",
    "STAGE_STATE_CHANGED",
    "ROLE_TRANSITION_STARTED",
    "ROLE_TRANSITION_COMPLETED",
    "SERVICE_DESELECTED",
    "RESOURCE_DESELECTED",
    "DDS_STATUS_UPDATE_SENT",
    "DDS_INCIDENT_CLOSED",
    "NOTIFICATION_CREATED",
    "NOTIFICATION_ACKNOWLEDGED",
    "RADIO_MESSAGE_CREATED",
    "WORLD_TRUTH_MUTATED",
    "CALLER_BELIEF_MUTATED",
    "CALLER_EMOTION_CHANGED",
    "CALL_ENDED",
    "DIALOGUE_INTERPRETED",
    "FACT_GATE_EVALUATED",
    "FACTS_DELIVERED",
    "TRANSPORT_DISCONNECTED",
    "TRANSPORT_RECONNECTED",
    "INFERENCE_HEALTH_CHANGED",
    "DDS_CARD_STATUS_CHANGED",
    "RECIPIENTS_RESOLVED",
    "DDS_CARD_OPENED",
    "DDS_SERVICE_STATUS_SET",
    "DDS_CARD_ISSUE_FLAGGED",
    "DDS_CARD_MARKS_SET",
    "DDS_CALL_STARTED",
    "DDS_CALL_ANSWERED",
    "DDS_CALL_ENDED",
    "DDS_CALL_STATUS_PROPOSED",
    "DDS_CALL_ASSERTION",
)

_OLD_EVENT_TYPES = (
    "SESSION_CREATED",
    "SESSION_STARTED",
    "ROLE_STAGE_STARTED",
    "CALL_RINGING",
    "CALL_ANSWERED",
    "USER_SPEECH_STARTED",
    "USER_SPEECH_ENDED",
    "ASR_PARTIAL",
    "ASR_FINAL",
    "CALLER_RESPONSE_PLANNED",
    "CALLER_RESPONSE_GENERATED",
    "CALLER_TTS_STARTED",
    "CALLER_TTS_ENDED",
    "CALLER_UTTERANCE_INTERRUPTED",
    "CARD_FIELD_CHANGED",
    "SERVICE_SELECTED",
    "HANDOFF_CREATED",
    "HANDOFF_RECEIVED",
    "DDS_ACKNOWLEDGED",
    "RESOURCE_SELECTED",
    "RESOURCE_DISPATCHED",
    "RESOURCE_STATUS_CHANGED",
    "WORLD_EVENT_TRIGGERED",
    "ROLE_STAGE_COMPLETED",
    "SCORING_RULE_EVALUATED",
    "SESSION_COMPLETED",
    "MODEL_FALLBACK_USED",
    "MODEL_ERROR",
    "SESSION_ABORTED",
    "STAGE_STATE_CHANGED",
    "ROLE_TRANSITION_STARTED",
    "ROLE_TRANSITION_COMPLETED",
    "SERVICE_DESELECTED",
    "RESOURCE_DESELECTED",
    "DDS_STATUS_UPDATE_SENT",
    "DDS_INCIDENT_CLOSED",
    "NOTIFICATION_CREATED",
    "NOTIFICATION_ACKNOWLEDGED",
    "RADIO_MESSAGE_CREATED",
    "WORLD_TRUTH_MUTATED",
    "CALLER_BELIEF_MUTATED",
    "CALLER_EMOTION_CHANGED",
    "CALL_ENDED",
    "DIALOGUE_INTERPRETED",
    "FACT_GATE_EVALUATED",
    "FACTS_DELIVERED",
    "TRANSPORT_DISCONNECTED",
    "TRANSPORT_RECONNECTED",
    "INFERENCE_HEALTH_CHANGED",
    "DDS_CARD_STATUS_CHANGED",
    "RECIPIENTS_RESOLVED",
    "DDS_CARD_OPENED",
    "DDS_SERVICE_STATUS_SET",
    "DDS_CARD_ISSUE_FLAGGED",
    "DDS_CALL_STARTED",
    "DDS_CALL_ANSWERED",
    "DDS_CALL_ENDED",
    "DDS_CALL_STATUS_PROPOSED",
    "DDS_CALL_ASSERTION",
)


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, enum_check("event_type", _NEW_EVENT_TYPES))


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, enum_check("event_type", _OLD_EVENT_TYPES))
