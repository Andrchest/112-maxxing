"""Domain <-> ORM row mapping (HLD `20-db-schema.md`, D2 "mapping … lives in
`backend/app/infrastructure/persistence/`").

Nothing here touches a database session: these are pure functions over domain objects and row
mappings, so they are cheap to test and impossible to misuse from the domain side.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from app.application.ports.notification_repository import StoredNotification
from app.application.ports.report_explanation_repository import (
    EXPLANATION_AUDIENCES,
    ExplanationAudience,
    StoredReportExplanation,
)
from app.application.ports.resource_repository import ResourceStateChange, StoredResource
from app.application.ports.world_engine_state_repository import WorldEngineState
from app.domain.caller.emotion import EmotionState
from app.domain.common.actors import ActorRef
from app.domain.common.ids import (
    AssignmentId,
    CardId,
    CardRevisionId,
    EventId,
    IncidentId,
    ResourceId,
    RoleStageId,
    ScenarioVersionId,
    SessionId,
    SnapshotId,
    UserId,
)
from app.domain.dds.assignment import DDSAssignment
from app.domain.dds.resources import (
    EmergencyResource,
    EtaProfile,
    ResourceAvailability,
    ResourceCapability,
)
from app.domain.enums import (
    ActorType,
    ClosureReason,
    DDSStageState,
    EvaluatorType,
    KnowledgeState,
    NotificationSeverity,
    Operator112StageState,
    ResourceStatus,
    ResourceType,
    RoleType,
    ScoringCategory,
    ServiceType,
    SessionMode,
    SessionState,
    ValueType,
)
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType
from app.domain.layers.caller_belief import CallerBelief
from app.domain.layers.handoff import HandoffSnapshot
from app.domain.layers.operator_card import CardRevision, OperatorCard
from app.domain.layers.world_truth import WorldTruth
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.results import ScoreEvidence, ScoreResult
from app.domain.scoring.rules import ScoringRule
from app.domain.session.session import (
    Incident,
    RoleStage,
    SessionParticipant,
    SimulationSession,
    StageState,
)
from app.domain.session.variants import variants_payload
from app.domain.world.engine import ScheduledTrigger

__all__ = [
    "caller_belief_from_row",
    "caller_belief_row_values",
    "card_revision_from_row",
    "card_revision_row_values",
    "emergency_resource_from_row",
    "emergency_resource_row_values",
    "event_row_values",
    "handoff_snapshot_from_row",
    "handoff_snapshot_row_values",
    "incident_from_row",
    "incident_row_values",
    "json_safe_payload",
    "notification_from_row",
    "notification_row_values",
    "operator_card_from_row",
    "operator_card_row_values",
    "participant_from_row",
    "participant_row_values",
    "report_explanation_from_row",
    "report_explanation_row_values",
    "resource_state_change_row_values",
    "role_stage_from_row",
    "role_stage_row_values",
    "scenario_version_row_values",
    "score_evidence_row_values",
    "score_result_from_row",
    "score_result_row_values",
    "scoring_rule_row_values",
    "session_event_from_row",
    "session_event_of",
    "session_from_rows",
    "session_row_values",
    "world_engine_state_from_row",
    "world_engine_state_row_values",
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
            "applies_to_roles": [role.value for role in rule.applies_to_roles],
            "applies_to_variants": {
                switch: list(values) for switch, values in rule.applies_to_variants.items()
            },
        }
        for index, rule in enumerate(rules)
    ]


def score_result_row_values(
    result_id: UUID,
    session_id: SessionId,
    scenario_version_id: ScenarioVersionId,
    result: ScoreResult,
) -> dict[str, Any]:
    """Column values for one `score_results` row (§20.7).

    `result_id` is generated by the caller (`uuid4()`, same reasoning as `event_row_values`): the
    matching `score_evidence` rows need it before the insert, so a `RETURNING` round-trip would
    only give it back later than it is needed.
    """
    return {
        "id": result_id,
        "session_id": UUID(str(session_id)),
        "scenario_version_id": UUID(str(scenario_version_id)),
        "rule_id": result.rule_id,
        "evaluator_type": result.evaluator_type.value,
        "category": result.category.value,
        "points_awarded": result.points_awarded,
        "max_points": result.max_points,
        "passed": result.passed,
        "critical_failure": result.critical_failure,
    }


def score_evidence_row_values(
    evidence_id: UUID, score_result_id: UUID, evidence: ScoreEvidence
) -> dict[str, Any]:
    """Column values for one `score_evidence` row (§20.7): the three references exactly as the
    domain object has them — the `exactly_one` CHECK is satisfied because `ScoreEvidence` already
    enforces it (`app.domain.scoring.results`)."""
    return {
        "id": evidence_id,
        "score_result_id": score_result_id,
        "session_event_id": (
            UUID(str(evidence.event_id)) if evidence.event_id is not None else None
        ),
        "card_revision_id": (
            UUID(str(evidence.card_revision_id)) if evidence.card_revision_id is not None else None
        ),
        "snapshot_id": (
            UUID(str(evidence.snapshot_id)) if evidence.snapshot_id is not None else None
        ),
        "seq_no": evidence.seq_no,
        "note_ru": evidence.note_ru,
    }


def score_result_from_row(
    row: Mapping[str, Any], evidence_rows: Sequence[Mapping[str, Any]]
) -> ScoreResult:
    """One stored `score_results` row plus its `score_evidence` rows, back into a `ScoreResult`.

    `points_awarded` / `max_points` come back from PostgreSQL as `decimal.Decimal`
    (`numeric(8,2)`); both are cast to `float` here, once, so every comparison downstream
    (`rescoreSession`'s equality check, R10) is `float == float`.
    """
    return ScoreResult(
        rule_id=str(row["rule_id"]),
        evaluator_type=EvaluatorType(row["evaluator_type"]),
        category=ScoringCategory(row["category"]),
        points_awarded=float(row["points_awarded"]),
        max_points=float(row["max_points"]),
        passed=bool(row["passed"]),
        critical_failure=bool(row["critical_failure"]),
        evidence=tuple(_score_evidence_from_row(evidence_row) for evidence_row in evidence_rows),
    )


def _score_evidence_from_row(row: Mapping[str, Any]) -> ScoreEvidence:
    return ScoreEvidence(
        event_id=EventId(row["session_event_id"]) if row["session_event_id"] is not None else None,
        card_revision_id=(
            CardRevisionId(row["card_revision_id"]) if row["card_revision_id"] is not None else None
        ),
        snapshot_id=SnapshotId(row["snapshot_id"]) if row["snapshot_id"] is not None else None,
        seq_no=row["seq_no"],
        note_ru=str(row["note_ru"]),
    )


def json_safe_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Render every `UUID` in an event payload as its canonical string, at any depth.

    `session_events.payload` is `jsonb`, and the pure domain legitimately puts identifier *objects*
    in a payload: `world/apply.py` emits `RESOURCE_STATUS_CHANGED.resource_id` as a `ResourceId`
    and derives the notification/radio ids with `uuid5`. §10.13 types those keys `"uuid"`, which at
    rest is a JSON string, so this is the conversion — and it lives here, at the one
    `DomainEvent` -> row boundary every producer shares, rather than in any single use case.

    It is applied by `event_row_values`, and `session_event_of` reads the result back out of the
    row values, so the inserted row, the `SessionEvent` the event store returns and the envelope
    the Unit of Work publishes after commit all carry the *same* JSON-safe payload (§20.8, §40.6).
    """
    return {key: _json_value(value) for key, value in payload.items()}


def _json_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    return value


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
        "payload": json_safe_payload(event.payload),
    }


