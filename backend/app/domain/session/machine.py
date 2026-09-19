"""`SESSION_STATE_MACHINE` — `SESSION_TRANSITIONS` wired to `SESSION_GUARDS` (HLD
`10-domain-model.md` §10.8, D6).

The two stage machines are owned by their `RoleModule` (`roles/operator112.py`, `roles/dds.py`),
which is where §10.9 puts them; the session machine has no such owner, so it is built here and
used by `SimulationSession`'s methods (`session/session.py`). Only backend use cases fire triggers
on it (D6).
"""

from __future__ import annotations

from app.domain.common.state_machine import StateMachine
from app.domain.enums import SessionState
from app.domain.session.guards import SESSION_GUARDS
from app.domain.session.transitions import SESSION_TRANSITIONS

SESSION_STATE_MACHINE: StateMachine[SessionState] = StateMachine(
    SESSION_TRANSITIONS, SESSION_GUARDS
)
