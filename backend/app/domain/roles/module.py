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
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.domain.common.state_machine import StateMachine
from app.domain.enums import RoleType
from app.domain.roles.visibility import DataVisibilityPolicy

if TYPE_CHECKING:  # pragma: no cover - typing only; `roles` must not initialise `session` early
    from app.domain.session.variants import SessionVariants


class Permission(str, Enum):
    """§10.9, plus I3's two additive members (HLD 70 §70.4.4)."""

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
    # Additive, I3 E5a (HLD 70 §70.4.4): the leg triggers of the memo's pencil, and the card check.
    SET_SERVICE_STATUS = "SET_SERVICE_STATUS"
    FLAG_CARD_ISSUE = "FLAG_CARD_ISSUE"


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

    def available_actions(
        self, stage_state: Enum, *, variants: SessionVariants | None = None
    ) -> tuple[ActionDescriptor, ...]:
        """The actions of `stage_state`. `variants` is the session's (HLD 70 §70.2.4): `None`
        keeps today's behaviour, and a module whose actions no switch changes ignores it."""
        ...

    def state_machine_for(self, variants: SessionVariants | None = None) -> StateMachine[Any]:
        """The stage machine a session with `variants` runs (HLD 70 §70.2.4). `None` and every
        module no switch changes answer `state_machine`; `DDSModule` answers its memo machine
        for `dds_mode: MEMO_STATUSES` (I3 E5a)."""
        ...

    def initial_state(self) -> Enum: ...

    def terminal_states(self) -> frozenset[Enum]: ...
