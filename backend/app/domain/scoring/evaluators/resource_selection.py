"""`RESOURCE_SELECTION` evaluator config (HLD `10-domain-model.md` §10.14 #8,
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
from app.domain.enums import ServiceType


class ResourceSelectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required_capabilities: tuple[ResourceCapability, ...] = ()
    min_units_by_service: Mapping[ServiceType, int]
    forbidden_resource_ids: tuple[str, ...] = ()
    must_be_dispatched: bool = True
    points: float
    penalty_per_missing: float = 0.0
    penalty_per_forbidden: float = 0.0


# TODO(E15): evaluate(...) for RESOURCE_SELECTION (HLD 10.14)