def session_event_of(
    session_id: SessionId, event: DomainEvent, row_values: Mapping[str, Any]
) -> SessionEvent:
    """The persisted `SessionEvent` corresponding to `event_row_values(...)` output.

    The payload is taken from `row_values`, not from `event`, so it is byte-identical to the one
    that goes into the row — `UUID`s already rendered as canonical strings (`json_safe_payload`).
    """
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
        payload=dict(row_values["payload"]),
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
    `numeric(4, 2)`. `variants` is written once, at insert; the update path never touches it
    (`_MUTABLE_SESSION_COLUMNS`), since variants are immutable after creation (HLD 70 §70.2.2).
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
        "role_transition_started_offset_ms": session.role_transition_started_offset_ms,
        "completed_at": session.completed_at,
        "abort_reason": session.abort_reason,
        "variants": variants_payload(session.variants),
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
        role_transition_started_offset_ms=(
            None
            if session_row["role_transition_started_offset_ms"] is None
            else int(session_row["role_transition_started_offset_ms"])
        ),
        completed_at=session_row["completed_at"],
        abort_reason=session_row["abort_reason"],
        # `'{}'` (a session created before E1) leaves the field out, and the aggregate fills in
        # the schema-1 derivation of its own stage chain (HLD 70 §70.2.2).
        variants=session_row["variants"] or None,
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


