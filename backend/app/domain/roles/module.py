"""`Permission`, `ActionDescriptor`, `RoleModule` (HLD `10-domain-model.md` §10.9, SPEC §14, D6).

`ROLE_MODULES` has moved to `roles/registry.py` (ruling R5 of this task's brief): this module
defines only the abstraction that `Operator112Module`/`DDSModule`/`EDDSModule` implement and that
`registry.py` imports back, which keeps the dependency one-directional (`registry -> {module,
operator112, dds, edds}`, never the reverse) and lets `ROLE_MODULES` be built eagerly at import
time instead of lazily through the PEP 562 module-level-attribute-access hook this module used to
rely on.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.domain.common.state_machine import StateMachine
from app.domain.enums import RoleType
from app.domain.roles.visibility import DataVisibilityPolicy


class Permission(str, Enum):
    """§10.9, exact."""

    ANSWER_CALL = "ANSWER_CALL"
    END_CALL = "END_CALL"
    EDIT_CARD = "EDIT_CARD"
    SELECT_SERVICES = "SELECT_SERVICES"
    CREATE_HANDOFF = "CREATE_HANDOFF"
    VIEW_HANDOFF = "VIEW_HANDOFF"
    ACKNOWLEDGE_ASSIGNMENT = "ACKNOWLEDGE_ASSIGNMENT"
    SELECT_RESOURCES = "SELECT_RESOURCES"
    DISPATCH_RESOURCES = "DISPATCH_RESOURCES"
    SEND_STATUS_UPDATE = "SEND_STATUS_UPDATE"
    CLOSE_INCIDENT = "CLOSE_INCIDENT"
    ACKNOWLEDGE_NOTIFICATION = "ACKNOWLEDGE_NOTIFICATION"
    VIEW_RESOURCE_BOARD = "VIEW_RESOURCE_BOARD"
    VIEW_TRANSCRIPT = "VIEW_TRANSCRIPT"


class ActionDescriptor(BaseModel):
    """§10.9. `trigger` is `None` for a non-transition command (e.g. `edit_card`)."""

    model_config = ConfigDict(frozen=True)

    action_id: str
    label_ru: str
    permission: Permission
    trigger: str | None = None


@runtime_checkable
class RoleModule(Protocol):
    """§10.9, D6. A registered `RoleModule` may have `implemented = False` (`EDDSModule`)."""

    role_type: RoleType
    implemented: bool
    permissions: frozenset[Permission]
    state_machine: StateMachine[Any]
    visibility_policy: DataVisibilityPolicy
    ui_schema: Mapping[str, Any]

    def available_actions(self, stage_state: Enum) -> tuple[ActionDescriptor, ...]: ...

    def initial_state(self) -> Enum: ...

    def terminal_states(self) -> frozenset[Enum]: ...
