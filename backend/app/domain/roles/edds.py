"""`EDDSModule` (HLD `10-domain-model.md` §10.9, SPEC §14) — the extension stub.

Registered in `ROLE_MODULES` so the extension point exists; `implemented = False` means
`validate_scenario_version` (a later slice, `domain/scenario/validation.py`) must reject any
`role_chain` containing `EDDS` (D6).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import TYPE_CHECKING, Any

from app.domain.common.state_machine import StateMachine
from app.domain.enums import DDSStageState, RoleType
from app.domain.events.types import EventType
from app.domain.roles.module import ActionDescriptor, Permission
from app.domain.roles.visibility import DataVisibilityPolicy, VisibilitySource

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.domain.session.variants import SessionVariants


class EDDSModule:
    """§10.9 `EDDSModule` stub: no permissions, no actions, a single-state machine over
    `DDSStageState.RECEIVED` with no transitions."""

    role_type: RoleType = RoleType.EDDS
    implemented: bool = False
    ui_schema: Mapping[str, Any] = {}

    def __init__(self) -> None:
        self.permissions: frozenset[Permission] = frozenset()
        self.state_machine: StateMachine[DDSStageState] = StateMachine({}, {})
        self.visibility_policy = DataVisibilityPolicy(
            role_type=RoleType.EDDS,
            sources=frozenset({VisibilitySource.NOTIFICATIONS, VisibilitySource.RADIO_MESSAGES}),
            visible_event_types=frozenset(
                {
                    EventType.NOTIFICATION_CREATED,
                    EventType.NOTIFICATION_ACKNOWLEDGED,
                    EventType.RADIO_MESSAGE_CREATED,
                }
            ),
        )

    def available_actions(
        self, stage_state: Enum, *, variants: SessionVariants | None = None
    ) -> tuple[ActionDescriptor, ...]:
        return ()

    def initial_state(self) -> Enum:
        return DDSStageState.RECEIVED

    def terminal_states(self) -> frozenset[Enum]:
        return frozenset()
