"""Domain <-> ORM row mapping (HLD `20-db-schema.md`, D2 "mapping … lives in
`backend/app/infrastructure/persistence/`").

Nothing here touches a database session: these are pure functions over domain objects and row
mappings, so they are cheap to test and impossible to misuse from the domain side.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from app.domain.common.ids import EventId, ScenarioVersionId, SessionId, UserId
from app.domain.enums import ActorType
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.rules import ScoringRule

__all__ = [
    "event_row_values",
    "scenario_version_row_values",
    "scoring_rule_row_values",
    "session_event_from_row",
    "session_event_of",
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
