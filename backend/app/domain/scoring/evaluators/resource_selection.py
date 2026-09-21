"""`RESOURCE_SELECTION` evaluator (HLD `10-domain-model.md` §10.14 #8,
`30-scenario-format.md` §30.7 example #8).

`required_capabilities` is typed `tuple[ResourceCapability, ...]` against the enum defined in
`app/domain/dds/resources.py` (HLD §10.7), which now exists: the config therefore rejects a
capability the domain does not know, instead of accepting any string. The wire representation is
unchanged (`ResourceCapability` is a `str` enum whose member name is its value).
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from app.domain.dds.resources import ResourceCapability
from app.domain.enums import RoleType, ServiceType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scoring import evidence
from app.domain.scoring.context import DispatchedUnit, ScoringContext, SelectedUnit
from app.domain.scoring.results import ScoreEvidence, ScoreResult
from app.domain.scoring.rules import ScoringRule


class ResourceSelectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required_capabilities: tuple[ResourceCapability, ...] = ()
    min_units_by_service: Mapping[ServiceType, int]
    forbidden_resource_ids: tuple[str, ...] = ()
    must_be_dispatched: bool = True
    points: float
    penalty_per_missing: float = 0.0
    penalty_per_forbidden: float = 0.0


def evaluate(
    rule: ScoringRule,
    config: ResourceSelectionConfig,
    ctx: ScoringContext,
) -> ScoreResult:
    """Were the right forces sent? (§10.14 #8)

    A unit's service comes from `RESOURCE_DISPATCHED.service_type_by_resource` — the unit's own
    service, per unit — and never from its assignment leg: an off-service unit attaches to the
    primary leg, so `assignment_id` does not imply a service (`application/dds/leg_for.py`).
    Dispatching an off-service unit is allowed; it simply does not count towards another
    service's minimum.
    """
    units = _units(ctx, config)
    covered = _capabilities(ctx, config, units)
    counts = _counts_by_service(units)

    missing_capabilities = [
        capability for capability in config.required_capabilities if capability.value not in covered
    ]
    shortfalls = [
        (service, minimum, counts.get(service, 0))
        for service, minimum in sorted(config.min_units_by_service.items(), key=_service_key)
        if counts.get(service, 0) < minimum
    ]
    forbidden = [unit for unit in units if unit.resource_id in set(config.forbidden_resource_ids)]

    unmet = len(missing_capabilities) + sum(minimum - actual for _, minimum, actual in shortfalls)
    earned = config.points if unmet == 0 else config.penalty_per_missing * unmet
    points = earned + config.penalty_per_forbidden * len(forbidden)
    passed = unmet == 0 and not forbidden

    items = _evidence(ctx, units, missing_capabilities, shortfalls, forbidden)
    return evidence.result(rule, points=points, passed=passed, evidence=items)


_Unit = DispatchedUnit | SelectedUnit


def _units(ctx: ScoringContext, config: ResourceSelectionConfig) -> tuple[_Unit, ...]:
    if config.must_be_dispatched:
        return tuple(ctx.dispatched_units)
    return tuple(ctx.selected_units)


def _capabilities(
    ctx: ScoringContext,
    config: ResourceSelectionConfig,
    units: tuple[_Unit, ...],
) -> frozenset[str]:
    """What the sent units can do, from the units plus `RESOURCE_DISPATCHED.capabilities_union`.

    §10.14 #8 states the payload "carries `capabilities_union` and `service_type` per resource, so
    no resource table lookup is needed". `capabilities_union` is a union over the dispatch, which
    is exactly what a "required capability is covered" test needs; the per-unit sets come from
    `RESOURCE_SELECTED.capabilities` and cover the `must_be_dispatched: false` case.
    """
    covered: set[str] = set()
    for unit in units:
        covered |= unit.capabilities
    if config.must_be_dispatched:
        covered |= ctx.dispatched_capabilities
    return frozenset(covered)


def _counts_by_service(units: tuple[_Unit, ...]) -> Mapping[ServiceType, int]:
    counts: dict[ServiceType, int] = {}
    for unit in units:
        if unit.service_type is not None:
            counts[unit.service_type] = counts.get(unit.service_type, 0) + 1
    return counts


def _service_key(item: tuple[ServiceType, int]) -> str:
    return item[0].value


def _evidence(
    ctx: ScoringContext,
    units: tuple[_Unit, ...],
    missing_capabilities: list[ResourceCapability],
    shortfalls: list[tuple[ServiceType, int, int]],
    forbidden: list[_Unit],
) -> list[ScoreEvidence]:
    items: list[ScoreEvidence] = []
    seen: set[int] = set()
    for unit in units:
        if unit.event.seq_no in seen:
            continue
        seen.add(unit.event.seq_no)
        items.append(
            evidence.from_event(
                unit.event,
                f"Направлены силы: {unit.resource_id} "
                f"({unit.service_type.value if unit.service_type else 'служба не указана'}).",
            )
        )
    if not (missing_capabilities or shortfalls or not items):
        for unit in forbidden:
            items.append(
                evidence.from_event(
                    unit.event, f"Направлена запрещённая единица {unit.resource_id}."
                )
            )
        return items

    absence = _absence_bound(ctx)
    for capability in missing_capabilities:
        items.append(
            evidence.from_event(absence, f"Нет возможности {capability.value} среди направленных.")
        )
    for service, minimum, actual in shortfalls:
        items.append(
            evidence.from_event(
                absence,
                f"Служба {service.value}: направлено {actual} из требуемых {minimum}.",
            )
        )
    for unit in forbidden:
        items.append(
            evidence.from_event(unit.event, f"Направлена запрещённая единица {unit.resource_id}.")
        )
    if not items:
        items.append(evidence.from_event(absence, "Силы не направлялись."))
    return items


def _absence_bound(ctx: ScoringContext) -> SessionEvent:
    """`DDS_INCIDENT_CLOSED`, else the bounding stage event (§10.14 #8)."""
    closed = ctx.first_of_type(EventType.DDS_INCIDENT_CLOSED)
    if closed is not None:
        return closed
    return evidence.bounding_event(ctx, RoleType.DDS)
