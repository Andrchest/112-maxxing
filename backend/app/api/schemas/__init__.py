"""API-level pydantic models — one per `openapi.yaml` schema this epic implements (D8, D12).

These are **not** domain types and never will be. D2 keeps `app.api` from importing
`app.domain.layers` at all, and `backend/tests/api/test_router_layering.py` scans the routers to
prove it: a response model here is built from an application result by an explicit mapping
function, so the wire shape and the domain shape can move independently and neither one silently
leaks the other's fields.

Property names are copied **literally** from `openapi.yaml` — `backend/tests/api/test_contract.py`
compares each response model's property-name set with the YAML schema's `properties` keys, so a
rename on either side fails the suite.
"""

from __future__ import annotations

from app.api.schemas.auth import LoginRequestSchema, TokenResponseSchema, UserAccountSchema
from app.api.schemas.health import (
    ComponentHealthSchema,
    HealthLiveResponseSchema,
    HealthReadyResponseSchema,
)
from app.api.schemas.scenarios import (
    ScenarioImportRequestSchema,
    ScenarioSummarySchema,
    ScenarioValidationIssueSchema,
    ScenarioValidationReportSchema,
    ScenarioVersionListItemSchema,
    ScenarioVersionTraineeSummarySchema,
)
from app.api.schemas.sessions import (
    AbortSessionRequestSchema,
    ParticipantAssignmentSchema,
    RoleStageViewSchema,
    SessionCreateRequestSchema,
    SessionDetailSchema,
    SessionListItemSchema,
    SessionParticipantViewSchema,
)

__all__ = [
    "AbortSessionRequestSchema",
    "ComponentHealthSchema",
    "HealthLiveResponseSchema",
    "HealthReadyResponseSchema",
    "LoginRequestSchema",
    "ParticipantAssignmentSchema",
    "RoleStageViewSchema",
    "ScenarioImportRequestSchema",
    "ScenarioSummarySchema",
    "ScenarioValidationIssueSchema",
    "ScenarioValidationReportSchema",
    "ScenarioVersionListItemSchema",
    "ScenarioVersionTraineeSummarySchema",
    "SessionCreateRequestSchema",
    "SessionDetailSchema",
    "SessionListItemSchema",
    "SessionParticipantViewSchema",
    "TokenResponseSchema",
    "UserAccountSchema",
]
