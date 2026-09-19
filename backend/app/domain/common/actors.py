"""`ActorRef` (HLD `10-domain-model.md` §10.1, §10.6, §10.8, D5).

One home for the "who performed an action" value object: `{actor_type, actor_id}`. Referenced by
`CardRevision` and `set_field` (`layers/operator_card.py`, §10.6), `GuardContext`
(`common/state_machine.py`, §10.8) and `DomainEvent` (`events/session_event.py`, §10.13). Every
other module imports it from here rather than redefining it (consolidation ruling R1 of this
task's brief: two ad hoc copies previously existed in `common/state_machine.py` and
`layers/operator_card.py`; both now import this one).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import UserId
from app.domain.enums import ActorType


class ActorRef(BaseModel):
    """Who performed an action: `{actor_type, actor_id}` (§10.1, §10.6, §10.8, §10.13)."""

    model_config = ConfigDict(frozen=True)

    actor_type: ActorType
    actor_id: UserId | None = None
