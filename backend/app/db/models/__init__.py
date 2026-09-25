"""ORM models — every table of HLD `20-db-schema.md` §20.1.

One module per HLD group: `reference` (§20.2), `session` (§20.3), `layers` (§20.4), `dds` (§20.5),
`events` (§20.6, with I4 E25's `audit_log`), `scoring` (§20.7), `reports` (§20.10, additive in
E16). Importing this package imports every module, so `app.db.base.Base.metadata` is complete —
which is what Alembic's `env.py` and `alembic check` rely on.

These classes are persistence structures only. They never inherit from, embed or wrap a domain
type; mapping to and from `app.domain` lives in `app/infrastructure/persistence/` (D2, D3, D5).
"""

from __future__ import annotations

from app.db.base import Base
from app.db.models.dds import (
    DDSAssignment,
    DdsCall,
    DDSServiceStatusHistory,
    EmergencyResource,
    Notification,
    ResourceStateChange,
)
from app.db.models.events import (
    AudioSegment,
    AuditLog,
    DialogueTurn,
    InferenceMetric,
    RecordingPurgeAudit,
    SessionEvent,
    TranscriptSegment,
)
from app.db.models.layers import (
    HandoffSnapshot,
    IncidentCallerBelief,
    IncidentCard,
    IncidentCardRevision,
    IncidentWorldState,
)
from app.db.models.reference import (
    Scenario,
    ScenarioVersion,
    ScoringRule,
    TraineeGroup,
    TraineeGroupMember,
    User,
)
from app.db.models.reports import ReportExplanation, ResultComment
from app.db.models.scoring import ScoreEvidence, ScoreResult
from app.db.models.session import (
    Incident,
    Lesson,
    RoleStage,
    SessionParticipant,
    SimulationSession,
    WorldEngineState,
)

__all__ = [
    "AudioSegment",
    "AuditLog",
    "Base",
    "DDSAssignment",
    "DDSServiceStatusHistory",
    "DdsCall",
    "DialogueTurn",
    "EmergencyResource",
    "HandoffSnapshot",
    "Incident",
    "IncidentCallerBelief",
    "IncidentCard",
    "IncidentCardRevision",
    "IncidentWorldState",
    "InferenceMetric",
    "Lesson",
    "Notification",
    "RecordingPurgeAudit",
    "ReportExplanation",
    "ResourceStateChange",
    "ResultComment",
    "RoleStage",
    "Scenario",
    "ScenarioVersion",
    "ScoreEvidence",
    "ScoreResult",
    "ScoringRule",
    "SessionEvent",
    "SessionParticipant",
    "SimulationSession",
    "TraineeGroup",
    "TraineeGroupMember",
    "TranscriptSegment",
    "User",
    "WorldEngineState",
]