def card_revision_row_values(revision: CardRevision, value_type: ValueType) -> dict[str, Any]:
    """Column values for one `incident_card_revisions` row (§20.4, SPEC §9).

    `value_type` is a column of the row but not a field of the pure `CardRevision`: it comes from
    the `CARD_FIELDS` spec the writing use case already resolved. `actor_type` is constrained by
    the table's own CHECK to `TRAINEE`/`INSTRUCTOR` (§42 test 4), which is why the domain's
    `set_field` refuses every other actor before a row can reach this function.

    `session_event_id` is left `NULL`: the `CARD_FIELD_CHANGED` row's id is allocated by the event
    store in the *same* transaction, and threading it back here would make the revision write
    depend on the append order. The link exists the other way round — the event payload carries
    `revision_id` — and E16 confirmed that is enough: the post-session report joins evidence the
    other way round (`score_evidence.card_revision_id` names the revision directly, and the
    `CARD_FIELD_CHANGED` that produced it is found through that event's own `revision_id` key), so
    nothing reads the forward column and it stays `NULL`.
    """
    return {
        "id": UUID(str(revision.revision_id)),
        "card_id": UUID(str(revision.card_id)),
        "revision_no": revision.revision_no,
        "field_path": revision.field_path,
        "previous_value": revision.previous_value,
        "new_value": revision.new_value,
        "value_type": value_type.value,
        "actor_type": revision.actor.actor_type.value,
        "actor_user_id": (
            None if revision.actor.actor_id is None else UUID(str(revision.actor.actor_id))
        ),
        "at_offset_ms": revision.at_offset_ms,
        "session_event_id": None,
    }


