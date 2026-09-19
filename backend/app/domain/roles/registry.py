"""`ROLE_MODULES` (HLD `10-domain-model.md` §10.1, §10.9, SPEC §14, D6).

Built eagerly, at import time (ruling R5 of this task's brief — no PEP 562 lazy
module-level-attribute-access indirection). This module imports `roles/module.py` (for
`RoleModule`) and the three concrete `RoleModule` implementations; none of those import this
module back, so there is no import cycle to defer around.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.enums import RoleType
from app.domain.roles.dds import DDSModule
from app.domain.roles.edds import EDDSModule
from app.domain.roles.module import RoleModule
from app.domain.roles.operator112 import Operator112Module

ROLE_MODULES: Mapping[RoleType, RoleModule] = {
    RoleType.OPERATOR_112: Operator112Module(),
    RoleType.DDS: DDSModule(),
    RoleType.EDDS: EDDSModule(),
}
