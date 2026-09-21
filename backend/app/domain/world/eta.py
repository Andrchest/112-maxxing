"""`EtaModel` and `ScenarioDefinedEta` (HLD `10-domain-model.md` §10.7, D7, SPEC §11).

D7: "Resource movement (turnout delay, travel time, on-scene work) is scheduled by the same engine
from scenario-defined ETA data through a local `EtaModel` port (`ScenarioDefinedEta`
implementation)." §10.7 adds that `EtaProfile`'s five values "are the only ETA input; the
`EtaModel` port implementation `ScenarioDefinedEta` reads them verbatim".

The port is a `typing.Protocol`, so `app.domain.dds.resources` can type its timed guards against it
without importing this package at runtime (`app.domain.world.__init__` imports the engine, which
imports `app.domain.dds.resources` — a runtime import back would close that cycle). Every method
returns **milliseconds**, because every offset the domain deals with is `…_ms`.

SPEC §11 also allows an ETA "computed by a local deterministic module"; such a model is another
implementation of this Protocol and needs no change here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only; see the module docstring
    from app.domain.dds.resources import EmergencyResource

__all__ = ["EtaModel", "ScenarioDefinedEta"]


class EtaModel(Protocol):
    """The five durations the resource state machine schedules on, in milliseconds (§10.7)."""

    def turnout_delay_ms(self, resource: EmergencyResource) -> int: ...

    def travel_time_ms(self, resource: EmergencyResource) -> int: ...

    def setup_ms(self, resource: EmergencyResource) -> int: ...

    def on_scene_work_ms(self, resource: EmergencyResource) -> int: ...

    def return_time_ms(self, resource: EmergencyResource) -> int: ...


class ScenarioDefinedEta:
    """Reads `EmergencyResource.eta` verbatim (§10.7): seconds × 1000, nothing else.

    Stateless and pure — no clock, no randomness, no I/O. An `AlterResourceAvailability` effect
    with `eta_multiplier != 1` rescales the resource's own `EtaProfile` (`world/apply.py`), so this
    model never needs a multiplier of its own.
    """

    def turnout_delay_ms(self, resource: EmergencyResource) -> int:
        return resource.eta.turnout_delay_seconds * 1000

    def travel_time_ms(self, resource: EmergencyResource) -> int:
        return resource.eta.travel_time_seconds * 1000

    def setup_ms(self, resource: EmergencyResource) -> int:
        return resource.eta.setup_seconds * 1000

    def on_scene_work_ms(self, resource: EmergencyResource) -> int:
        return resource.eta.on_scene_work_seconds * 1000

    def return_time_ms(self, resource: EmergencyResource) -> int:
        return resource.eta.return_time_seconds * 1000
