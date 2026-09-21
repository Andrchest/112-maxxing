"""World-event simulation: simulated time, the tick use case and the runner (D7, SPEC §12, §39).

`world_state_loader` is deliberately **not** re-exported here. It is the one application module
holding both the world-truth and the caller-belief repository (D3), and the only module allowed to
import it is `tick_session`; exporting it from the package would put it one `from … import` away
from every DDS- and operator-facing use case, which is exactly the visibility D3 forbids.
"""

from app.application.simulation.runner import SimulationRunner
from app.application.simulation.sim_time import sim_ms
from app.application.simulation.tick_session import TickResult, TickSession

__all__ = ["SimulationRunner", "TickResult", "TickSession", "sim_ms"]
