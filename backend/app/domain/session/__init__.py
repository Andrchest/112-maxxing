"""Session-level domain types (HLD `10-domain-model.md` §10.8, §10.10): the session aggregate
(`session.py`), the three transition tables (`transitions.py`), their guard callables
(`guards.py`), the session state machine (`machine.py`) and `SessionPolicy` (`policy.py`).

The names below are re-exported so callers may write either `from app.domain.session import
SimulationSession` or `from app.domain.session.session import SimulationSession`, matching
`app.domain.roles`. The import order here matters: `guards` and `machine` are import-clean of
`session.py`, and `session.py` reaches `ROLE_MODULES` at call time (see its `_role_modules`), so
`roles.registry -> roles.operator112 -> session.guards` never closes a cycle.
"""

from __future__ import annotations

from app.domain.session.guards import (
    DDS_GUARDS,
    OPERATOR_112_GUARDS,
    SESSION_GUARDS,
    TERMINAL_STAGE_STATES,
)
from app.domain.session.machine import SESSION_STATE_MACHINE
from app.domain.session.policy import (
    SESSION_POLICIES,
    ParticipantAssignmentRule,
    SessionPolicy,
)
from app.domain.session.session import (
    Incident,
    RoleStage,
    SessionParticipant,
    SimulationSession,
    StageState,
    create_session,
)
from app.domain.session.transitions import (
    DDS_TRANSITIONS,
    OPERATOR_112_TRANSITIONS,
    SESSION_TRANSITIONS,
)

__all__ = [
    "DDS_GUARDS",
    "DDS_TRANSITIONS",
    "OPERATOR_112_GUARDS",
    "OPERATOR_112_TRANSITIONS",
    "SESSION_GUARDS",
    "SESSION_POLICIES",
    "SESSION_STATE_MACHINE",
    "SESSION_TRANSITIONS",
    "TERMINAL_STAGE_STATES",
    "Incident",
    "ParticipantAssignmentRule",
    "RoleStage",
    "SessionParticipant",
    "SessionPolicy",
    "SimulationSession",
    "StageState",
    "create_session",
]