def card_revision_from_row(row: Mapping[str, Any]) -> CardRevision:
    """Read one `incident_card_revisions` row back into its domain type (§20.4)."""
    actor_user_id = row["actor_user_id"]
    return CardRevision(
        revision_id=CardRevisionId(UUID(str(row["id"]))),
        card_id=CardId(UUID(str(row["card_id"]))),
        revision_no=int(row["revision_no"]),
        field_path=row["field_path"],
        previous_value=row["previous_value"],
        new_value=row["new_value"],
        actor=ActorRef(
            actor_type=ActorType(row["actor_type"]),
            actor_id=None if actor_user_id is None else UserId(UUID(str(actor_user_id))),
        ),
        at_offset_ms=int(row["at_offset_ms"]),
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


# ---------------------------------------------------------------------------------------------
# Resources and the world engine's bookkeeping (§20.5, E6)
# ---------------------------------------------------------------------------------------------


def emergency_resource_row_values(session_id: SessionId, stored: StoredResource) -> dict[str, Any]:
    """Column values for one `emergency_resources` row (§20.5).

    `assignment_id` is written here only because scenario instantiation inserts the whole board at
    once and a fresh board has none; after that the column belongs to the DDS selection use case
    and is written by `ResourceRepository.attach` alone, never by the engine's `save`.
    """
    resource = stored.resource
    return {
        "id": UUID(str(resource.resource_id)),
        "session_id": UUID(str(session_id)),
        "scenario_resource_id": stored.scenario_resource_id,
        "service_type": resource.service_type.value,
        "resource_type": resource.resource_type.value,
        "callsign": resource.callsign,
        "name_ru": resource.name_ru,
        "capabilities": sorted(capability.value for capability in resource.capabilities),
        "current_status": resource.current_status.value,
        "home_station_ru": resource.home_station_ru,
        "crew_size": resource.crew_size,
        "availability": resource.availability.model_dump(mode="json"),
        "eta": resource.eta.model_dump(mode="json"),
        "status_changed_at_offset_ms": resource.status_changed_at_offset_ms,
        "assignment_id": (
            None if stored.assignment_id is None else UUID(str(stored.assignment_id))
        ),
    }


def emergency_resource_from_row(row: Mapping[str, Any]) -> StoredResource:
    """Read one `emergency_resources` row back into its domain type plus its scenario id (§20.5)."""
    raw_assignment = row.get("assignment_id")
    return StoredResource(
        scenario_resource_id=row["scenario_resource_id"],
        assignment_id=(None if raw_assignment is None else AssignmentId(UUID(str(raw_assignment)))),
        resource=EmergencyResource(
            resource_id=ResourceId(UUID(str(row["id"]))),
            service_type=ServiceType(row["service_type"]),
            resource_type=ResourceType(row["resource_type"]),
            callsign=row["callsign"],
            name_ru=row["name_ru"],
            capabilities=frozenset(
                ResourceCapability(value) for value in (row["capabilities"] or ())
            ),
            current_status=ResourceStatus(row["current_status"]),
            availability=ResourceAvailability.model_validate(row["availability"]),
            eta=EtaProfile.model_validate(row["eta"]),
            home_station_ru=row["home_station_ru"],
            crew_size=int(row["crew_size"]),
            status_changed_at_offset_ms=int(row["status_changed_at_offset_ms"]),
        ),
    )


def resource_state_change_row_values(change: ResourceStateChange) -> dict[str, Any]:
    """Column values for one `resource_state_changes` row (§20.5, SPEC §29).

    `assignment_id` is the DDS leg the unit hung on when the transition fired, and
    `session_event_id` is the `session_events` row of the `RESOURCE_STATUS_CHANGED` that records
    it: the caller appends its events first, then writes these rows with the allocated ids, all
    inside one transaction (D5). Both stay `None` for a change nobody could attribute — an
    unattached unit, or a transition fired outside an event append.
    """
    return {
        "resource_id": UUID(str(change.resource.resource_id)),
        "assignment_id": (
            None if change.assignment_id is None else UUID(str(change.assignment_id))
        ),
        "session_event_id": change.session_event_id,
        "previous_status": (
            change.previous_status.value if change.previous_status is not None else None
        ),
        "new_status": change.new_status.value,
        "trigger": change.trigger,
        "source_world_event_id": change.source_world_event_id,
        "at_offset_ms": change.at_offset_ms,
    }


# ---------------------------------------------------------------------------------------------
# DDS assignments (§20.5, §10.7)
# ---------------------------------------------------------------------------------------------


def dds_assignment_row_values(assignment: DDSAssignment) -> dict[str, Any]:
    """Column values for one `dds_assignments` row — one leg of a DDS work item (§20.5).

    `selected_resource_ids` and `dispatched_resource_ids` are absent: §20.5 gives the table no
    column for either (analyst §7 #7). They are projections over `emergency_resources` /
    `resource_state_changes` and are filled by the slice that owns those tables.
    """
    return {
        "id": UUID(str(assignment.assignment_id)),
        "incident_id": UUID(str(assignment.incident_id)),
        "role_stage_id": UUID(str(assignment.role_stage_id)),
        "snapshot_id": UUID(str(assignment.snapshot_id)),
        "service_type": assignment.service_type.value,
        "state": assignment.state.value,
        "received_at_offset_ms": assignment.received_at_offset_ms,
        "acknowledged_at_offset_ms": assignment.acknowledged_at_offset_ms,
        "dispatched_at_offset_ms": assignment.dispatched_at_offset_ms,
        "closed_at_offset_ms": assignment.closed_at_offset_ms,
        "closure_reason": (
            assignment.closure_reason.value if assignment.closure_reason is not None else None
        ),
    }


def dds_assignment_from_row(row: Mapping[str, Any]) -> DDSAssignment:
    """Read one `dds_assignments` row back into its domain type (§20.5).

    The two resource-id tuples come back empty for the reason `dds_assignment_row_values` states.
    """
    closure_reason = row["closure_reason"]
    return DDSAssignment(
        assignment_id=AssignmentId(UUID(str(row["id"]))),
        incident_id=IncidentId(UUID(str(row["incident_id"]))),
        role_stage_id=RoleStageId(UUID(str(row["role_stage_id"]))),
        snapshot_id=SnapshotId(UUID(str(row["snapshot_id"]))),
        service_type=ServiceType(row["service_type"]),
        state=DDSStageState(row["state"]),
        received_at_offset_ms=int(row["received_at_offset_ms"]),
        acknowledged_at_offset_ms=_optional_int(row["acknowledged_at_offset_ms"]),
        dispatched_at_offset_ms=_optional_int(row["dispatched_at_offset_ms"]),
        closed_at_offset_ms=_optional_int(row["closed_at_offset_ms"]),
        closure_reason=None if closure_reason is None else ClosureReason(closure_reason),
    )


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


# ---------------------------------------------------------------------------------------------
# Notifications (§20.5 additive, §10.7)
# ---------------------------------------------------------------------------------------------


def notification_row_values(notification: StoredNotification) -> dict[str, Any]:
    """Column values for one `notifications` row (§20.5, additive per D5)."""
    return {
        "id": notification.notification_id,
        "incident_id": UUID(str(notification.incident_id)),
        "audience_role": notification.audience_role.value,
        "severity": notification.severity.value,
        "title_ru": notification.title_ru,
        "body_ru": notification.body_ru,
        "source_world_event_id": notification.source_world_event_id,
        "created_at_offset_ms": notification.created_at_offset_ms,
        "acknowledged_at_offset_ms": notification.acknowledged_at_offset_ms,
        "acknowledged_by_user_id": (
            None
            if notification.acknowledged_by_user_id is None
            else UUID(str(notification.acknowledged_by_user_id))
        ),
    }


def notification_from_row(row: Mapping[str, Any]) -> StoredNotification:
    """Read one `notifications` row back into its application type (§20.5)."""
    acknowledged_by = row["acknowledged_by_user_id"]
    return StoredNotification(
        notification_id=UUID(str(row["id"])),
        incident_id=IncidentId(UUID(str(row["incident_id"]))),
        audience_role=RoleType(row["audience_role"]),
        severity=NotificationSeverity(row["severity"]),
        title_ru=row["title_ru"],
        body_ru=row["body_ru"],
        source_world_event_id=row["source_world_event_id"],
        created_at_offset_ms=int(row["created_at_offset_ms"]),
        acknowledged_at_offset_ms=_optional_int(row["acknowledged_at_offset_ms"]),
        acknowledged_by_user_id=(
            None if acknowledged_by is None else UserId(UUID(str(acknowledged_by)))
        ),
    )


def world_engine_state_row_values(state: WorldEngineState) -> dict[str, Any]:
    """Column values for one `world_engine_states` row (additive, E6).

    The five bookkeeping members travel as one jsonb document, because their keys are
    scenario-defined (`world_event_id`s, emotion rule ids) and have no fixed column set — the same
    reason §20.4 gives for its own jsonb columns.
    """
    return {
        "incident_id": UUID(str(state.incident_id)),
        "last_tick_ms": state.last_tick_ms,
        "last_folded_seq_no": state.last_folded_seq_no,
        "bookkeeping": {
            "occurrences": dict(state.occurrences),
            "last_fired_ms": dict(state.last_fired_ms),
            "scheduled": [trigger.model_dump(mode="json") for trigger in state.scheduled],
            "emotion_applications": dict(state.emotion_applications),
            "reached_states": {
                role.value: sorted(states) for role, states in state.reached_states.items()
            },
        },
    }


def world_engine_state_from_row(row: Mapping[str, Any]) -> WorldEngineState:
    """Read one `world_engine_states` row back into its application type (additive, E6)."""
    bookkeeping: Mapping[str, Any] = dict(row["bookkeeping"] or {})
    return WorldEngineState(
        incident_id=IncidentId(UUID(str(row["incident_id"]))),
        last_tick_ms=int(row["last_tick_ms"]),
        last_folded_seq_no=int(row["last_folded_seq_no"]),
        occurrences={
            key: int(value) for key, value in (bookkeeping.get("occurrences") or {}).items()
        },
        last_fired_ms={
            key: int(value) for key, value in (bookkeeping.get("last_fired_ms") or {}).items()
        },
        scheduled=tuple(
            ScheduledTrigger.model_validate(entry) for entry in (bookkeeping.get("scheduled") or ())
        ),
        emotion_applications={
            key: int(value)
            for key, value in (bookkeeping.get("emotion_applications") or {}).items()
        },
        reached_states={
            RoleType(role): frozenset(states)
            for role, states in (bookkeeping.get("reached_states") or {}).items()
        },
    )


def report_explanation_row_values(explanation: StoredReportExplanation) -> dict[str, Any]:
    """Column values for one `report_explanations` row (§20.10, additive per E16)."""
    return {
        "id": explanation.id,
        "session_id": UUID(str(explanation.session_id)),
        "audience": explanation.audience,
        "text_ru": explanation.text_ru,
        "generated_at": explanation.generated_at,
        "llm_provider": explanation.llm_provider,
        "llm_model": explanation.llm_model,
        "score_report_checksum": explanation.score_report_checksum,
    }


def report_explanation_from_row(row: Mapping[str, Any]) -> StoredReportExplanation:
    """Read one `report_explanations` row back into its application type (§20.10)."""
    audience = str(row["audience"])
    if audience not in EXPLANATION_AUDIENCES:  # pragma: no cover - the CHECK constraint holds
        raise ValueError(f"unknown explanation audience {audience!r}")
    return StoredReportExplanation(
        id=UUID(str(row["id"])),
        session_id=SessionId(UUID(str(row["session_id"]))),
        audience=cast("ExplanationAudience", audience),
        text_ru=row["text_ru"],
        generated_at=row["generated_at"],
        llm_provider=row["llm_provider"],
        llm_model=row["llm_model"],
        score_report_checksum=row["score_report_checksum"],
    )
