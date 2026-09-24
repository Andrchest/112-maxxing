"""Typed UUID aliases (HLD `10-domain-model.md` §10.1: "SessionId, IncidentId, …").

Every `…Id` name referenced anywhere in `10-domain-model.md` gets a `NewType` here so that domain
signatures cannot mix up ids belonging to different aggregates by accident, while the runtime
representation stays a plain `uuid.UUID`.
"""

from __future__ import annotations

from typing import NewType
from uuid import UUID

AssignmentId = NewType("AssignmentId", UUID)
CardId = NewType("CardId", UUID)
CardRevisionId = NewType("CardRevisionId", UUID)
EventId = NewType("EventId", UUID)
IncidentId = NewType("IncidentId", UUID)
LessonId = NewType("LessonId", UUID)
ResourceId = NewType("ResourceId", UUID)
RoleStageId = NewType("RoleStageId", UUID)
ScenarioId = NewType("ScenarioId", UUID)
ScenarioVersionId = NewType("ScenarioVersionId", UUID)
SessionId = NewType("SessionId", UUID)
SnapshotId = NewType("SnapshotId", UUID)
UserId = NewType("UserId", UUID)
