"""`SERVICE_SELECTION` evaluator (HLD `10-domain-model.md` §10.14 #5, `30-scenario-format.md`
§30.7 example #5).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.enums import RoleType, ServiceType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scoring import evidence
from app.domain.scoring.context import ScoringContext
from app.domain.scoring.results import ScoreEvidence, ScoreResult
from app.domain.scoring.rules import ScoringRule

EvaluatedAt = Literal["HANDOFF", "SESSION_END"]


class ServiceSelectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required_services: tuple[ServiceType, ...]
    forbidden_services: tuple[ServiceType, ...] = ()
    points_per_required: float
    penalty_per_forbidden: float = 0.0
    all_or_nothing: bool = False
    evaluated_at: EvaluatedAt


def evaluate(
    rule: ScoringRule,
    config: ServiceSelectionConfig,
    ctx: ScoringContext,
) -> ScoreResult:
    """Were the right services addressed, and no wrong one? (§10.14 #5)

    At `evaluated_at: HANDOFF` the set is `HANDOFF_CREATED.recipient_services` — the frozen
    snapshot that actually went to the DDS, not what was on screen at some other moment. Without
    a handoff (a stage that never handed off) the set is folded from `SERVICE_SELECTED` /
    `SERVICE_DESELECTED` up to the cutoff, which is also what `SESSION_END` always uses.
    """
    cutoff = ctx.cutoff_seq_no(config.evaluated_at)
    selected, source = _selected_services(ctx, config.evaluated_at, cutoff)

    present = [service for service in config.required_services if service in selected]
    missing = [service for service in config.required_services if service not in selected]
    forbidden = [service for service in config.forbidden_services if service in selected]

    if config.all_or_nothing:
        earned = rule.max_points if not missing else 0.0
    else:
        earned = config.points_per_required * len(present)
    points = earned + config.penalty_per_forbidden * len(forbidden)
    passed = not missing and not forbidden

    items: list[ScoreEvidence] = []
    for service in present:
        items.append(_service_evidence(ctx, service, cutoff, source))
    for service in missing:
        items.append(evidence.from_event(source, f"Служба {service.value} не указана получателем."))
    for service in forbidden:
        items.append(evidence.from_event(source, f"Указана недопустимая служба {service.value}."))
    if not items:
        items.append(evidence.from_event(source, "Правило не назвало ни одной службы."))
    return evidence.result(rule, points=points, passed=passed, evidence=items)


def _selected_services(
    ctx: ScoringContext,
    evaluated_at: EvaluatedAt,
    cutoff: int,
) -> tuple[frozenset[ServiceType], SessionEvent]:
    """The service set at the cutoff, and the event that is the source of record for it."""
    handoff = ctx.handoff_event
    if evaluated_at == "HANDOFF" and handoff is not None:
        raw = handoff.payload.get("recipient_services")
        services = _as_services(raw)
        return services, handoff

    selected: set[ServiceType] = set()
    for event in ctx.of_type(EventType.SERVICE_SELECTED) + ctx.of_type(
        EventType.SERVICE_DESELECTED
    ):
        if event.seq_no > cutoff:
            continue
        service = _one_service(event.payload.get("service_type"))
        if service is None:
            continue
        if event.event_type is EventType.SERVICE_SELECTED:
            selected.add(service)
        else:
            selected.discard(service)
    bound = handoff if handoff is not None else evidence.bounding_event(ctx, RoleType.OPERATOR_112)
    return frozenset(selected), bound


def _service_evidence(
    ctx: ScoringContext,
    service: ServiceType,
    cutoff: int,
    fallback: SessionEvent,
) -> ScoreEvidence:
    """The `SERVICE_SELECTED` that put `service` on the card, else the source of record."""
    for event in reversed(ctx.of_type(EventType.SERVICE_SELECTED)):
        if event.seq_no > cutoff:
            continue
        if _one_service(event.payload.get("service_type")) is service:
            return evidence.from_event(event, f"Служба {service.value} выбрана оператором.")
    return evidence.from_event(fallback, f"Служба {service.value} указана получателем.")


def _as_services(raw: object) -> frozenset[ServiceType]:
    if not isinstance(raw, list | tuple):
        return frozenset()
    found = {_one_service(item) for item in raw}
    return frozenset(service for service in found if service is not None)


def _one_service(raw: object) -> ServiceType | None:
    if isinstance(raw, ServiceType):
        return raw
    if isinstance(raw, str):
        try:
            return ServiceType(raw)
        except ValueError:
            return None
    return None
