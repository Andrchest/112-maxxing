"""`instructor` schemas — `InstructorSessionOverview` and its own nested views (`openapi.yaml`,
E17 R4; D2, D3).

`WorldTruthViewSchema`, `CallerBeliefViewSchema`, `GateDecisionViewSchema` and `GateTurnViewSchema`
are new here rather than reused from anywhere else: nothing else in `app.api.schemas` ever renders
`WorldTruth`/`CallerBelief`/gate internals (the report's `truth_vs_card_diff` is the one other
place, and it is a diff, not these layers themselves — D11). Every other field of
`InstructorSessionOverviewSchema` reuses the mapper an existing trainee-facing schema already has
(`session_detail_schema`, `dds_work_item_schema`, `resource_schema`, `call_state_schema`,
`operator_card_schema`, `handoff_snapshot_schema`, `component_health_schema`), because the shapes
are the same contract types the trainee endpoints already answer with — only who may reach them
differs, and that is enforced in the use case, not by a second schema.

Property names are copied **literally** from `openapi.yaml`; `backend/tests/api/test_contract.py`
compares each response model's field-name set against the YAML's `properties` keys.
"""

from __future__ import annotations

from uuid import UUID

from app.api.schemas.common import ApiModel
from app.api.schemas.dds import EmergencyResourceViewSchema, resource_schema
from app.api.schemas.handoff import (
    DdsWorkItemSchema,
    HandoffSnapshotViewSchema,
    dds_work_item_schema,
    handoff_snapshot_schema,
)
from app.api.schemas.health import HealthReadyResponseSchema
from app.api.schemas.operator import (
    CallStateViewSchema,
    FactValueSchema,
    OperatorCardViewSchema,
    call_state_schema,
    operator_card_schema,
)
from app.api.schemas.sessions import RoleStageViewSchema, SessionDetailSchema, session_detail_schema
from app.application.handoff.create_handoff import handoff_snapshot_view
from app.application.instructor.get_overview import (
    GateDecisionEntry,
    GateTurnEntry,
    InstructorSessionOverviewView,
)
from app.application.operator.views import card_view
from app.domain.enums import EmotionLabel, GateOutcome, GateReason, KnowledgeState, ValueType

__all__ = [
    "CallerBeliefViewSchema",
    "GateDecisionViewSchema",
    "GateTurnViewSchema",
    "InstructorSessionOverviewSchema",
    "WorldTruthViewSchema",
    "instructor_session_overview_schema",
]


class WorldTruthViewSchema(ApiModel):
    """`openapi.yaml`'s `WorldTruthView` — instructor console and report context only (D3, D11)."""

    incident_id: UUID
    revision: int
    facts: dict[str, FactValueSchema]
    value_types: dict[str, ValueType]


class CallerBeliefViewSchema(ApiModel):
    """`openapi.yaml`'s `CallerBeliefView` — what the simulated caller believes, instructor only."""

    incident_id: UUID
    revision: int
    facts: dict[str, FactValueSchema]
    knowledge: dict[str, KnowledgeState]
    certainty: dict[str, float]
    emotion: EmotionLabel
    stress_level: float
    revealed_fact_ids: list[str]


class GateDecisionViewSchema(ApiModel):
    """`openapi.yaml`'s `GateDecisionView` — one `FACT_GATE_EVALUATED` fact verdict."""

    fact_id: str
    outcome: GateOutcome
    reason: GateReason


class GateTurnViewSchema(ApiModel):
    """`openapi.yaml`'s `GateTurnView` — one `FACT_GATE_EVALUATED` row."""

    turn_index: int
    at_offset_ms: int
    decisions: list[GateDecisionViewSchema]
    allowed_fact_ids: list[str]
    spontaneous_attached: list[str]
    withheld_count: int


class InstructorSessionOverviewSchema(ApiModel):
    """`openapi.yaml`'s `InstructorSessionOverview` — the union of the two trainee views plus the
    hidden layers; no trainee endpoint returns this schema or any part of it."""

    session: SessionDetailSchema
    stages: list[RoleStageViewSchema]
    world_truth: WorldTruthViewSchema
    caller_belief: CallerBeliefViewSchema
    gate_turns: list[GateTurnViewSchema]
    card: OperatorCardViewSchema | None
    handoff: HandoffSnapshotViewSchema | None
    assignments: list[DdsWorkItemSchema]
    resources: list[EmergencyResourceViewSchema]
    call_state: CallStateViewSchema
    last_seq_no: int
    inference_health: HealthReadyResponseSchema


def _gate_decision_schema(entry: GateDecisionEntry) -> GateDecisionViewSchema:
    return GateDecisionViewSchema(fact_id=entry.fact_id, outcome=entry.outcome, reason=entry.reason)


def _gate_turn_schema(entry: GateTurnEntry) -> GateTurnViewSchema:
    return GateTurnViewSchema(
        turn_index=entry.turn_index,
        at_offset_ms=entry.at_offset_ms,
        decisions=[_gate_decision_schema(decision) for decision in entry.decisions],
        allowed_fact_ids=list(entry.allowed_fact_ids),
        spontaneous_attached=list(entry.spontaneous_attached),
        withheld_count=entry.withheld_count,
    )


def instructor_session_overview_schema(
    view: InstructorSessionOverviewView, *, inference_health: HealthReadyResponseSchema
) -> InstructorSessionOverviewSchema:
    """`InstructorSessionOverviewView` -> `InstructorSessionOverview`.

    `inference_health` is not on the application view (`get_overview`'s docstring says why) and is
    always supplied by the router, which is the one place in this slice allowed to probe it.
    """
    session_schema = session_detail_schema(view.session)
    return InstructorSessionOverviewSchema(
        session=session_schema,
        stages=session_schema.stages,
        world_truth=WorldTruthViewSchema(
            incident_id=UUID(str(view.world_truth.incident_id)),
            revision=view.world_truth.revision,
            facts=dict(view.world_truth.facts),
            value_types=dict(view.world_truth.value_types),
        ),
        caller_belief=CallerBeliefViewSchema(
            incident_id=UUID(str(view.caller_belief.incident_id)),
            revision=view.caller_belief.revision,
            facts=dict(view.caller_belief.facts),
            knowledge=dict(view.caller_belief.knowledge),
            certainty=dict(view.caller_belief.certainty),
            emotion=view.caller_belief.emotion.emotion,
            stress_level=view.caller_belief.emotion.stress_level,
            revealed_fact_ids=sorted(view.caller_belief.revealed_fact_ids),
        ),
        gate_turns=[_gate_turn_schema(entry) for entry in view.gate_turns],
        card=None if view.card is None else operator_card_schema(card_view(view.card)),
        handoff=(
            None
            if view.handoff is None
            else handoff_snapshot_schema(handoff_snapshot_view(view.handoff))
        ),
        assignments=[dds_work_item_schema(item) for item in view.assignments],
        resources=[resource_schema(item) for item in view.resources],
        call_state=call_state_schema(view.call_state),
        last_seq_no=view.last_seq_no,
        inference_health=inference_health,
    )
