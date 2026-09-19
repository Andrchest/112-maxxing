"""Domain <-> ORM row mapping (HLD `20-db-schema.md`, D2 "mapping … lives in
`backend/app/infrastructure/persistence/`").

Nothing here touches a database session: these are pure functions over domain objects and row
mappings, so they are cheap to test and impossible to misuse from the domain side.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.domain.caller.emotion import EmotionState
from app.domain.common.ids import (
    CardId,
    CardRevisionId,
    EventId,
    IncidentId,
    RoleStageId,
    ScenarioVersionId,
    SessionId,
    SnapshotId,
    UserId,
)
from app.domain.enums import (
    ActorType,
    ClosureReason,
    DDSStageState,
    KnowledgeState,
    Operator112StageState,
    RoleType,
    ServiceType,
    SessionMode,
    SessionState,
    ValueType,
)
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType
from app.domain.layers.caller_belief import CallerBelief
from app.domain.layers.handoff import HandoffSnapshot
from app.domain.layers.operator_card import OperatorCard
from app.domain.layers.world_truth import WorldTruth
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.rules import ScoringRule
from app.domain.session.session import (
    Incident,
    RoleStage,
    SessionParticipant,
    SimulationSession,
    StageState,
)

__all__ = [
    "caller_belief_from_row",
    "caller_belief_row_values",
    "event_row_values",
    "handoff_snapshot_from_row",
    "handoff_snapshot_row_values",
    "incident_from_row",
    "incident_row_values",
    "operator_card_from_row",
    "operator_card_row_values",
    "participant_from_row",
    "participant_row_values",
    "role_stage_from_row",
    "role_stage_row_values",
    "scenario_version_row_values",
    "scoring_rule_row_values",
    "session_event_from_row",
    "session_event_of",
    "session_from_rows",
    "session_row_values",
    "world_truth_from_row",
    "world_truth_row_values",
]


def scenario_version_row_values(
    scenario_version: ScenarioVersion,
    content: Mapping[str, Any],
    content_sha256: str,
    source_path: str | None = None,
) -> dict[str, Any]:
    """Column values for one `scenario_versions` row (§20.2)."""
    return {
        "id": UUID(str(scenario_version.id)),
        "scenario_id": UUID(str(scenario_version.scenario_id)),
        "version": scenario_version.version,
        "schema_version": scenario_version.schema_version,
        "title": scenario_version.title,
        "description": scenario_version.description,
        "difficulty": scenario_version.difficulty,
        "deterministic_seed": scenario_version.deterministic_seed,
        "role_chain": [role.value for role in scenario_version.role_chain],
        "content": dict(content),
        "content_sha256": content_sha256,
        "source_path": source_path,
    }


def scoring_rule_row_values(
    scenario_version_id: ScenarioVersionId, rules: Sequence[ScoringRule]
) -> list[dict[str, Any]]:
    """Column values for the `scoring_rules` projection of a version (§20.2).

    `order_index` is the rule's position in the scenario document: `scoring_rules` is a list in the
    YAML (SPEC §4) and the report renders the rules in the author's order.
    """
    return [
        {
            "scenario_version_id": UUID(str(scenario_version_id)),
            "rule_id": rule.rule_id,
            "name_ru": rule.name_ru,
            "description_ru": rule.description_ru,
            "category": rule.category.value,
            "max_points": rule.max_points,
            "critical": rule.critical,
            "evaluator_type": rule.evaluator_type.value,
            "config": dict(rule.config),
            "min_evidence": rule.min_evidence,
            "order_index": index,
        }
        for index, rule in enumerate(rules)
    ]


def event_row_values(
    session_id: SessionId,
    event: DomainEvent,
    seq_no: int,
    timestamp_utc: datetime,
    event_id: UUID | None = None,
) -> dict[str, Any]:
    """Column values for one `session_events` row (§20.6, SPEC §8).

    The id is generated here rather than by the server default so the caller gets the persisted
    `SessionEvent` back without a `RETURNING` round-trip. `timestamp_utc` is supplied by the
    caller, which takes it from the injected `Clock` — never from `datetime.now()` (D5).
    """
    return {
        "id": event_id if event_id is not None else uuid4(),
        "session_id": UUID(str(session_id)),
        "seq_no": seq_no,
        "event_type": event.event_type.value,
        "timestamp_utc": timestamp_utc,
        "monotonic_offset_ms": event.monotonic_offset_ms,
        "actor_type": event.actor.actor_type.value,
        "actor_id": UUID(str(event.actor.actor_id)) if event.actor.actor_id is not None else None,
        "correlation_id": event.correlation_id,
        "payload": dict(event.payload),
    }


def session_event_of(
    session_id: SessionId, event: DomainEvent, row_values: Mapping[str, Any]
) -> SessionEvent:
    """The persisted `SessionEvent` corresponding to `event_row_values(...)` output."""
    return SessionEvent(
        id=EventId(UUID(str(row_values["id"]))),
        session_id=session_id,
        seq_no=int(row_values["seq_no"]),
        event_type=event.event_type,
        timestamp_utc=row_values["timestamp_utc"],
        monotonic_offset_ms=event.monotonic_offset_ms,
        actor_type=event.actor.actor_type,
        actor_id=event.actor.actor_id,
        correlation_id=event.correlation_id,
        payload=dict(event.payload),
    )


def session_event_from_row(row: Mapping[str, Any]) -> SessionEvent:
    """Read one `session_events` row back into its domain type (§20.6)."""
    actor_id = row["actor_id"]
    return SessionEvent(
        id=EventId(UUID(str(row["id"]))),
        session_id=SessionId(UUID(str(row["session_id"]))),
        seq_no=int(row["seq_no"]),
        event_type=EventType(row["event_type"]),
        timestamp_utc=row["timestamp_utc"],
        monotonic_offset_ms=int(row["monotonic_offset_ms"]),
        actor_type=ActorType(row["actor_type"]),
        actor_id=UserId(UUID(str(actor_id))) if actor_id is not None else None,
        correlation_id=UUID(str(row["correlation_id"])) if row["correlation_id"] else None,
        payload=dict(row["payload"]),
    )


# ---------------------------------------------------------------------------------------------
# Session aggregate (§20.3)
# ---------------------------------------------------------------------------------------------


def session_row_values(session: SimulationSession) -> dict[str, Any]:
    """Column values for one `simulation_sessions` row (§20.3).

    `next_seq_no` is absent on purpose: the event store owns sequence allocation (§20.8) and the
    aggregate has no field for it, so neither an insert nor an update from here may write it.
    `created_at` is a storage default. `time_scale` becomes a `Decimal` because the column is
    `numeric(4, 2)`.
    """
    return {
        "id": UUID(str(session.id)),
        "scenario_version_id": UUID(str(session.scenario_version_id)),
        "session_mode": session.session_mode.value,
        "state": session.state.value,
        "session_seed": session.session_seed,
        "time_scale": Decimal(str(session.time_scale)),
        "created_by_user_id": UUID(str(session.created_by_user_id)),
        "started_at": session.started_at,
        "paused_total_ms": session.paused_total_ms,
        "completed_at": session.completed_at,
        "abort_reason": session.abort_reason,
    }


def incident_row_values(incident: Incident) -> dict[str, Any]:
    """Column values for one `incidents` row (§20.3)."""
    return {
        "id": UUID(str(incident.incident_id)),
        "session_id": UUID(str(incident.session_id)),
        "scenario_version_id": UUID(str(incident.scenario_version_id)),
        "created_at_offset_ms": incident.created_at_offset_ms,
        "closed_at_offset_ms": incident.closed_at_offset_ms,
        "closure_reason": (
            incident.closure_reason.value if incident.closure_reason is not None else None
        ),
    }


def role_stage_row_values(stage: RoleStage) -> dict[str, Any]:
    """Column values for one `role_stages` row (§20.3)."""
    return {
        "id": UUID(str(stage.role_stage_id)),
        "session_id": UUID(str(stage.session_id)),
        "incident_id": UUID(str(stage.incident_id)),
        "role_type": stage.role_type.value,
        "order_index": stage.order_index,
        "state": stage.state.value,
        "participant_user_id": (
            UUID(str(stage.participant_user_id)) if stage.participant_user_id is not None else None
        ),
        "started_at_offset_ms": stage.started_at_offset_ms,
        "completed_at_offset_ms": stage.completed_at_offset_ms,
    }


def participant_row_values(
    session_id: SessionId, participant: SessionParticipant
) -> dict[str, Any]:
    """Column values for one `session_participants` row (§20.3).

    `joined_at` is a storage default (`now()`) the pure domain cannot produce and no rule reads,
    so it is never written from here (E5-B ruling R3). `participant_id` is required: the creating
    use case allocates it from the `IdGenerator`, so every persisted participant has a stable id.
    """
    if participant.participant_id is None:
        raise ValueError(
            f"participant {participant.user_id} of session {session_id} has no participant_id: "
            "the use case must allocate one from the IdGenerator before persisting"
        )
    return {
        "id": participant.participant_id,
        "session_id": UUID(str(session_id)),
        "user_id": UUID(str(participant.user_id)),
        "assigned_role_type": (
            participant.assigned_role_type.value
            if participant.assigned_role_type is not None
            else None
        ),
    }


def session_from_rows(
    session_row: Mapping[str, Any],
    incident_row: Mapping[str, Any],
    stage_rows: Sequence[Mapping[str, Any]],
    participant_rows: Sequence[Mapping[str, Any]],
) -> SimulationSession:
    """Rebuild the aggregate from its four row sets (§20.3).

    `stage_rows` is ordered by `order_index` by the caller, which is the order
    `SimulationSession.stages` is documented to keep.
    """
    return SimulationSession(
        id=SessionId(UUID(str(session_row["id"]))),
        scenario_version_id=ScenarioVersionId(UUID(str(session_row["scenario_version_id"]))),
        session_mode=SessionMode(session_row["session_mode"]),
        state=SessionState(session_row["state"]),
        session_seed=session_row["session_seed"],
        time_scale=float(session_row["time_scale"]),
        created_by_user_id=UserId(UUID(str(session_row["created_by_user_id"]))),
        started_at=session_row["started_at"],
        paused_total_ms=int(session_row["paused_total_ms"]),
        completed_at=session_row["completed_at"],
        abort_reason=session_row["abort_reason"],
        incident=incident_from_row(incident_row),
        stages=tuple(role_stage_from_row(row) for row in stage_rows),
        participants=tuple(participant_from_row(row) for row in participant_rows),
    )


def incident_from_row(row: Mapping[str, Any]) -> Incident:
    """Read one `incidents` row back into its domain type (§20.3)."""
    closure_reason = row["closure_reason"]
    return Incident(
        incident_id=IncidentId(UUID(str(row["id"]))),
        session_id=SessionId(UUID(str(row["session_id"]))),
        scenario_version_id=ScenarioVersionId(UUID(str(row["scenario_version_id"]))),
        created_at_offset_ms=int(row["created_at_offset_ms"]),
        closed_at_offset_ms=row["closed_at_offset_ms"],
        closure_reason=None if closure_reason is None else ClosureReason(closure_reason),
    )


def role_stage_from_row(row: Mapping[str, Any]) -> RoleStage:
    """Read one `role_stages` row back into its domain type (§20.3).

    `state` carries either an `Operator112StageState` or a `DDSStageState` member (§20.3's CHECK
    is the union of both enums), so the member is resolved against the role's own enum.
    """
    role_type = RoleType(row["role_type"])
    participant_user_id = row["participant_user_id"]
    return RoleStage(
        role_stage_id=RoleStageId(UUID(str(row["id"]))),
        session_id=SessionId(UUID(str(row["session_id"]))),
        incident_id=IncidentId(UUID(str(row["incident_id"]))),
        role_type=role_type,
        order_index=int(row["order_index"]),
        state=_stage_state(role_type, row["state"]),
        participant_user_id=(
            None if participant_user_id is None else UserId(UUID(str(participant_user_id)))
        ),
        started_at_offset_ms=row["started_at_offset_ms"],
        completed_at_offset_ms=row["completed_at_offset_ms"],
    )


def participant_from_row(row: Mapping[str, Any]) -> SessionParticipant:
    """Read one `session_participants` row back into its domain type (§20.3)."""
    assigned_role_type = row["assigned_role_type"]
    return SessionParticipant(
        user_id=UserId(UUID(str(row["user_id"]))),
        assigned_role_type=None if assigned_role_type is None else RoleType(assigned_role_type),
        participant_id=UUID(str(row["id"])),
    )


def _stage_state(role_type: RoleType, value: str) -> StageState:
    """Resolve a `role_stages.state` string against the enum its `role_type` uses (§20.3)."""
    enum_type: type[Operator112StageState] | type[DDSStageState] = (
        Operator112StageState if role_type is RoleType.OPERATOR_112 else DDSStageState
    )
    return enum_type(value)


# ---------------------------------------------------------------------------------------------
# The four information layers (§20.4, D3)
# ---------------------------------------------------------------------------------------------


def world_truth_row_values(world_truth: WorldTruth) -> dict[str, Any]:
    """Column values for one `incident_world_states` row (§20.4)."""
    return {
        "incident_id": UUID(str(world_truth.incident_id)),
        "revision": world_truth.revision,
        "facts": dict(world_truth.facts),
        "value_types": {
            fact_id: value_type.value for fact_id, value_type in world_truth.value_types.items()
        },
    }


def world_truth_from_row(row: Mapping[str, Any]) -> WorldTruth:
    """Read one `incident_world_states` row back into its domain type (§20.4)."""
    return WorldTruth(
        incident_id=IncidentId(UUID(str(row["incident_id"]))),
        revision=int(row["revision"]),
        facts=dict(row["facts"]),
        value_types={
            fact_id: ValueType(value) for fact_id, value in dict(row["value_types"]).items()
        },
    )


def caller_belief_row_values(caller_belief: CallerBelief) -> dict[str, Any]:
    """Column values for one `incident_caller_beliefs` row (§20.4)."""
    return {
        "incident_id": UUID(str(caller_belief.incident_id)),
        "revision": caller_belief.revision,
        "facts": dict(caller_belief.facts),
        "knowledge": {fact_id: state.value for fact_id, state in caller_belief.knowledge.items()},
        "certainty": dict(caller_belief.certainty),
        "emotion": caller_belief.emotion.model_dump(mode="json"),
        "revealed_fact_ids": sorted(caller_belief.revealed_fact_ids),
    }


def caller_belief_from_row(row: Mapping[str, Any]) -> CallerBelief:
    """Read one `incident_caller_beliefs` row back into its domain type (§20.4)."""
    return CallerBelief(
        incident_id=IncidentId(UUID(str(row["incident_id"]))),
        revision=int(row["revision"]),
        facts=dict(row["facts"]),
        knowledge={
            fact_id: KnowledgeState(value) for fact_id, value in dict(row["knowledge"]).items()
        },
        certainty={fact_id: float(value) for fact_id, value in dict(row["certainty"]).items()},
        emotion=EmotionState.model_validate(row["emotion"]),
        revealed_fact_ids=frozenset(row["revealed_fact_ids"] or ()),
    )


def operator_card_row_values(card: OperatorCard) -> dict[str, Any]:
    """Column values for one `incident_cards` row (§20.4)."""
    return {
        "id": UUID(str(card.card_id)),
        "incident_id": UUID(str(card.incident_id)),
        "values": dict(card.values),
        "revision_counter": card.revision_counter,
    }


def operator_card_from_row(row: Mapping[str, Any]) -> OperatorCard:
    """Read one `incident_cards` row back into its domain type (§20.4)."""
    return OperatorCard(
        card_id=CardId(UUID(str(row["id"]))),
        incident_id=IncidentId(UUID(str(row["incident_id"]))),
        values=dict(row["values"]),
        revision_counter=int(row["revision_counter"]),
    )


def handoff_snapshot_row_values(snapshot: HandoffSnapshot) -> dict[str, Any]:
    """Column values for one `handoff_snapshots` row (§20.4, SPEC §10)."""
    return {
        "id": UUID(str(snapshot.snapshot_id)),
        "incident_id": UUID(str(snapshot.incident_id)),
        "card_id": UUID(str(snapshot.card_id)),
        "card_revision_id": UUID(str(snapshot.card_revision_id)),
        "card_values": dict(snapshot.card_values),
        "recipient_services": [service.value for service in snapshot.recipient_services],
        "content_sha256": snapshot.content_sha256,
        "created_by_user_id": UUID(str(snapshot.created_by_user_id)),
        "created_at_offset_ms": snapshot.created_at_offset_ms,
    }


def handoff_snapshot_from_row(row: Mapping[str, Any]) -> HandoffSnapshot:
    """Read one `handoff_snapshots` row back into its domain type (§20.4)."""
    return HandoffSnapshot(
        snapshot_id=SnapshotId(UUID(str(row["id"]))),
        incident_id=IncidentId(UUID(str(row["incident_id"]))),
        card_id=CardId(UUID(str(row["card_id"]))),
        card_revision_id=CardRevisionId(UUID(str(row["card_revision_id"]))),
        card_values=dict(row["card_values"]),
        recipient_services=tuple(ServiceType(value) for value in row["recipient_services"]),
        created_by_user_id=UserId(UUID(str(row["created_by_user_id"]))),
        created_at_offset_ms=int(row["created_at_offset_ms"]),
        content_sha256=row["content_sha256"],
    )
