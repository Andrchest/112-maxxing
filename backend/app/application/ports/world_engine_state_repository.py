"""`WorldEngineStateRepository` port — `world_engine_states` (additive, E6; D3, D5, D7).

The pure engine of `app.domain.world` carries bookkeeping that is neither a fact about the world
nor a fact about the caller: how often each world event has already fired, when it last fired,
which future firings are queued, how often each emotion rule was applied, which stage states have
ever been reached, and how far simulated time has been advanced. D3 forbids merging that into
`incident_world_states` — world truth holds *facts* only — so it has its own table, one row per
incident.

`EventIndex` is deliberately **not** stored. It is a pure fold of the session's own action events
(§10.11 determinism rule 1), so it is rebuilt from `session_events` on every load and the event log
stays the single source of what happened (D5). `last_folded_seq_no` is the boundary between "already
folded into the index" and "a `PendingAction` for the next tick".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.domain.common.ids import IncidentId
from app.domain.enums import RoleType
from app.domain.world.engine import ScheduledTrigger

__all__ = ["WorldEngineState", "WorldEngineStateRepository"]


class WorldEngineState(BaseModel):
    """One `world_engine_states` row: the engine's bookkeeping for one incident (E6)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: IncidentId
    last_tick_ms: int = 0
    last_folded_seq_no: int = 0
    occurrences: Mapping[str, int] = Field(default_factory=dict)
    last_fired_ms: Mapping[str, int] = Field(default_factory=dict)
    scheduled: tuple[ScheduledTrigger, ...] = ()
    emotion_applications: Mapping[str, int] = Field(default_factory=dict)
    reached_states: Mapping[RoleType, frozenset[str]] = Field(default_factory=dict)


@runtime_checkable
class WorldEngineStateRepository(Protocol):
    """`world_engine_states` — engine-written only (additive, E6)."""

    async def get(self, incident_id: IncidentId) -> WorldEngineState | None:
        """The incident's engine bookkeeping, or `None` when the row does not exist."""
        ...

    async def add(self, state: WorldEngineState) -> None:
        """Insert the zeroed row session creation makes."""
        ...

    async def save(self, state: WorldEngineState) -> None:
        """Write back the bookkeeping of a tick that changed something."""
        ...
