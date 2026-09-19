"""`VisibilitySource`, `DataVisibilityPolicy` (HLD `10-domain-model.md` §10.9, D3)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from app.domain.enums import RoleType
from app.domain.events.types import EventType


class VisibilitySource(str, Enum):
    """§10.9, exact."""

    OPERATOR_CARD = "OPERATOR_CARD"
    CARD_REVISIONS = "CARD_REVISIONS"
    HANDOFF_SNAPSHOT = "HANDOFF_SNAPSHOT"
    DDS_ASSIGNMENT = "DDS_ASSIGNMENT"
    RESOURCE_BOARD = "RESOURCE_BOARD"
    NOTIFICATIONS = "NOTIFICATIONS"
    RADIO_MESSAGES = "RADIO_MESSAGES"
    TRANSCRIPT = "TRANSCRIPT"
    CALL_STATE = "CALL_STATE"
    SCORE_REPORT = "SCORE_REPORT"
    WORLD_TRUTH = "WORLD_TRUTH"
    CALLER_BELIEF = "CALLER_BELIEF"
    GATE_INTERNALS = "GATE_INTERNALS"


class DataVisibilityPolicy(BaseModel):
    """A whitelist, never a blacklist (§10.9, D3)."""

    model_config = ConfigDict(frozen=True)

    role_type: RoleType
    sources: frozenset[VisibilitySource]
    visible_event_types: frozenset[EventType]

    def may_read(self, source: VisibilitySource) -> bool:
        return source in self.sources

    def may_receive(self, event_type: EventType) -> bool:
        return event_type in self.visible_event_types
